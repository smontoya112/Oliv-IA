"""Auditoría de integridad (checklist 13.2): modelos cerrados y fugas por n-gramas.

1. Modelos cerrados: busca en el código del pipeline (src/, config/, jobs/, scripts/) clientes o nombres de modelos de APIs cerradas.
   El juez de texto libre del evaluador oficial (scripts/evaluate.py) y los jobs de RAGAS lo usan solo para EVALUAR (OpenRouter):
   se listan aparte, no forman parte del sistema que responde.
2. Fugas: compara las preguntas (enunciado y opciones) de los archivos dados con el texto procesado del corpus por n-gramas de palabras.
   Una pregunta con muchos n-gramas dentro de un mismo documento del corpus indicaría que el corpus trae el banco de preguntas o material de estudio con
   ellas. No se imprime ni se guarda texto de las preguntas: solo conteos, ids y doc_id.

    python -m src.analisis.auditoria_integridad --preguntas data/test_992.jsonl data/sample_50.jsonl \
        --texto data/processed_base/texto --salida experimentos/claude/auditoria
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

CERRADOS = re.compile(r"\b(openai|anthropic|google\.generativeai|genai|gemini|cohere|mistralai|vertexai|gpt-[0-9a-z.\-]+|claude-[0-9a-z.\-]+|"
                      r"chatgpt)\b", re.I)
USO_EVALUACION = ("scripts/evaluate.py", "scripts/requirements-evaluador.txt", "jobs/ragas_con_timeout.py", "jobs/ragas_por_item.py",
                  "jobs/ragas_claude.sh", "jobs/evaluar_ragas.sh", "jobs/verificar.sh", "src/analisis/auditoria_integridad.py")
PALABRA = re.compile(r"\w+", re.U)


def palabras(texto: str) -> list[str]:
    return PALABRA.findall(texto.lower())


def modelos_cerrados(raiz: Path) -> dict:
    sistema, evaluacion = [], []
    for carpeta in ("src", "config", "jobs", "scripts"):
        for f in sorted((raiz / carpeta).rglob("*")):
            if not f.is_file() or f.suffix not in (".py", ".sh", ".json", ".txt", ".yaml", ".toml") or "__pycache__" in f.parts:
                continue
            rel = f.relative_to(raiz).as_posix()
            for n, linea in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                m = CERRADOS.search(linea)
                if m:
                    (evaluacion if rel in USO_EVALUACION else sistema).append({"archivo": rel, "linea": n, "coincidencia": m.group(0)})
    decoder = json.loads((raiz / "config" / "responder.json").read_text(encoding="utf-8"))["modelo"]
    return {"decoder_configurado": decoder, "coincidencias_en_el_sistema": sistema, "coincidencias_solo_evaluacion": evaluacion}


def cargar_preguntas(rutas: list[Path]) -> dict[str, list[dict]]:
    res = {}
    for r in rutas:
        items = [json.loads(l) for l in r.read_text(encoding="utf-8").splitlines() if l.strip()]
        res[r.name] = items
    return res


def texto_pregunta(it: dict) -> str:
    opciones = it.get("opciones") or {}
    return " ".join([it.get("pregunta", "")] + [str(v) for v in (opciones.values() if isinstance(opciones, dict) else opciones)])


def fugas(preguntas: dict[str, list[dict]], dir_texto: Path, n: int) -> dict:
    # n-gramas de cada pregunta -> (archivo, id)
    indice: dict[int, list[tuple[str, int]]] = defaultdict(list)
    total_gramas: dict[tuple[str, int], int] = {}
    for archivo, items in preguntas.items():
        for it in items:
            w = palabras(texto_pregunta(it))
            gramas = {hash(tuple(w[i:i + n])) for i in range(len(w) - n + 1)}
            total_gramas[(archivo, it["id"])] = len(gramas)
            for g in gramas:
                indice[g].append((archivo, it["id"]))
    aciertos: dict[tuple[str, int], Counter] = defaultdict(Counter)    # (archivo, id) -> doc_id -> n-gramas hallados
    n_docs = 0
    for f in sorted(dir_texto.glob("*.txt")):
        n_docs += 1
        w = palabras(f.read_text(encoding="utf-8", errors="replace"))
        vistos: set[int] = set()
        for i in range(len(w) - n + 1):
            g = hash(tuple(w[i:i + n]))
            if g in indice and g not in vistos:
                vistos.add(g)
                for clave in indice[g]:
                    aciertos[clave][f.stem] += 1
    resumen = {}
    for archivo, items in preguntas.items():
        filas = []
        for it in items:
            clave = (archivo, it["id"])
            tot = total_gramas[clave]
            doc, k = aciertos[clave].most_common(1)[0] if aciertos.get(clave) else (None, 0)
            filas.append({"id": it["id"], "formato": it.get("formato"), "n_gramas": tot, "max_en_un_documento": k,
                          "cobertura": round(k / tot, 3) if tot else 0.0, "doc_id": doc})
        con = [f for f in filas if f["max_en_un_documento"] > 0]
        resumen[archivo] = {
            "preguntas": len(items), "con_algun_n_grama_en_el_corpus": len(con),
            "con_cobertura_mayor_a_0_5": [f for f in filas if f["cobertura"] > 0.5],
            "con_cobertura_entre_0_2_y_0_5": [f for f in filas if 0.2 < f["cobertura"] <= 0.5],
            "cobertura_maxima": max((f["cobertura"] for f in filas), default=0.0),
            "mas_cubiertas": sorted(con, key=lambda f: -f["cobertura"])[:10],
        }
    return {"n": n, "documentos_revisados": n_docs, "por_archivo": resumen}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--raiz", type=Path, default=Path("."))
    ap.add_argument("--preguntas", type=Path, nargs="+", default=[Path("data/test_992.jsonl"), Path("data/sample_50.jsonl")])
    ap.add_argument("--texto", type=Path, default=Path("data/processed_base/texto"))
    ap.add_argument("--n", type=int, default=12, help="longitud del n-grama en palabras")
    ap.add_argument("--salida", type=Path, default=Path("experimentos/claude/auditoria"))
    args = ap.parse_args()
    raiz = args.raiz
    informe = {"modelos": modelos_cerrados(raiz)}
    rutas = [r for r in args.preguntas if r.exists()]
    if rutas and args.texto.exists():
        informe["fugas"] = fugas(cargar_preguntas(rutas), args.texto, args.n)
    args.salida.mkdir(parents=True, exist_ok=True)
    (args.salida / "auditoria.json").write_text(json.dumps(informe, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    m = informe["modelos"]
    print(f"RESULTADO decoder {m['decoder_configurado']} · coincidencias de modelos cerrados en el sistema: "
          f"{len(m['coincidencias_en_el_sistema'])} · solo en evaluación: {len(m['coincidencias_solo_evaluacion'])}")
    for archivo, r in informe.get("fugas", {}).get("por_archivo", {}).items():
        print(f"RESULTADO fugas {archivo}: {r['preguntas']} preguntas · con algún {args.n}-grama en el corpus: "
              f"{r['con_algun_n_grama_en_el_corpus']} · cobertura > 0,5: {len(r['con_cobertura_mayor_a_0_5'])} · "
              f"entre 0,2 y 0,5: {len(r['con_cobertura_entre_0_2_y_0_5'])} · máxima {r['cobertura_maxima']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
