"""Fase 5 completa: data/processed/chunks.parquet -> data/index/ (FAISS + BM25 + index_config.json).

    python -m src.indice.build                                  # todo (en GPU: jobs/indice.sh)
    python -m src.indice.build --solo lexico                    # solo BM25 (no necesita GPU)
    python -m src.indice.build --limite 300 --salida data/index_prueba   # prueba rápida en CPU

La fila i de chunks.parquet es el id i de FAISS y de BM25 (chunk_ids.json guarda el orden).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import platform
import sys
import time
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

from src.indice import denso, encoder, lexico

log = logging.getLogger("indice")
CONFIG = "index_config.json"
COLUMNAS = ["chunk_id", "doc_id", "texto", "sha1_texto"]


def sha256(ruta: Path) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def leer_chunks(ruta: Path, limite: int | None = None) -> dict[str, list]:
    tabla = pq.read_table(ruta, columns=COLUMNAS)
    if limite:
        tabla = tabla.slice(0, limite)
    return tabla.to_pydict()


def _versiones() -> dict[str, str]:
    v = {"python": platform.python_version()}
    for paquete in ("faiss-cpu", "bm25s", "torch", "transformers", "numpy", "pyarrow"):
        try:
            v[paquete] = metadata.version(paquete)
        except metadata.PackageNotFoundError:
            pass
    return v


def construir_lexico(chunks: dict, salida: Path, stem: bool) -> dict:
    t0 = time.time()
    retriever = lexico.construir(chunks["texto"], lexico.crear_stemmer(stem))
    lexico.guardar(salida, retriever)
    log.info("BM25: %d chunks, vocabulario %d (%.0f s)", len(chunks["texto"]),
             len(retriever.vocab_dict), time.time() - t0)
    return {"libreria": "bm25s", "k1": lexico.K1, "b": lexico.B, "stemmer": "spanish" if stem else None,
            "vocabulario": len(retriever.vocab_dict), "stopwords": len(lexico.STOPWORDS),
            "tokenizador": "src.indice.lexico.tokenizar (sin tildes, minúsculas, conserva números, "
                           "sentencias como c355)",
            "segundos": round(time.time() - t0, 1)}


def construir_denso(chunks: dict, salida: Path, batch: int, device: str | None,
                    modelo: str, revision: str | None) -> dict:
    t0 = time.time()
    enc = encoder.Encoder(modelo=modelo, revision=revision, device=device)
    log.info("encoder %s@%s en %s (fp16=%s)", enc.modelo, (enc.revision or "-")[:8], enc.device,
             enc.fp16)
    stats = {}

    def codificar(textos: list[str]) -> np.ndarray:
        lon = enc.longitudes(textos)
        stats.update(p50=int(np.percentile(lon, 50)), p95=int(np.percentile(lon, 95)),
                     max=int(lon.max()), truncados=int((lon > enc.max_tokens).sum()))
        log.info("tokens por chunk: p50 %(p50)d, p95 %(p95)d, máx %(max)d, truncados %(truncados)d",
                 stats)
        t1 = time.time()
        vec = enc.encode(textos, batch=batch, longitudes=lon)
        stats["segundos_encoding"] = round(time.time() - t1, 1)
        return vec

    emb, n_unicos = denso.vectores_unicos(chunks["texto"], chunks["sha1_texto"], codificar)
    log.info("textos únicos codificados: %d de %d filas", n_unicos, len(emb))
    indice = denso.construir(emb)
    denso.guardar(salida, indice, emb)
    log.info("FAISS IndexFlatIP: %d vectores de dim %d (%.0f s)", indice.ntotal, indice.d,
             time.time() - t0)
    return {"modelo": enc.modelo, "revision": enc.revision, "pooling": "cls + normalización L2",
            "dim": indice.d, "metrica": "producto interno (= coseno)", "tipo_indice": "IndexFlatIP",
            "device": enc.device, "fp16": enc.fp16, "batch": batch, "max_tokens": enc.max_tokens,
            "n_textos_unicos": n_unicos, "tokens": stats,
            "sha256_faiss": sha256(salida / denso.INDICE),
            "segundos": round(time.time() - t0, 1)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--chunks", type=Path, default=Path("data/processed/chunks.parquet"))
    ap.add_argument("--salida", type=Path, default=Path("data/index"))
    ap.add_argument("--limite", type=int, help="solo las primeras N filas (pruebas)")
    ap.add_argument("--solo", choices=["lexico", "denso"])
    ap.add_argument("--batch", type=int, help="lote del encoder (por defecto 128 en GPU, 8 en CPU)")
    ap.add_argument("--device", help="cuda / cpu (por defecto: cuda si está disponible)")
    ap.add_argument("--stem", action="store_true", help="BM25 con stemming (PyStemmer, spanish)")
    ap.add_argument("--modelo", default=encoder.MODELO, help="encoder de HF o carpeta local")
    ap.add_argument("--revision", default=encoder.REVISION, help="commit de HF ('' para ninguno)")
    args = ap.parse_args()
    # Avance -> stdout (.out del job); solo los ERROR -> stderr (.err del job).
    salida_std = logging.StreamHandler(sys.stdout)
    salida_std.addFilter(lambda r: r.levelno < logging.ERROR)
    salida_err = logging.StreamHandler(sys.stderr)
    salida_err.setLevel(logging.ERROR)
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[salida_std, salida_err])

    chunks = leer_chunks(args.chunks, args.limite)
    sha_chunks = sha256(args.chunks)
    n = len(chunks["chunk_id"])
    log.info("chunks: %d filas de %d documentos (%s)", n, len(set(chunks["doc_id"])), args.chunks)
    args.salida.mkdir(parents=True, exist_ok=True)
    denso.guardar_orden(args.salida, chunks["chunk_id"], sha_chunks)

    # Con --solo se conserva la sección del otro índice si ya existía para estos mismos chunks.
    ruta_cfg = args.salida / CONFIG
    previo = json.loads(ruta_cfg.read_text(encoding="utf-8")) if ruta_cfg.exists() else {}
    if previo.get("sha256_chunks") != sha_chunks or previo.get("n_chunks") != n:
        previo = {}
    cfg = {
        "creado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "chunks": str(args.chunks).replace("\\", "/"),
        "sha256_chunks": sha_chunks,
        "n_chunks": n,
        "n_docs": len(set(chunks["doc_id"])),
        "n_textos_unicos": len(set(chunks["sha1_texto"])),
        "limite": args.limite,
        "campo_indexado": "texto (cabecera + cuerpo vigente)",
        "versiones": _versiones(),
        "lexico": previo.get("lexico"),
        "denso": previo.get("denso"),
    }
    if args.solo != "denso":
        cfg["lexico"] = construir_lexico(chunks, args.salida, args.stem)
    if args.solo != "lexico":
        import torch
        batch = args.batch or (128 if (args.device or ("cuda" if torch.cuda.is_available()
                                                       else "cpu")).startswith("cuda") else 8)
        cfg["denso"] = construir_denso(chunks, args.salida, batch, args.device, args.modelo,
                                       args.revision or None)
    ruta_cfg.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("n_chunks %d | índices en %s | config %s", n, args.salida, ruta_cfg)


if __name__ == "__main__":
    main()
