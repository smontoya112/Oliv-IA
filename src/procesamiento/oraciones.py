"""División en oraciones para texto jurídico colombiano.

No corta dentro de notas {{…}}, tras abreviaturas (art., num., M.P., C.C.…), en
ordinales ("1o."), en números con punto de miles ni tras un numeral al inicio ("1. ").
"""
from __future__ import annotations

import re

_ABREVIATURAS = {
    "art", "arts", "num", "nums", "inc", "incs", "lit", "lits", "par", "no", "nro", "núm",
    "dr", "dra", "drs", "sr", "sra", "mp", "p", "pp", "pág", "págs", "cfr", "vid", "ss",
    "ibíd", "ibid", "op", "cit", "etc", "ltda", "cía", "cia", "s.a", "d.c", "c.p", "c.c",
    "c.co", "c.p.p", "c.s.t", "e.t", "m.p", "ord", "dto", "dcto", "res", "exp", "rad",
    "gral", "admón", "lib", "tít", "cap", "sent", "aprox", "ej", "fl", "fls", "vol",
}
_CANDIDATO = re.compile(r"[.!?;](?:[”\")\]]*)\s+(?=\{\{|[\"“(¿¡]?[A-ZÁÉÍÓÚÑ0-9])")


def _protegidos(texto: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in re.finditer(r"\{\{.*?\}\}|~~.*?~~", texto, re.S)]


def _es_abreviatura(texto: str, pos_punto: int) -> bool:
    previo = texto[:pos_punto]
    m = re.search(r"([\wÁÉÍÓÚÑáéíóúñ.]+)$", previo)
    if not m:
        return False
    palabra = m.group(1).lower().strip(".")
    if palabra in _ABREVIATURAS or re.fullmatch(r"[a-záéíóúñ]", palabra):
        return True
    if re.fullmatch(r"(?:[a-záéíóúñ]\.)+[a-záéíóúñ]?", palabra):      # siglas c.g.p
        return True
    if re.fullmatch(r"\d+[oº°]?", palabra) and re.fullmatch(r"\s*\d+[oº°]?", previo[-4:] or ""):
        return True                                                    # "1o." "2."
    return False


def dividir(texto: str) -> list[tuple[int, int]]:
    """Spans (inicio, fin) de cada oración dentro de `texto`."""
    protegidos = _protegidos(texto)
    cortes = []
    for m in _CANDIDATO.finditer(texto):
        p = m.start()
        if any(a <= p < b for a, b in protegidos):
            continue
        if texto[p] == "." and _es_abreviatura(texto, p):
            continue
        # "ARTÍCULO 17. COMPETENCIA…": el punto tras el número no cierra oración.
        if texto[p] == "." and re.search(r"(?i)\bart[íi]culo\s+\S+$", texto[:p]):
            continue
        cortes.append(m.end())
    spans, ini = [], 0
    for c in cortes:
        spans.append((ini, c))
        ini = c
    if ini < len(texto):
        spans.append((ini, len(texto)))
    return [(a, b) for a, b in ((a, a + len(texto[a:b].rstrip())) for a, b in spans) if b > a]
