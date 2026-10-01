"""Paso 8.3: los pasajes que respaldan una cita de la respuesta quedan dentro del top 10.

El evaluador solo mira `pasajes_recuperados[:10]` (evaluate.MAX_PASAJES_EVIDENCIA), así que
un pasaje que respalda una cita pero cae en la posición 11 no cuenta. Lógica pura.
"""
from __future__ import annotations

from .citas import MAX_PASAJES, cuerpos


def reordenar(pasajes: list[dict], citados: set[tuple], insertados: list[dict] = (),
              max_pasajes: int = MAX_PASAJES) -> tuple[list[dict], list[dict]]:
    """(top `max_pasajes`, insertados que sí entraron).

    Orden: 1) pasajes que respaldan algún cuerpo citado (en su orden original, es decir, por
    puntaje); 2) `insertados` (pasajes traídos del catálogo para respaldar una cita), solo si
    su cuerpo no estaba ya cubierto; 3) el resto en su orden original, hasta llenar el cupo.
    Los insertados desplazan a los no citados de menor puntaje."""
    utiles, otros, cubiertos = [], [], set()
    for p in pasajes:
        c = cuerpos(p.get("texto")) & citados
        if c:
            utiles.append(p)
            cubiertos |= c
        else:
            otros.append(p)
    vistos = {p.get("chunk_id") for p in pasajes if p.get("chunk_id")}
    nuevos = []
    for p in insertados:
        c = cuerpos(p.get("texto")) & citados
        if c - cubiertos and p.get("chunk_id") not in vistos:
            nuevos.append(p)
            cubiertos |= c
    utiles = utiles[:max_pasajes]
    nuevos = nuevos[: max_pasajes - len(utiles)]
    final = utiles + nuevos
    return final + otros[: max_pasajes - len(final)], nuevos
