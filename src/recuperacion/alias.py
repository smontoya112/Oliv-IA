"""Paso 6.2: expansión de consultas con el diccionario de alias (data/alias_normas.yaml).

Si la pregunta nombra "CGP" o "C.S.T.", el texto de los artículos dice "Código General del
Proceso" o "Código Sustantivo del Trabajo": se agregan esos nombres (y "Ley 1564 de 2012") a
la consulta LÉXICA. La consulta densa no se toca: el encoder ya entiende las siglas.
"""
from __future__ import annotations

import citations
import normalizacion


def _entradas() -> dict:
    d = normalizacion._ALIAS_DICT
    return {**d.get("codigos", {}), **d.get("extensiones", {})}


def terminos(texto: str) -> list[str]:
    """Nombres completos de las normas que el texto cita por sigla o alias."""
    entradas = _entradas()
    extra, visto = [], citations.norm(texto)
    cuerpos = {c[0] for c in citations.extract(texto)} | {
        c[0] for c in normalizacion._extract_extensiones(texto)}
    for slug in sorted(cuerpos):
        e = entradas.get(slug)
        if not e:
            continue
        candidatos = []
        if e.get("alias"):
            candidatos.append(max(e["alias"], key=len))          # el nombre más largo
        if e.get("tipo") and e.get("numero") and e.get("anio"):
            candidatos.append(f"{e['tipo']} {e['numero']} de {e['anio']}")
        for t in candidatos:
            if len(t) > 5 and citations.norm(t) not in visto and t not in extra:
                extra.append(t)
    return extra


def expandir(texto: str) -> str:
    extra = terminos(texto)
    return f"{texto}\n{' '.join(extra)}" if extra else texto
