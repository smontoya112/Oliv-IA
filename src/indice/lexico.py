"""Paso 5.3: índice léxico BM25 (bm25s) con un tokenizador propio para texto jurídico.

El mismo `tokenizar` se usa para los chunks y para las consultas (fase 6). Conserva los
números (artículos, leyes, años) y une las referencias a sentencias en un solo token
(C-355 -> c355, SL3385-2022 -> sl3385), además del número suelto.
"""
from __future__ import annotations

import re
from pathlib import Path

import bm25s
import numpy as np

import citations

DIR_BM25 = "bm25"
K1, B = 1.2, 0.75

# Lista corta a propósito: no incluye "ley", "art", "decreto", "no", "sin" ni "salvo".
STOPWORDS = frozenset("""
a al ante bajo con contra de del desde durante e el en entre hacia hasta la las le les lo los
mediante o os para por que se segun sobre su sus tras u un una unas unos y ya este esta estos
estas ese esa esos esas aquel aquella cual cuales como cuando donde quien quienes cuyo cuya
es son sera seran ser fue han ha sido haber hay mas muy tambien otro otra otros otras dicho
dicha dichos dichas mismo misma
""".split())

_SENTENCIA = re.compile(r"\b(su|sl|sc|sp|stc|stl|ac|au|c|t)\s?-\s?(\d{1,5})\b"
                        r"|\b(su|sl|sc|sp|stc|stl)(\d{2,5})\b")
_ORDINAL = re.compile(r"\b(\d+)[oº°]\b")
_TOKEN = re.compile(r"\w+")


def _sentencia(m: re.Match) -> str:
    sala, num = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
    return f" {sala}{int(num)} {int(num)} "


def tokenizar(texto: str, stemmer=None) -> list[str]:
    t = citations.strip_accents(texto or "").lower()
    t = _SENTENCIA.sub(_sentencia, t)
    t = _ORDINAL.sub(r"\1", t)
    toks = [w for w in _TOKEN.findall(t) if w not in STOPWORDS and w != "_"]
    if stemmer is not None:
        toks = stemmer.stemWords(toks)
    return toks


def crear_stemmer(usar: bool):
    if not usar:
        return None
    import Stemmer   # PyStemmer, opcional
    return Stemmer.Stemmer("spanish")


def construir(textos: list[str], stemmer=None) -> bm25s.BM25:
    retriever = bm25s.BM25(k1=K1, b=B)
    retriever.index([tokenizar(t, stemmer) for t in textos], show_progress=False)
    return retriever


def guardar(dir_: Path, retriever: bm25s.BM25) -> None:
    retriever.save(str(dir_ / DIR_BM25))


def cargar(dir_: Path, chunk_ids: list[str] | None = None) -> bm25s.BM25:
    if chunk_ids is not None:
        from src.indice.denso import verificar_orden
        verificar_orden(dir_, chunk_ids)
    return bm25s.BM25.load(str(dir_ / DIR_BM25))


def buscar(retriever: bm25s.BM25, consultas: list[str], k: int,
           stemmer=None) -> tuple[np.ndarray, np.ndarray]:
    """(scores, ids) de forma (n_consultas, k), mismo contrato que denso.buscar."""
    toks = [tokenizar(c, stemmer) or ["_vacio_"] for c in consultas]
    k = min(k, retriever.scores["num_docs"])
    ids, scores = retriever.retrieve(toks, k=k, show_progress=False)
    return scores, ids
