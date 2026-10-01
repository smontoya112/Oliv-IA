"""Catálogo de chunks: columnas en memoria + el puente entre los ids de chunk y los ids
canónicos de la fase 4.

`chunks.norma_id_canonico` sale de src.procesamiento.encabezado.norma_id y usa la tupla del
evaluador (codigo_general_proceso#art_391, jurisprudencia_C-355_2006). El estándar de la
fase 4 (scripts/normalizacion.to_canonical_id) es otro (ley_1564_2012#art_391,
sentencia_C-355_2006). `a_canonico` convierte el primero al segundo para poder comparar con
`normalizacion.extract_canonical(pregunta)`.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import normalizacion  # scripts/normalizacion.py (src.recuperacion agrega scripts/ al path)

from .config import TRANSVERSALES

COLUMNAS = ["chunk_id", "doc_id", "norma_id_canonico", "areas", "texto", "inicio", "fin",
            "sha1_texto"]
_TIPOS = "ley|decreto|acto_legislativo|decreto_ley|resolucion|circular|acuerdo"
_RE_NORMA = re.compile(rf"^({_TIPOS})_(\d+)_(\d{{4}})$")
_RE_JURIS = re.compile(r"^jurisprudencia_([A-Za-z]+-\d+)_(\d{4})$")


def a_canonico(norma_id: str) -> str:
    """norma_id de un chunk -> id canónico de la fase 4 (conserva el sufijo #art_N)."""
    base, _, art = (norma_id or "").partition("#art_")
    if m := _RE_JURIS.match(base):
        tupla = ("jurisprudencia", m.group(1), m.group(2), art or None)
    elif m := _RE_NORMA.match(base):
        tupla = (m.group(1), m.group(2), m.group(3), art or None)
    else:                                   # slug de código (codigo_civil), constitución, doc_id
        tupla = (base, None, None, art or None)
    return normalizacion.to_canonical_id(tupla)


@dataclass
class Catalogo:
    cols: dict[str, list]
    canon: list[str] = field(default_factory=list)            # id canónico por fila
    por_canon: dict[str, list[int]] = field(default_factory=lambda: defaultdict(list))
    areas: list[frozenset] = field(default_factory=list)
    transversal: list[bool] = field(default_factory=list)

    @classmethod
    def desde_columnas(cls, cols: dict[str, list]) -> "Catalogo":
        cat = cls(cols=cols)
        for i, nid in enumerate(cols["norma_id_canonico"]):
            c = a_canonico(nid)
            cat.canon.append(c)
            cat.por_canon[c].append(i)
            if "#" in c:                        # también por norma completa
                cat.por_canon[c.split("#")[0]].append(i)
            cat.areas.append(frozenset(cols["areas"][i] or ()))
            cat.transversal.append(c.split("#")[0] in TRANSVERSALES)
        return cat

    def __len__(self) -> int:
        return len(self.cols["chunk_id"])

    def base(self, i: int) -> str:
        return self.canon[i].split("#")[0]

    def pasaje(self, i: int, score: float | None = None, **extra) -> dict:
        c = self.cols
        p = {"doc_id": c["doc_id"][i], "inicio": c["inicio"][i], "fin": c["fin"][i],
             "texto": c["texto"][i], "chunk_id": c["chunk_id"][i], "norma_id": self.canon[i]}
        if score is not None:
            p["score"] = round(float(score), 5)
        p.update({k: v for k, v in extra.items() if v is not None})
        return p


def cargar(dir_indice: Path = Path("data/index")) -> Catalogo:
    """Lee chunks.parquet (la misma ruta y recorte con que se construyó el índice)."""
    import pyarrow.parquet as pq
    cfg = json.loads((dir_indice / "index_config.json").read_text(encoding="utf-8"))
    tabla = pq.read_table(cfg["chunks"], columns=COLUMNAS)
    if cfg.get("limite"):
        tabla = tabla.slice(0, cfg["limite"])
    return Catalogo.desde_columnas(tabla.to_pydict())
