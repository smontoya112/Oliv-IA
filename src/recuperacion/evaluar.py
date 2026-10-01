"""Mide la recuperación final (top-10) contra el legal_basis de las muestras y la compara con
la línea base de la fase 5 (data/index/eval_recuperacion.json).

    python -m src.recuperacion.evaluar data/recuperacion/sample_50.jsonl [otra.jsonl ...]
    python -m src.recuperacion.evaluar data/recuperacion/*.jsonl --salida data/recuperacion/ablaciones.json

Usa las mismas definiciones que src.indice.evaluar, sobre los 10 primeros pasajes de la
salida (que es lo que cuenta evaluate.citas_respaldadas):
  * cobertura_cuerpo@10 / cobertura_articulo@10: fracción de las citas del legal_basis que
    aparecen en el TEXTO de esos pasajes (evaluate.py puntúa por cuerpo normativo).
  * hit_doc@10: algún pasaje viene de un documento que nombra un cuerpo del legal_basis.
legal_basis se usa SOLO aquí, para evaluar: nunca dentro de la recuperación.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

import citations
from src.indice.build import CONFIG, leer_chunks
from src.indice.evaluar import CITAS, leer_muestras

log = logging.getLogger("recuperacion")


def _media(xs: list) -> float | None:
    xs = [x for x in xs if x is not None]
    return round(float(np.mean(xs)), 4) if xs else None


def _contexto_corpus(indice: Path):
    """(cuerpos del corpus, cuerpos por documento): mismas definiciones que la fase 5."""
    from src.indice.evaluar import citas_chunks
    cfg = json.loads((indice / CONFIG).read_text(encoding="utf-8"))
    chunks = leer_chunks(Path(cfg["chunks"]), cfg.get("limite"))
    cit_cab, _ = citas_chunks(chunks["texto"], indice / CITAS,
                              f"{cfg['sha256_chunks']}:{cfg.get('limite')}")
    cuerpos_corpus = set().union(*(citations.bodies(c) for c in cit_cab))
    cuerpos_doc: dict[str, set] = defaultdict(set)
    for d, cs in zip(chunks["doc_id"], cit_cab):
        cuerpos_doc[d] |= citations.bodies(cs)
    return cuerpos_corpus, cuerpos_doc


def evaluar_corrida(ruta: Path, items: dict[int, dict], cuerpos_corpus: set,
                    cuerpos_doc: dict[str, set]) -> dict:
    filas = []
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        r = json.loads(linea)
        it = items.get(r["id"])
        if it is None:
            continue
        ref = citations.extract(it.get("legal_basis") or "")
        ref_cuerpos = citations.bodies(ref) & cuerpos_corpus
        if not ref_cuerpos:
            continue                                         # sin citas o fuera del corpus
        ref_art = {c for c in citations.article_level(ref) if (c[0], c[1], c[2]) in ref_cuerpos}
        top = (r.get("pasajes") or [])[:10]
        respaldo = set()
        for p in top:
            respaldo |= citations.extract(str(p.get("texto") or ""))
        docs_rel = {d for d, cs in cuerpos_doc.items() if cs & ref_cuerpos}
        filas.append({
            "id": r["id"], "formato": it.get("formato"),
            "cuerpo@10": len(ref_cuerpos & citations.bodies(respaldo)) / len(ref_cuerpos),
            "articulo@10": (len(ref_art & respaldo) / len(ref_art)) if ref_art else None,
            "hit_doc@10": float(any(p["doc_id"] in docs_rel for p in top)),
            "latencia_ms": r.get("latencia_ms"),
        })

    def agregar(sel: list[dict]) -> dict:
        return {"n": len(sel), "cobertura_cuerpo@10": _media([f["cuerpo@10"] for f in sel]),
                "cobertura_articulo@10": _media([f["articulo@10"] for f in sel]),
                "hit_doc@10": _media([f["hit_doc@10"] for f in sel]),
                "s_por_item": _media([f["latencia_ms"] / 1000 for f in sel
                                      if f["latencia_ms"] is not None])}

    por_formato = {fmt: agregar([f for f in filas if f["formato"] == fmt])
                   for fmt in sorted({f["formato"] for f in filas})}
    return {"todos": agregar(filas), "por_formato": por_formato, "items": filas}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("corridas", type=Path, nargs="+")
    ap.add_argument("--indice", type=Path, default=Path("data/index"))
    ap.add_argument("--muestras", type=Path, default=Path("data/sample_50.jsonl"))
    ap.add_argument("--salida", type=Path, default=Path("data/recuperacion/ablaciones.json"))
    args = ap.parse_args()
    salida_std = logging.StreamHandler(sys.stdout)
    salida_std.addFilter(lambda r: r.levelno < logging.ERROR)
    salida_err = logging.StreamHandler(sys.stderr)
    salida_err.setLevel(logging.ERROR)
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[salida_std, salida_err])

    items = {it["id"]: it for it in leer_muestras(args.muestras)}
    cuerpos_corpus, cuerpos_doc = _contexto_corpus(args.indice)
    resultados = {}
    for ruta in args.corridas:
        if ruta.name.endswith(".config.json"):
            continue
        res = evaluar_corrida(ruta, items, cuerpos_corpus, cuerpos_doc)
        resultados[ruta.stem] = res
        t = res["todos"]
        log.info("RESULTADO %-22s n=%s cuerpo@10 %s  articulo@10 %s  hit_doc@10 %s  s/ítem %s",
                 ruta.stem, t["n"], t["cobertura_cuerpo@10"], t["cobertura_articulo@10"],
                 t["hit_doc@10"], t["s_por_item"])
    base = args.indice / "eval_recuperacion.json"
    if base.exists():
        b = json.loads(base.read_text(encoding="utf-8"))["resultados"]
        for nombre in ("bm25", "denso", "rrf"):
            r = b.get(nombre, {}).get("todos", {})
            log.info("BASE fase 5 %-6s cuerpo@10 %s  articulo@10 %s  (cuerpo@50 %s)", nombre,
                     r.get("cobertura_cuerpo@10"), r.get("cobertura_articulo@10"),
                     r.get("cobertura_cuerpo@50"))
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    args.salida.write_text(json.dumps(resultados, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("detalle en %s", args.salida)


if __name__ == "__main__":
    main()
