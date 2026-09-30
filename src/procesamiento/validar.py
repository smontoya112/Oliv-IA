"""Chequeos automáticos sobre la segmentación. Producen alertas, no detienen el build."""
from __future__ import annotations

import re
from collections import Counter

from src.procesamiento.partir import LIMITE_PALABRAS

# Número de artículos base (sin sufijos A, bis, -1…) verificado contra la fuente.
# Para los demás documentos se usa el máximo encontrado, así que solo se detectan huecos.
N_BASE = {
    "ley_1564_2012": 627,
    "codigo_civil": 2684,
}
_FIN_OK = re.compile(r"(?:[.:;!?)\]”\"»]|\}\})\s*$")
_RESIDUOS = re.compile(r"\*\*|\|\s*\||(?m:^\|)|Ã|Â|\{\{(?![^{}]*\}\})|[\x00-\x08\x0b\x0c\x0e-\x1f]")
# Fragmentos cuyo final sin puntuación es de la fuente y ya se revisó (chunk_id).
LISTA_BLANCA_FIN: set[str] = set()


def validar_articulos(doc_id: str, articulos: list) -> dict:
    bases = [a.num_base for a in articulos if a.num_base is not None]
    esperado = N_BASE.get(doc_id) or (max(bases) if bases else 0)
    faltan = sorted(set(range(1, esperado + 1)) - set(bases))
    conteo = Counter(a.num for a in articulos)
    return {
        "n_articulos": len(articulos),
        "n_base_esperado": esperado,
        "faltan_base": faltan,
        "con_sufijo": [a.num for a in articulos if a.sufijo],
        "transitorios": [a.num for a in articulos if a.num.startswith("T")],
        "duplicados": sorted(n for n, c in conteo.items() if c > 1),
        "vacios": [a.num for a in articulos if len(" ".join(b.texto for b in a.bloques)) < 15],
    }


def validar_chunks(chunks: list[dict]) -> dict:
    sobre_limite = [c["chunk_id"] for c in chunks if c["num_palabras"] > LIMITE_PALABRAS]
    sin_fin = [c["chunk_id"] for c in chunks
               if not _FIN_OK.search(c["texto"]) and c["chunk_id"] not in LISTA_BLANCA_FIN]
    residuos = [c["chunk_id"] for c in chunks if _RESIDUOS.search(c["texto"])]
    cortos = [c["chunk_id"] for c in chunks if c["num_palabras_cuerpo"] < 10]
    hashes = Counter(c["sha1_cuerpo"] for c in chunks)
    duplicados = sorted({c["chunk_id"] for c in chunks if hashes[c["sha1_cuerpo"]] > 1})
    return {
        "n_chunks": len(chunks),
        "sobre_limite": sobre_limite,
        "forzados": [c["chunk_id"] for c in chunks if c["corte_forzado"]],
        "alerta_sin_fin_de_oracion": sin_fin,
        "alerta_residuos": residuos,
        "alerta_cuerpo_corto": cortos,
        "duplicados_exactos": duplicados,
    }
