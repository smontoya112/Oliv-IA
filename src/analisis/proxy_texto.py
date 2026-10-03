"""Proxy local (sin créditos) de la corrección en texto libre.

RAGAS `answer_correctness` = 0,75 · correctitud factual (un LLM juez compara afirmaciones de la
respuesta y de la esperada) + 0,25 · similitud semántica (coseno de embeddings e5-large, local).
Aquí se reproduce la parte semántica TAL CUAL (mismo encoder, sin prefijos, como en
scripts/evaluate.py) y la factual se aproxima con el F1 de palabras de contenido (sin
stopwords, con números y términos jurídicos). No sustituye al juez: sirve para ORDENAR variantes
sin gastar llamadas a OpenRouter. Para saber cuánto confiar en él, se compara con los RAGAS que ya
se midieron (llama-3.1-8b > qwen3-8b).

    python -m src.analisis.proxy_texto --submission data/processed/bench_generacion/qwen3-8b.jsonl
    python -m src.analisis.proxy_texto --submission X.jsonl --sin-embeddings    # solo la parte léxica

También informa la longitud generada contra la esperada (por formato) y el índice de citas.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import unicodedata
from collections import Counter
from pathlib import Path

import src.generacion  # noqa: F401  (agrega scripts/ al path)

PESO_FACTUAL, PESO_SEMANTICO = 0.75, 0.25
ENCODER = "intfloat/multilingual-e5-large"
_STOP = set("""a al algo ante con contra cual cuales cuando de del desde donde el ella ellas ello ellos en
entre era es esa esas ese eso esos esta estan estar este esto estos fue ha han hay la las le les lo
los mas me mi muy no nos o otra otro para pero por porque que quien se si sin sobre su sus tambien
tiene tienen un una unas uno unos y ya como ser son segun cada asi tal etc""".split())
_TOKEN = re.compile(r"\w+", re.UNICODE)


def _sin_tildes(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")


def tokens(texto: str) -> list[str]:
    """Palabras de contenido: minúsculas, sin tildes, sin stopwords (se conservan los números)."""
    return [w for w in _TOKEN.findall(_sin_tildes(texto or "").lower())
            if w not in _STOP and (len(w) > 1 or w.isdigit())]


def f1_contenido(respuesta: str, referencia: str) -> float:
    """F1 de unigramas y bigramas de contenido (promedio de ambos)."""
    a, r = tokens(respuesta), tokens(referencia)
    if not a or not r:
        return 0.0

    def f1(x: Counter, y: Counter) -> float:
        comun = sum((x & y).values())
        if not comun:
            return 0.0
        p, rec = comun / sum(x.values()), comun / sum(y.values())
        return 2 * p * rec / (p + rec)

    uni = f1(Counter(a), Counter(r))
    bi = f1(Counter(zip(a, a[1:])), Counter(zip(r, r[1:]))) if len(a) > 1 and len(r) > 1 else uni
    return (uni + bi) / 2


def similitud_semantica(pares: list[tuple[str, str]], modelo: str = ENCODER) -> list[float]:
    """Coseno entre embeddings e5 (mean pooling + normalización, sin prefijos)."""
    import torch
    from transformers import AutoModel, AutoTokenizer
    dispositivo = "cuda" if torch.cuda.is_available() else "cpu"
    tok, enc = AutoTokenizer.from_pretrained(modelo), AutoModel.from_pretrained(modelo).to(dispositivo)
    enc.eval()

    def emb(textos: list[str]):
        lote = tok(textos, padding=True, truncation=True, max_length=512, return_tensors="pt").to(dispositivo)
        with torch.no_grad():
            h = enc(**lote).last_hidden_state
        m = lote["attention_mask"].unsqueeze(-1).to(h.dtype)
        v = (h * m).sum(1) / m.sum(1)
        return torch.nn.functional.normalize(v, dim=-1)

    res = []
    for k in range(0, len(pares), 8):
        trozo = pares[k: k + 8]
        a, b = emb([x or " " for x, _ in trozo]), emb([y or " " for _, y in trozo])
        res += (a * b).sum(-1).float().cpu().tolist()
    return res


def evaluar(entrega: list[dict], muestra: list[dict], con_embeddings: bool = True) -> dict:
    import evaluate                                  # scripts/evaluate.py (no se modifica)
    sub = {s["id"]: s for s in entrega}
    juzgados = [r for r in muestra if r["formato"] != "multiple_choice"]
    filas, pares = [], []
    for r in juzgados:
        s = sub.get(r["id"])
        texto = "" if (not s or s.get("abstencion")) else evaluate.ragas_text(s)
        filas.append({"id": r["id"], "formato": r["formato"], "sub_tarea": r.get("sub_tarea"),
                      "palabras": len(texto.split()),
                      "palabras_esperadas": len(str(r.get("respuesta_esperada") or "").split()),
                      "lexico": round(f1_contenido(texto, r.get("respuesta_esperada") or ""), 4)})
        pares.append((texto, r.get("respuesta_esperada") or ""))
    if con_embeddings:
        for f, c in zip(filas, similitud_semantica(pares)):
            f["semantico"] = round(max(c, 0.0), 4) if f["palabras"] else 0.0
            f["proxy"] = round(PESO_FACTUAL * f["lexico"] + PESO_SEMANTICO * f["semantico"], 4)
    else:
        for f in filas:
            f["proxy"] = f["lexico"]

    def media(xs):
        return round(sum(xs) / len(xs), 4) if xs else None

    por_formato = {}
    for fmt in ("semi_open", "open_ended"):
        fs = [f for f in filas if f["formato"] == fmt]
        por_formato[fmt] = {
            "n": len(fs), "proxy": media([f["proxy"] for f in fs]),
            "lexico": media([f["lexico"] for f in fs]),
            "semantico": media([f.get("semantico", 0) for f in fs]) if con_embeddings else None,
            "palabras_mediana": statistics.median([f["palabras"] for f in fs]) if fs else None,
            "palabras_esperadas_mediana": statistics.median([f["palabras_esperadas"] for f in fs]) if fs else None}
    return {"n_juzgados": len(filas), "proxy": media([f["proxy"] for f in filas]),
            "lexico": media([f["lexico"] for f in filas]),
            "semantico": media([f.get("semantico", 0) for f in filas]) if con_embeddings else None,
            "por_formato": por_formato, "filas": filas}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--submission", type=Path, required=True)
    ap.add_argument("--muestra", type=Path, default=Path("data/sample_50.jsonl"))
    ap.add_argument("--sin-embeddings", action="store_true")
    ap.add_argument("--salida", type=Path, help="JSON con el detalle por ítem")
    args = ap.parse_args()
    leer = lambda p: [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    r = evaluar(leer(args.submission), leer(args.muestra), not args.sin_embeddings)
    resumen = {k: v for k, v in r.items() if k != "filas"}
    print("RESULTADO proxy_texto", json.dumps(resumen, ensure_ascii=False))
    if args.salida:
        args.salida.parent.mkdir(parents=True, exist_ok=True)
        args.salida.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
