"""Paso 6.1: inclusión directa de las normas que el ENUNCIADO nombra.

Solo se mira el enunciado, nunca las opciones: en una pregunta cerrada los distractores
suelen ser normas inventadas o ajenas ("Ley 1564 de 2002"). Las opciones se atienden en
src.recuperacion.cerradas como evidencia etiquetada.
"""
from __future__ import annotations

import normalizacion

from .catalogo import Catalogo


def normas_nombradas(enunciado: str) -> list[str]:
    """Ids canónicos (fase 4) que cita el enunciado: ley_1564_2012#art_391, decreto_2591_1991..."""
    return sorted(normalizacion.extract_canonical(enunciado or ""))


def directos(enunciado: str, cat: Catalogo, ranking: list[tuple[int, float]],
             n_max: int = 4, max_por_id: int = 2) -> tuple[list[int], dict]:
    """Filas a promover y un resumen {nombradas, en_corpus, sin_corpus}.

    - Cita con artículo y existe ese artículo: sus chunks (las primeras partes).
    - Cita sin artículo, o artículo que no está: los chunks mejor rankeados de esa norma que
      ya aparecen en `ranking` (no se promueve su encabezado a ciegas).
    """
    ids = normas_nombradas(enunciado)
    filas: list[int] = []
    en_corpus, sin_corpus = [], []
    for ident in ids:
        base = ident.split("#")[0]
        if base not in cat.por_canon:
            sin_corpus.append(ident)
            continue
        en_corpus.append(ident)
        if "#" in ident and ident in cat.por_canon:
            elegidas = cat.por_canon[ident][:max_por_id]
        else:
            elegidas = [i for i, _ in ranking if cat.base(i) == base][:max_por_id]
        filas += [i for i in elegidas if i not in filas]
    return filas[:n_max], {"nombradas": ids, "en_corpus": en_corpus, "sin_corpus": sin_corpus}
