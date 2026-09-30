"""Notas de vigencia {{…}} → campos notas, modificado_por, vigente, vigencia_parcial.

Versión inicial: se basa solo en las notas editoriales del Senado. Un artículo es no
vigente cuando una nota lo declara derogado o inexequible en su totalidad.
"""
from __future__ import annotations

import re

import citations

_NOTA = re.compile(r"\{\{(.*?)\}\}", re.S)
_TOTAL = re.compile(r"^\s*(?:Art[íi]culo|ART[ÍI]CULO)\s+(?:derogado|INEXEQUIBLE|declarado\s+"
                    r"INEXEQUIBLE|subrogado)", re.I)
_PARCIAL = re.compile(r"derogad|inexequible|tachado", re.I)
_MODIFICA = re.compile(r"(?:modificad|adicionad|corregid|subrogad|sustituid|derogad)[oa]s?\s+"
                       r"(?:t[áa]citamente\s+)?por\s+(?:el|los)\s+art[íi]culos?", re.I)


def notas(texto: str) -> list[str]:
    return [" ".join(n.split()) for n in _NOTA.findall(texto)]


def analizar(texto: str) -> dict:
    ns = notas(texto)
    modificado_por: set[str] = set()
    for n in ns:
        if _MODIFICA.search(n):
            for c in citations.extract(n):
                modificado_por.add("_".join(str(p) for p in c[:3] if p))
    no_vigente = any(_TOTAL.search(n) for n in ns)
    return {
        "notas": ns,
        "modificado_por": sorted(modificado_por),
        "vigente": not no_vigente,
        "vigencia_parcial": (not no_vigente) and ("~~" in texto or any(_PARCIAL.search(n) for n in ns)),
    }
