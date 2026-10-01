"""Paso 5.2: índice denso exacto en FAISS (IndexFlatIP sobre vectores normalizados = coseno).

La fila i de chunks.parquet es el id i del índice. Los textos repetidos (mismo sha1_texto)
se codifican una sola vez y su vector se copia a todas sus filas.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import faiss
import numpy as np

INDICE = "faiss.index"
EMBEDDINGS = "embeddings.npy"
CHUNK_IDS = "chunk_ids.json"


def vectores_unicos(textos: list[str], sha1: list[str],
                    codificar: Callable[[list[str]], np.ndarray]) -> tuple[np.ndarray, int]:
    """Codifica cada texto distinto una vez. Devuelve (matriz por fila, n de textos únicos)."""
    primera: dict[str, int] = {}
    for i, h in enumerate(sha1):
        primera.setdefault(h, i)
    unicos = list(primera.values())
    vec_unicos = codificar([textos[i] for i in unicos])
    pos = {h: k for k, h in enumerate(primera)}
    return vec_unicos[[pos[h] for h in sha1]], len(unicos)


def construir(embeddings: np.ndarray) -> faiss.Index:
    indice = faiss.IndexFlatIP(embeddings.shape[1])
    indice.add(np.ascontiguousarray(embeddings, dtype=np.float32))
    return indice


def guardar(dir_: Path, indice: faiss.Index, embeddings: np.ndarray) -> None:
    dir_.mkdir(parents=True, exist_ok=True)
    faiss.write_index(indice, str(dir_ / INDICE))
    np.save(dir_ / EMBEDDINGS, embeddings.astype(np.float16))


def guardar_orden(dir_: Path, chunk_ids: list[str], sha_chunks: str) -> None:
    """chunk_ids.json: fila i del parquet = id i de FAISS y de BM25."""
    dir_.mkdir(parents=True, exist_ok=True)
    (dir_ / CHUNK_IDS).write_text(json.dumps({"sha256_chunks": sha_chunks, "chunk_ids": chunk_ids},
                                             ensure_ascii=False), encoding="utf-8")


def verificar_orden(dir_: Path, chunk_ids: list[str]) -> None:
    """Falla si los índices se construyeron sobre otro chunks.parquet (re-chunking sin reindexar)."""
    guardado = json.loads((dir_ / CHUNK_IDS).read_text(encoding="utf-8"))["chunk_ids"]
    if guardado != chunk_ids:
        raise RuntimeError(f"{dir_}: el índice no corresponde a este chunks.parquet "
                           f"({len(guardado)} ids guardados vs {len(chunk_ids)} filas). "
                           "Vuelvan a correr python -m src.indice.build.")


def cargar(dir_: Path, chunk_ids: list[str] | None = None) -> faiss.Index:
    if chunk_ids is not None:
        verificar_orden(dir_, chunk_ids)
    return faiss.read_index(str(dir_ / INDICE))


def buscar(indice: faiss.Index, consultas: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
    """(scores, ids) de forma (n_consultas, k)."""
    return indice.search(np.ascontiguousarray(consultas, dtype=np.float32), k)
