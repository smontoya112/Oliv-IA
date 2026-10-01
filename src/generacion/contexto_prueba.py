"""Pasajes de PRUEBA para desarrollar la fase 7 sin la fase 5/6 (índices) todavía lista.

Dos fuentes, ambas leyendo data/processed/chunks.parquet:
  - oraculo:  chunks de las normas de `legal_basis` de la muestra. Es un TECHO de calidad.
              Solo para desarrollo con sample_50: legal_basis no existe en el test ciego y
              esto NUNCA forma parte del pipeline de entrega.
  - bm25:     recuperación léxica simple, una línea base realista y sin dependencias.

    python -m src.generacion.contexto_prueba --modo oraculo --salida data/processed/contexto_oraculo.json
"""
from __future__ import annotations

import argparse
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import citations  # scripts/citations.py (el __init__ del paquete agrega scripts/ al path)

COLUMNAS = ["chunk_id", "doc_id", "norma_id_canonico", "texto", "inicio", "fin", "areas"]
_TOKEN = re.compile(r"\w+", re.UNICODE)


def cargar_chunks(ruta: Path = Path("data/processed/chunks.parquet")) -> list[dict]:
    import pyarrow.parquet as pq
    return pq.read_table(ruta, columns=COLUMNAS).to_pylist()


def _pasaje(c: dict, score: float | None = None) -> dict:
    p = {"doc_id": c["doc_id"], "inicio": c["inicio"], "fin": c["fin"], "texto": c["texto"]}
    if score is not None:
        p["score"] = round(float(score), 4)
    return p


def ids_de_legal_basis(legal_basis: str) -> list[str]:
    """legal_basis -> ids canónicos como los de chunks.norma_id_canonico
    (ej. ley_472_1998#art_46, o ley_472_1998 si la cita no llega a artículo)."""
    ids = []
    for cuerpo, num, anio, art in sorted(citations.extract(legal_basis),
                                         key=lambda c: tuple(str(x) for x in c)):
        base = "_".join(str(p) for p in (cuerpo, num, anio) if p)
        ids.append(f"{base}#art_{art}" if art else base)
    return ids


def oraculo(item: dict, chunks: list[dict], max_pasajes: int = 8) -> list[dict]:
    por_id = defaultdict(list)
    for c in chunks:
        nid = c["norma_id_canonico"]
        por_id[nid].append(c)
        if "#" in nid:                       # también por norma completa (cita sin artículo)
            por_id[nid.split("#")[0]].append(c)
    elegidos, vistos = [], set()
    for ident in ids_de_legal_basis(item.get("legal_basis") or ""):
        for c in por_id.get(ident, [])[:2]:
            if c["chunk_id"] not in vistos:
                vistos.add(c["chunk_id"])
                elegidos.append(_pasaje(c, 1.0))
    return elegidos[:max_pasajes]


def _tokens(texto: str) -> list[str]:
    t = unicodedata.normalize("NFKD", texto.lower())
    return _TOKEN.findall("".join(ch for ch in t if not unicodedata.combining(ch)))


class BM25Simple:
    def __init__(self, chunks: list[dict], k1: float = 1.5, b: float = 0.75):
        self.chunks, self.k1, self.b = chunks, k1, b
        self.tf = [Counter(_tokens(c["texto"])) for c in chunks]
        self.largo = [sum(t.values()) for t in self.tf]
        self.prom = sum(self.largo) / max(len(chunks), 1)
        self.post = defaultdict(list)
        for i, t in enumerate(self.tf):
            for w in t:
                self.post[w].append(i)

    def buscar(self, consulta: str, k: int = 8) -> list[dict]:
        n, puntajes = len(self.chunks), defaultdict(float)
        for w in set(_tokens(consulta)):
            docs = self.post.get(w, [])
            if not docs:
                continue
            idf = math.log(1 + (n - len(docs) + 0.5) / (len(docs) + 0.5))
            for i in docs:
                f = self.tf[i][w]
                puntajes[i] += idf * f * (self.k1 + 1) / (
                    f + self.k1 * (1 - self.b + self.b * self.largo[i] / self.prom))
        top = sorted(puntajes, key=puntajes.get, reverse=True)[:k]
        return [_pasaje(self.chunks[i], puntajes[i]) for i in top]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--modo", choices=["oraculo", "bm25"], required=True)
    ap.add_argument("--muestra", type=Path, default=Path("data/sample_50.jsonl"))
    ap.add_argument("--chunks", type=Path, default=Path("data/processed/chunks.parquet"))
    ap.add_argument("--salida", type=Path, required=True)
    ap.add_argument("--k", type=int, default=8)
    args = ap.parse_args()

    items = [json.loads(l) for l in args.muestra.read_text(encoding="utf-8").splitlines() if l.strip()]
    chunks = cargar_chunks(args.chunks)
    if args.modo == "oraculo":
        res = {it["id"]: oraculo(it, chunks, args.k) for it in items}
    else:
        bm = BM25Simple(chunks)
        res = {it["id"]: bm.buscar(it["pregunta"] + " " + " ".join((it.get("opciones") or {}).values()),
                                   args.k) for it in items}
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    args.salida.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    vacios = sum(1 for v in res.values() if not v)
    print(f"{len(res)} ítems, {vacios} sin pasajes -> {args.salida}")


if __name__ == "__main__":
    main()
