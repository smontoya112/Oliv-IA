"""JSON schemas para la salida guiada de vLLM (uno por formato).

El orden de las propiedades importa: el modelo escribe en ese orden, así que el
razonamiento (justificación/análisis) va ANTES de la decisión (letra elegida).
"""
from __future__ import annotations

LETRAS = ("A", "B", "C", "D")

_TEXTO = {"type": "string", "minLength": 1}

ESQUEMAS: dict[str, dict] = {
    "multiple_choice": {
        "type": "object",
        "properties": {
            "justificacion": _TEXTO,
            "respuesta_correcta": {"enum": list(LETRAS)},
            "descarte_opciones": {
                "type": "object",
                "properties": {l: _TEXTO for l in LETRAS},
                "additionalProperties": False,
            },
        },
        "required": ["justificacion", "respuesta_correcta", "descarte_opciones"],
        "additionalProperties": False,
    },
    "semi_open": {
        "type": "object",
        "properties": {
            "respuesta": _TEXTO,
            "palabras_clave": {"type": "array", "items": _TEXTO, "minItems": 2, "maxItems": 8},
            "referencia_legal": _TEXTO,
        },
        "required": ["respuesta", "palabras_clave", "referencia_legal"],
        "additionalProperties": False,
    },
    "open_ended": {
        "type": "object",
        "properties": {
            "marco_normativo": _TEXTO,
            "analisis": _TEXTO,
            "jurisprudencia": _TEXTO,
            "conclusion": _TEXTO,
        },
        "required": ["marco_normativo", "analisis", "jurisprudencia", "conclusion"],
        "additionalProperties": False,
    },
}


def esquema(formato: str) -> dict:
    try:
        return ESQUEMAS[formato]
    except KeyError:
        raise ValueError(f"formato desconocido: {formato!r}") from None
