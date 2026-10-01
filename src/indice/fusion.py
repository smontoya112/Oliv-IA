"""Colapso de textos repetidos y fusión RRF, compartidos por la evaluación (fase 5) y la
recuperación (fase 6). Sin dependencias pesadas (solo numpy en los tipos)."""
from __future__ import annotations

from collections import defaultdict

import numpy as np

RRF_K = 60


def colapsar(scores: np.ndarray, ids: np.ndarray, sha1: list[str], k: int,
             descartar_cero: bool) -> list[tuple[int, float]]:
    """Ranking de filas sin textos repetidos (se queda la primera aparición)."""
    vistos, salida = set(), []
    for s, i in zip(scores, ids):
        if i < 0 or (descartar_cero and s <= 0) or sha1[i] in vistos:
            continue
        vistos.add(sha1[i])
        salida.append((int(i), float(s)))
        if len(salida) == k:
            break
    return salida


def rrf(*rankings: list[tuple[int, float]], k: int) -> list[tuple[int, float]]:
    acum: dict[int, float] = defaultdict(float)
    for ranking in rankings:
        for pos, (i, _) in enumerate(ranking, start=1):
            acum[i] += 1.0 / (RRF_K + pos)
    return sorted(acum.items(), key=lambda x: -x[1])[:k]
