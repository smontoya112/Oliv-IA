"""Cobertura del enriquecimiento: de las preguntas que nombran una norma que se descargó, ¿cuántas la recuperan en el top-10?

Entradas: data/enriquecimiento/<preguntas>/normas.json (lo que dejó jobs/enriquecer_corpus.sh), el corpus (data/md) y la
recuperación de esas preguntas con el índice nuevo (src.recuperacion.pipeline). Solo usa el texto de las preguntas.

    # 1. subconjunto de preguntas que nombran normas descargadas
    python -m src.analisis.cobertura_enriquecimiento subconjunto --preguntas data/test_992.jsonl \
        --normas data/enriquecimiento/test_992/normas.json --salida data/exp/enriquecimiento_preguntas.jsonl
    # 2. recuperación con el índice (GPU)
    python -m src.recuperacion.pipeline --preguntas data/exp/enriquecimiento_preguntas.jsonl \
        --indice data/index_base --salida data/exp/enriquecimiento_recuperacion.jsonl
    # 3. cobertura
    python -m src.analisis.cobertura_enriquecimiento medir --normas data/enriquecimiento/test_992/normas.json \
        --recuperacion data/exp/enriquecimiento_recuperacion.jsonl --salida experimentos/claude/corpus_enriquecido/cobertura.json
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path


def _jsonl(ruta: Path) -> list[dict]:
    return [json.loads(l) for l in ruta.read_text(encoding="utf-8").splitlines() if l.strip()]


def pares(normas: list[dict], md: Path) -> list[tuple[str, int]]:
    """(doc_id, id de pregunta) de las normas marcadas «descargar como X» cuyo Markdown ya está en el corpus."""
    res = []
    for n in normas:
        m = re.match(r"descargar como (\S+)", str(n.get("accion", "")))
        if m and (md / f"{m.group(1)}.md").exists():
            res += [(m.group(1), int(i)) for i in n.get("preguntas", [])]
    return res


def cmd_subconjunto(args) -> int:
    normas = json.loads(args.normas.read_text(encoding="utf-8"))
    ids = {i for _, i in pares(normas, args.md)}
    items = [it for it in _jsonl(args.preguntas) if it["id"] in ids]
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    with args.salida.open("w", encoding="utf-8", newline="\n") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    print(f"RESULTADO {len(items)} preguntas que nombran normas descargadas -> {args.salida}")
    return 0


def cmd_medir(args) -> int:
    normas = json.loads(args.normas.read_text(encoding="utf-8"))
    rec = {r["id"]: r for r in _jsonl(args.recuperacion)}
    filas, por_doc = [], defaultdict(list)
    for doc_id, i in pares(normas, args.md):
        if i not in rec:
            continue
        docs = [p["doc_id"] for p in rec[i]["pasajes"][: args.k]]
        pos = docs.index(doc_id) + 1 if doc_id in docs else None
        filas.append({"doc_id": doc_id, "pregunta": i, "formato": rec[i].get("formato"), "posicion_primer_pasaje": pos,
                      "pasajes_del_doc_en_top": sum(d == doc_id for d in docs)})
        por_doc[doc_id].append(pos is not None)
    n, hit = len(filas), sum(f["posicion_primer_pasaje"] is not None for f in filas)
    resumen = {"k": args.k, "pares_norma_pregunta": n, "recuperadas_en_top_k": hit,
               "tasa": round(hit / n, 4) if n else None,
               "normas_con_alguna_pregunta_que_la_recupera": sum(any(v) for v in por_doc.values()),
               "normas": len(por_doc), "detalle": filas}
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    args.salida.write_text(json.dumps(resumen, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    print(f"RESULTADO pares norma-pregunta: {n} · la norma nueva aparece en el top-{args.k}: {hit} ({resumen['tasa']}) · "
          f"normas recuperadas por al menos una pregunta: {resumen['normas_con_alguna_pregunta_que_la_recupera']}/{len(por_doc)}")
    for d, v in sorted(por_doc.items()):
        if not any(v):
            print(f"  ninguna pregunta recupera {d} ({len(v)} preguntas)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("subconjunto")
    s.add_argument("--preguntas", type=Path, default=Path("data/test_992.jsonl"))
    s.add_argument("--normas", type=Path, default=Path("data/enriquecimiento/test_992/normas.json"))
    s.add_argument("--md", type=Path, default=Path("data/md"))
    s.add_argument("--salida", type=Path, default=Path("data/exp/enriquecimiento_preguntas.jsonl"))
    m = sub.add_parser("medir")
    m.add_argument("--normas", type=Path, default=Path("data/enriquecimiento/test_992/normas.json"))
    m.add_argument("--md", type=Path, default=Path("data/md"))
    m.add_argument("--recuperacion", type=Path, default=Path("data/exp/enriquecimiento_recuperacion.jsonl"))
    m.add_argument("--salida", type=Path, default=Path("experimentos/claude/corpus_enriquecido/cobertura.json"))
    m.add_argument("-k", type=int, default=10)
    args = ap.parse_args()
    return {"subconjunto": cmd_subconjunto, "medir": cmd_medir}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
