"""Preguntas cerradas: análisis opción por opción y decisión determinista.

El modelo escribe primero un veredicto ("correcta"/"incorrecta") y una razón por CADA opción, y
solo después la justificación y la letra (src.generacion.esquemas). Así la letra sale de evaluar
todas las opciones y no al revés. Luego `resolver` decide la letra final con reglas fijas:

- Opciones compuestas ("Todas las anteriores", "Ninguna de las anteriores", "(a) y (b)") se
  deciden a partir de los veredictos de las opciones simples, no del criterio del modelo.
- Si la letra que eligió el modelo contradice sus propios veredictos (ítem 51 de sample_50:
  la justificación respaldaba C y la letra fue B), gana el veredicto.
"""
from __future__ import annotations

import re

_TODAS = re.compile(r"\btodas\s+las\s+(anteriores|opciones|afirmaciones)|\btodas\s+son\s+correctas", re.I)
_NINGUNA = re.compile(r"\bninguna\s+de\s+las\s+(anteriores|opciones|afirmaciones)|\bninguna\s+es\s+correcta", re.I)
# "(a) y (b)", "A y C", "a, b y c son correctas", "las opciones A y B"
_COMBINACION = re.compile(r"^\W*(?:las\s+opciones\s+)?\(?([a-d])\)?(?:\s*,\s*\(?([a-d])\)?)*\s+(?:y|e)\s+"
                          r"\(?([a-d])\)?(?:\s+son\s+correctas)?\W*$", re.I)
_LETRA = re.compile(r"\(?\b([a-d])\b\)?", re.I)


def clasificar(opciones: dict) -> dict[str, dict]:
    """{letra: {"tipo": "simple"|"todas"|"ninguna"|"combinacion", "refs": [letras]}}.
    Una combinación que se nombra a sí misma ("A. (a) y (b)") es ambigua: queda como simple."""
    res = {}
    for letra, texto in opciones.items():
        t = " ".join(str(texto or "").split())
        if _TODAS.search(t):
            res[letra] = {"tipo": "todas", "refs": []}
        elif _NINGUNA.search(t):
            res[letra] = {"tipo": "ninguna", "refs": []}
        elif _COMBINACION.match(t):
            refs = sorted({m.upper() for m in _LETRA.findall(t)})
            ok = letra not in refs and all(r in opciones for r in refs)
            res[letra] = {"tipo": "combinacion", "refs": refs} if ok else {"tipo": "simple", "refs": []}
        else:
            res[letra] = {"tipo": "simple", "refs": []}
    return res


def nota_opcion(tipo: dict) -> str:
    """Aclaración para el prompt de una opción compuesta ("" si es simple)."""
    if tipo["tipo"] == "todas":
        return " [opción compuesta: solo es correcta si TODAS las demás opciones lo son]"
    if tipo["tipo"] == "ninguna":
        return " [opción compuesta: solo es correcta si NINGUNA de las demás opciones lo es]"
    if tipo["tipo"] == "combinacion":
        return (f" [opción compuesta: equivale a que {' y '.join(tipo['refs'])} sean correctas "
                "a la vez]")
    return ""


def veredictos(analisis: dict, letras) -> dict[str, bool | None]:
    """{letra: True (correcta) | False (incorrecta) | None (sin veredicto legible)}."""
    res = {}
    for l in letras:
        v = analisis.get(l) if isinstance(analisis, dict) else None
        v = (v.get("veredicto") if isinstance(v, dict) else v) or ""
        v = str(v).strip().lower()
        res[l] = True if v.startswith("correct") else False if v.startswith("incorrect") else None
    return res


def resolver(opciones: dict, analisis: dict, letra_modelo: str | None) -> tuple[str | None, str]:
    """(letra final, regla aplicada). Ver el docstring del módulo."""
    tipos = clasificar(opciones)
    ver = veredictos(analisis, sorted(opciones))
    simples = [l for l in sorted(opciones) if tipos[l]["tipo"] == "simple"]
    ciertas = {l for l in simples if ver[l]}
    juzgadas = all(ver[l] is not None for l in simples)

    compuestas = []
    for l in sorted(opciones):
        t = tipos[l]
        if t["tipo"] == "todas" and juzgadas and len(simples) >= 2:
            if ciertas == set(simples):
                compuestas.append(l)
        elif t["tipo"] == "ninguna" and juzgadas and simples:
            if not ciertas:
                compuestas.append(l)
        elif t["tipo"] == "combinacion" and all(ver[r] is not None for r in t["refs"]):
            if set(t["refs"]) <= ciertas:
                compuestas.append(l)

    if len(compuestas) == 1:                    # "todas"/"ninguna"/"a y b" confirmada por los veredictos
        return compuestas[0], f"compuesta_{tipos[compuestas[0]]['tipo']}"
    candidatas = compuestas or sorted(ciertas)
    if not candidatas:                          # ningún veredicto "correcta": no hay con qué corregir
        return letra_modelo, "modelo_sin_veredictos"
    if letra_modelo in candidatas:              # el modelo es coherente con sus veredictos
        return letra_modelo, "modelo"
    if len(candidatas) == 1:                    # la letra contradice el único veredicto "correcta"
        return candidatas[0], "veredicto_unico"
    return candidatas[0], "varias_correctas"
