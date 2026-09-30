"""Segmentación simple de sentencias.

Solo se distinguen tres secciones con marcas robustas entre sentencias:
  cuerpo       todo lo anterior a la decisión (antecedentes, consideraciones…)
  resuelve     desde "DECISIÓN" / "RESUELVE"
  salvamentos  desde el primer "SALVAMENTO / ACLARACIÓN DE VOTO" posterior a la decisión
Los salvamentos no son la ratio de la Corte; la recuperación puede penalizarlos.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from src.procesamiento.normas import Bloque, bloques

_DECISION = re.compile(r"^(?:[IVXL]+\.\s*)?(?:DECISI[ÓO]N|R\s?E\s?S\s?U\s?E\s?L\s?V\s?E)\s*[.:]?$")
_SALVAMENTO = re.compile(r"^(?:CON\s+)?(?:SALVAMENTO|ACLARACI[ÓO]N)\s+(?:PARCIAL\s+)?DE\s+VOTO",
                         re.I)
_PONENTE = re.compile(r"^Magistrad[oa]s?\s+Ponentes?\s*:?\s*(?P<resto>.*)$", re.I)
_DOCTOR = re.compile(r"^Dr[a]?\.\s+(?P<nombre>.+)$")
_FECHA = re.compile(r"^Bogot[áa],?\s+D\.\s?C\.,?\s+(?P<fecha>.+?)\.?$", re.S)


@dataclass
class Seccion:
    nombre: str
    bloques: list[Bloque]


def metadatos(texto: str) -> dict:
    bls = bloques(texto)
    ponentes, fecha = [], None
    for i, b in enumerate(bls[:400]):
        if m := _PONENTE.match(b.texto):
            if m.group("resto").strip():
                ponentes.append(m.group("resto").strip())
            for sig in bls[i + 1:i + 5]:
                if d := _DOCTOR.match(sig.texto):
                    ponentes.append(" ".join(d.group("nombre").split()).title())
                else:
                    break
        if fecha is None and (m := _FECHA.match(b.texto)):
            fecha = " ".join(m.group("fecha").split())
    return {"magistrado_ponente": ponentes, "fecha": fecha}


def secciones(texto: str) -> list[Seccion]:
    bls = bloques(texto)
    i_dec = next((i for i, b in enumerate(bls) if _DECISION.match(b.texto)), None)
    i_salv = None
    if i_dec is not None:
        i_salv = next((i for i, b in enumerate(bls[i_dec:], start=i_dec)
                       if _SALVAMENTO.match(b.texto)), None)
    cortes = [("cuerpo", 0)]
    if i_dec is not None:
        cortes.append(("resuelve", i_dec))
    if i_salv is not None:
        cortes.append(("salvamentos", i_salv))
    salida = []
    for k, (nombre, ini) in enumerate(cortes):
        fin = cortes[k + 1][1] if k + 1 < len(cortes) else len(bls)
        if bls[ini:fin]:
            salida.append(Seccion(nombre, bls[ini:fin]))
    return salida
