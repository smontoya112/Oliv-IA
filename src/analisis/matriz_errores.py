"""Paso 9.2: matriz de errores por ítem sobre sample_50.

Para cada pregunta recorre las etapas del sistema y marca en cuál se pierde la evidencia:
corpus -> top 10 de la recuperación -> cita en la respuesta -> formato. El legal_basis se usa
SOLO para diagnosticar, nunca dentro del sistema.

    python -m src.analisis.matriz_errores \\
        --submission data/processed/verificacion/qwen3-8b.jsonl \\
        --recuperacion data/recuperacion/sample_50.jsonl \\
        --salida data/processed/analisis/matriz_qwen3-8b.csv

La Fase 6 solo guarda el top 10, así que no hay columna de top 50 (habría que guardar los
candidatos antes del reranker para añadirla).
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))

import citations  # noqa: E402
import evaluate  # noqa: E402

CAMPOS = ["id", "formato", "area", "complejidad", "sub_tarea", "n_ref", "en_corpus",
          "cuerpo@10", "articulo@10", "hit_cuerpo_top10", "abstencion", "cita_acierta",
          "n_citadas", "citas_incorrectas", "cerrada_acierta", "formato_ok", "etapa_falla"]


def _jsonl(ruta: Path) -> list[dict]:
    return [json.loads(l) for l in ruta.read_text(encoding="utf-8").splitlines() if l.strip()]


def _cuerpos_texto(texto: str) -> set:
    return citations.bodies(citations.extract(texto))


def cuerpos_del_corpus(chunks: Path, cache: Path) -> set:
    """Cuerpos normativos citados en el texto de algún chunk del corpus (con caché JSON)."""
    if cache.exists():
        return {tuple(x) for x in json.loads(cache.read_text(encoding="utf-8"))}
    import pyarrow.parquet as pq
    from concurrent.futures import ProcessPoolExecutor
    textos = pq.read_table(chunks, columns=["texto"]).column("texto").to_pylist()
    cuerpos: set = set()
    with ProcessPoolExecutor() as ex:
        for c in ex.map(_cuerpos_texto, textos, chunksize=500):
            cuerpos |= c
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(sorted(cuerpos, key=str), ensure_ascii=False), encoding="utf-8")
    return cuerpos


def etapa_falla(f: dict) -> str:
    """Primera etapa en la que se pierde el ítem, en orden de flujo."""
    if f["n_ref"] == 0:
        return "sin_citas_ref"                    # legal_basis es prosa: no hay contra qué comparar
    if not f["en_corpus"]:
        return "fuera_corpus"
    if not f["hit_cuerpo_top10"]:
        return "no_en_top10"
    if f["abstencion"]:
        return "abstuvo"
    if not f["cita_acierta"]:
        return "recuperado_no_citado"
    if f["cerrada_acierta"] is False:
        return "cerrada_incorrecta"
    return "ok"


def fila(it: dict, sub: dict | None, rec: dict | None, corpus: set, problemas: dict) -> dict:
    ref = citations.extract(it.get("legal_basis") or "")
    ref_cuerpos = citations.bodies(ref)
    ref_corpus = ref_cuerpos & corpus
    top = ((rec or {}).get("pasajes") or [])[:10]
    respaldo: set = set()
    for p in top:
        respaldo |= citations.extract(str(p.get("texto") or ""))
    ref_art = {c for c in citations.article_level(ref) if (c[0], c[1], c[2]) in ref_corpus}
    abst = bool(sub is None or sub.get("abstencion"))
    cita = {"aciertos": 0, "n_citadas": 0, "incorrectas": 0}
    if sub is not None and not abst and ref:
        cita = citations.score(evaluate.answer_text(sub), it.get("legal_basis") or "",
                               evaluate.citas_respaldadas(sub))
    cerrada = None
    if it["formato"] == "multiple_choice":
        cerrada = bool(sub and not abst and
                       sub.get("respuesta_correcta") == it.get("respuesta_correcta"))
    f = {
        "id": it["id"], "formato": it["formato"], "area": it.get("area"),
        "complejidad": it.get("complejidad"), "sub_tarea": it.get("sub_tarea"),
        "n_ref": len(ref_cuerpos), "en_corpus": bool(ref_corpus),
        "cuerpo@10": round(len(ref_corpus & citations.bodies(respaldo)) / len(ref_corpus), 3)
                     if ref_corpus else None,
        "articulo@10": round(len(ref_art & respaldo) / len(ref_art), 3) if ref_art else None,
        "hit_cuerpo_top10": bool(ref_corpus & citations.bodies(respaldo)),
        "abstencion": abst, "cita_acierta": cita["aciertos"] > 0,
        "n_citadas": cita["n_citadas"], "citas_incorrectas": cita["incorrectas"],
        "cerrada_acierta": cerrada, "formato_ok": it["id"] not in problemas,
    }
    f["etapa_falla"] = etapa_falla(f)
    return f


def resumen(filas: list[dict]) -> dict:
    por_etapa = Counter(f["etapa_falla"] for f in filas)
    por_formato: dict[str, Counter] = {}
    for f in filas:
        por_formato.setdefault(f["formato"], Counter())[f["etapa_falla"]] += 1
    return {"n": len(filas), "por_etapa": dict(por_etapa),
            "por_formato": {k: dict(v) for k, v in sorted(por_formato.items())},
            "formato_invalido": sum(not f["formato_ok"] for f in filas)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--submission", type=Path,
                    default=Path("data/processed/verificacion/qwen3-8b.jsonl"))
    ap.add_argument("--recuperacion", type=Path, default=Path("data/recuperacion/sample_50.jsonl"))
    ap.add_argument("--muestras", type=Path, default=Path("data/sample_50.jsonl"))
    ap.add_argument("--chunks", type=Path, default=Path("data/processed/chunks.parquet"))
    ap.add_argument("--cache-corpus", type=Path,
                    default=Path("data/processed/analisis/cuerpos_corpus.json"))
    ap.add_argument("--salida", type=Path,
                    default=Path("data/processed/analisis/matriz_errores.csv"))
    args = ap.parse_args()

    items = _jsonl(args.muestras)
    subs = {s["id"]: s for s in _jsonl(args.submission)}
    recs = {r["id"]: r for r in _jsonl(args.recuperacion)}
    corpus = cuerpos_del_corpus(args.chunks, args.cache_corpus)
    avisos = evaluate.validate(list(subs.values()), {it["id"] for it in items})
    problemas = {int(a.split()[1].rstrip(":")) for a in avisos if a.startswith("item ")}

    filas = [fila(it, subs.get(it["id"]), recs.get(it["id"]), corpus, problemas) for it in items]
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    with args.salida.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, CAMPOS)
        w.writeheader()
        w.writerows(filas)
    print(json.dumps(resumen(filas), ensure_ascii=False, indent=2))
    print(f"matriz -> {args.salida}")


if __name__ == "__main__":
    main()
