"""Paso 6.6: consultas para preguntas cerradas (enunciado + opciones).

Una consulta base (enunciado y las cuatro opciones, como en la fase 5) y una por opción
(enunciado + esa opción) para traer evidencia que sirva para respaldar o descartar cada una.
"""
from __future__ import annotations


def consulta_base(item: dict) -> str:
    texto = item.get("pregunta") or ""
    if item.get("formato") == "multiple_choice" and item.get("opciones"):
        texto += "\n" + "\n".join(f"{k}) {v}" for k, v in item["opciones"].items())
    return texto


def consultas_por_opcion(item: dict) -> list[tuple[str, str]]:
    """[(letra, "enunciado + opción")]; vacío si el ítem no es de opción múltiple."""
    if item.get("formato") != "multiple_choice":
        return []
    return [(k, f"{item.get('pregunta') or ''}\n{v}")
            for k, v in sorted((item.get("opciones") or {}).items())]
