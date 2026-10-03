"""JSON schemas para la salida guiada (gramática de llama.cpp) (uno por formato).

El orden de las propiedades importa: el modelo escribe en ese orden, así que el
razonamiento (justificación/análisis) va ANTES de la decisión (letra elegida).
"""
from __future__ import annotations

LETRAS = ("A", "B", "C", "D")

_TEXTO = {"type": "string", "minLength": 1}
_VEREDICTO = {
    "type": "object",
    "properties": {"veredicto": {"enum": ["correcta", "incorrecta"]}, "razon": _TEXTO},
    "required": ["veredicto", "razon"],
    "additionalProperties": False,
}


def esquema_cerrada(letras=LETRAS) -> dict:
    """Cerradas: primero un veredicto y una razón por CADA opción, luego la justificación y por
    último la letra (src.generacion.cerradas). `descarte_opciones`, que pide el formato de
    entrega, se arma en el postproceso con las razones de las opciones no elegidas."""
    letras = list(letras)
    return {
        "type": "object",
        "properties": {
            "analisis_opciones": {
                "type": "object",
                "properties": {l: _VEREDICTO for l in letras},
                "required": letras,
                "additionalProperties": False,
            },
            "justificacion": _TEXTO,
            "respuesta_correcta": {"enum": letras},
        },
        "required": ["analisis_opciones", "justificacion", "respuesta_correcta"],
        "additionalProperties": False,
    }


def esquema_justificacion(letras, elegida: str) -> dict:
    """Cerradas con la letra ya decidida: solo hay que justificarla y descartar las demás."""
    otras = [l for l in letras if l != elegida]
    return {
        "type": "object",
        "properties": {
            "justificacion": _TEXTO,
            "descarte_opciones": {"type": "object", "properties": {l: _TEXTO for l in otras},
                                  "required": otras, "additionalProperties": False},
        },
        "required": ["justificacion", "descarte_opciones"],
        "additionalProperties": False,
    }


ESQUEMAS: dict[str, dict] = {
    "multiple_choice": esquema_cerrada(),
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


def esquema_item(item: dict) -> dict:
    """Esquema de un ítem concreto: en las cerradas, solo con las letras que trae."""
    if item["formato"] == "multiple_choice":
        letras = sorted(item.get("opciones") or LETRAS)
        return ESQUEMAS["multiple_choice"] if tuple(letras) == LETRAS else esquema_cerrada(letras)
    return esquema(item["formato"])
