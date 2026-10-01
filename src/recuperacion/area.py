"""Paso 6.3: filtro por área con vuelta al corpus general.

El ítem trae "Derecho constitucional"; los chunks traen areas=["constitucional"]. Se
recuperan muchos candidatos sin filtrar (k_area) y después se conservan los del área; si
quedan muy pocos, el área estaba mal o la pregunta cruza áreas y se usa todo el corpus.
"""
from __future__ import annotations

from src.descarga.seed_a_fuentes import _areas

from .catalogo import Catalogo


def areas_item(item: dict) -> frozenset[str]:
    return frozenset(_areas([item.get("area") or ""]))


def filtrar(ranking: list[tuple[int, float]], cat: Catalogo, areas: frozenset[str],
            min_en_area: int, modo: str = "filtro") -> tuple[list[tuple[int, float]], bool]:
    """(ranking filtrado, hubo_fallback). Con modo 'ninguno' o área desconocida no filtra."""
    if modo == "ninguno" or not areas:
        return ranking, False
    dentro = [(i, s) for i, s in ranking if cat.transversal[i] or cat.areas[i] & areas]
    if len(dentro) < min_en_area:
        return ranking, True
    return dentro, False
