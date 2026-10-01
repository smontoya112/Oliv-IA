"""Paso 6.7: armado del contexto del prompt, [P1]…[P8] entre 3.000 y 5.000 tokens.

Cabe en el prompt los mejores pasajes en el orden en que llegan (ya reordenados por el
reranker), con un máximo de 8 y sin pasar del presupuesto. Los pasajes 9 y 10 no entran al
prompt pero SÍ viajan en `pasajes_recuperados` de la entrega (el evaluador mira los 10
primeros, paso 8.3). Sin dependencias pesadas: lo usa src.generacion.prompts.
"""
from __future__ import annotations

MIN_TOKENS, MAX_TOKENS, MAX_PASAJES = 3000, 5000, 8
_CHARS_POR_TOKEN = 3.5       # estimación cuando no hay tokenizador del decoder


def estimar_tokens(texto: str) -> int:
    return int(len(texto) / _CHARS_POR_TOKEN) + 1


def _etiqueta(p: dict) -> str:
    return f" (evidencia sobre la opción {p['opcion']})" if p.get("opcion") else ""


def armar(pasajes: list[dict], max_tokens: int = MAX_TOKENS, max_pasajes: int = MAX_PASAJES,
          contar=None) -> tuple[str, list[dict]]:
    """(texto "[P1] doc_id ...", pasajes incluidos). Siempre incluye el primero, truncado si
    él solo excede el presupuesto. `contar` es el contador de tokens del decoder."""
    contar = contar or estimar_tokens
    bloques, usados, gastado = [], [], 0
    for i, p in enumerate(pasajes[:max_pasajes], start=1):
        bloque = f"[P{i}] {p['doc_id']}{_etiqueta(p)}\n{p['texto'].strip()}"
        costo = contar(bloque)
        if usados and gastado + costo > max_tokens:
            break
        if not usados and costo > max_tokens:
            bloque = bloque[: int(max_tokens * _CHARS_POR_TOKEN)]
            costo = max_tokens
        bloques.append(bloque)
        usados.append(p)
        gastado += costo
    return "\n\n".join(bloques), usados


def tokens_usados(texto: str, contar=None) -> int:
    return (contar or estimar_tokens)(texto)
