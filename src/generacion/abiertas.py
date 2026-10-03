"""Preguntas abiertas (casos jurídicos): plantilla por tipo de caso, consultas de búsqueda deducidas del caso
y una segunda pasada que quita lo que los pasajes no respaldan.

Por qué un trato aparte (diagnóstico sobre `sample_50`, 5 abiertas):
* El caso es un relato largo con una o dos preguntas al final. Buscar con el relato completo trae pasajes
  parecidos al relato (parques, buses, fiducias), no a la norma que lo gobierna (acción popular y Ley 472,
  accidente in itinere y Ley 1562, habeas data y Ley 1581): la recuperación @10 de la norma de referencia es
  de 0,75 en abiertas contra 1,0 en semiabiertas, y el cross-encoder del reranker solo ve 512 tokens: el
  relato se come el espacio del pasaje.
* La respuesta esperada empieza por la conclusión y contesta CADA pregunta del caso; el prompt anterior
  pedía lo mismo para todos los casos y arrastraba relleno ("no hay jurisprudencia").

Las tres piezas se activan por la variable `OLIVIA_ABIERTAS` (lista separada por comas de `plantilla`,
`expansion`, `revision`) o por la clave `abiertas` de config/responder.json; sin ninguna, el camino es el anterior.
Todo es determinista (temperatura 0) y solo usa el enunciado: nunca `legal_basis` ni respuestas de la muestra.
"""
from __future__ import annotations

import json
import os
import re

PIEZAS = ("plantilla", "expansion", "expansion_pura", "revision")
LIMITES_ANALISIS = (7, 200)         # (oraciones, palabras) máximas del campo "analisis" con la plantilla
MAX_TOKENS_CONSULTAS = 260
MAX_TOKENS_REVISION = 1100

_PREGUNTA = re.compile(r"¿[^?¿]+\?")
_ORACION = re.compile(r"(?<=[.!?])\s+")


def activas(cfg: dict | None = None) -> set[str]:
    """Piezas activas: OLIVIA_ABIERTAS manda sobre `cfg["abiertas"]`; "" o "ninguna" las apaga todas."""
    crudo = os.environ.get("OLIVIA_ABIERTAS")
    if crudo is None:
        crudo = ",".join((cfg or {}).get("abiertas") or [])
    return {p.strip() for p in crudo.split(",") if p.strip() in PIEZAS}


# ------------------------------------------------------------------ las preguntas del caso
def preguntas(texto: str) -> list[str]:
    """Las preguntas del caso, en orden. Sin signos de interrogación, la última oración que parezca
    pregunta (qué, cuál, quién, procede…) o, si no, la última oración."""
    texto = " ".join(str(texto or "").split())
    qs = [q.strip() for q in _PREGUNTA.findall(texto)]
    if qs:
        return qs
    oraciones = [o.strip() for o in _ORACION.split(texto) if o.strip()]
    for o in reversed(oraciones):
        if re.search(r"\b(qu[eé]|cu[aá]l(?:es)?|qui[eé]n(?:es)?|c[oó]mo|procede|puede|debe|existe)\b", o, re.I):
            return [o]
    return oraciones[-1:] if oraciones else []


_TIPOS = [
    ("accion", r"qu[eé] (acci[oó]n|recurso|mecanismo|medio|procedimiento|v[ií]a)\b|cu[aá]l (es )?(la |el )?(acci[oó]n|recurso|mecanismo)|procede(n)? (la |el |alg[uú]n )?(acci[oó]n|recurso|mecanismo)"),
    ("responsable", r"qui[eé]n(es)? (responde|debe responder|es responsable|asume|debe asumir|paga)|qu[eé] parte tiene derecho|responsabilidad"),
    ("viabilidad", r"\b(puede|pueden|debe|deben|es posible|est[aá] obligad|tiene derecho|procede)\b"),
]
_AYUDA_TIPO = {
    "accion": ("Indica la acción, recurso o mecanismo que procede, su fundamento legal, quién puede ejercerlo, "
               "ante quién y por qué es el adecuado frente a otros que podrían confundirse con él."),
    "responsable": ("Indica quién responde o a quién corresponde el derecho, por qué título jurídico y con qué "
                    "fundamento normativo, y qué ocurre con las excepciones (fuerza mayor, caso fortuito, etc.)."),
    "viabilidad": ("Responde si se puede o se debe, con la regla que lo permite o lo prohíbe, sus excepciones y "
                   "los requisitos que el caso cumple o incumple."),
    "analisis": ("Identifica el problema jurídico, la regla aplicable y aplícala a los hechos del caso."),
}


def tipo(pregunta_o_texto: str) -> str:
    t = " ".join(str(pregunta_o_texto or "").split())
    for nombre, patron in _TIPOS:
        if re.search(patron, t, re.I):
            return nombre
    return "analisis"


def tipos_del_caso(texto: str) -> list[str]:
    """Tipo de cada pregunta del caso (sin repetir, en orden)."""
    vistos: list[str] = []
    for q in preguntas(texto) or [texto]:
        t = tipo(q)
        if t not in vistos:
            vistos.append(t)
    return vistos


def instrucciones(item: dict) -> str:
    """Bloque de instrucciones v3 para open_ended: contesta cada pregunta del caso, en orden."""
    qs = preguntas(item.get("pregunta"))
    numeradas = " ".join(f"({i}) {q}" for i, q in enumerate(qs, start=1)) if qs else ""
    ayudas = " ".join(_AYUDA_TIPO[t] for t in tipos_del_caso(item.get("pregunta")))
    cabecera = (f"Pregunta abierta: caso jurídico con {len(qs)} pregunta(s) por responder: {numeradas}"
                if qs else "Pregunta abierta: caso jurídico.")
    return (f"{cabecera}\n"
            "Campos del JSON (en total, unas 300 palabras):\n"
            "- \"marco_normativo\": de 1 a 3 oraciones (máximo 70 palabras) con la norma o normas que gobiernan el punto "
            "(nombre completo y artículo) y, si aparece en los pasajes, la sentencia que fija la regla. Incluye la norma "
            "o sentencia que el enunciado mencione.\n"
            "- \"analisis\": de 4 a 7 oraciones (máximo 180 palabras) que contesten cada pregunta del caso en el mismo "
            f"orden. Empieza con la respuesta directa, enuncia la regla y aplícala a los hechos. {ayudas} "
            "No repitas el marco normativo ni agregues relleno.\n"
            "- \"jurisprudencia\": una o dos oraciones con la sentencia de los pasajes que aplica al caso y la regla que "
            "fija. Si ninguna aplica, escribe en una oración el principio jurídico en juego; no escribas que no hay "
            "jurisprudencia.\n"
            "- \"conclusion\": una oración por pregunta del caso (máximo 50 palabras en total), con la respuesta final.")


# ------------------------------------------------------------------ consultas de búsqueda (expansión)
SISTEMA_CONSULTAS = ("Eres un abogado colombiano que prepara la investigación de un caso. No lo resuelves: "
                     "identificas qué hay que buscar. Responde únicamente con un objeto JSON válido.")
_USUARIO_CONSULTAS = (
    "Caso:\n{caso}\n\nIdentifica:\n"
    "- \"problema_juridico\": el problema jurídico central en una o dos oraciones, sin los hechos accesorios.\n"
    "- \"consultas\": de 2 a 4 consultas cortas (máximo 15 palabras cada una) para buscar en un corpus de "
    "legislación y jurisprudencia colombianas: instituciones, acciones, derechos y normas que probablemente "
    "regulan el punto (por ejemplo \"acción popular derechos colectivos Ley 472 de 1998\"). No inventes números "
    "de normas o sentencias que no conozcas con seguridad.")
ESQUEMA_CONSULTAS = {
    "type": "object",
    "properties": {
        "problema_juridico": {"type": "string", "minLength": 1},
        "consultas": {"type": "array", "items": {"type": "string", "minLength": 1}, "minItems": 1, "maxItems": 4},
    },
    "required": ["problema_juridico", "consultas"],
    "additionalProperties": False,
}


def deducir_consultas(item: dict, motor) -> dict | None:
    """{"problema_juridico", "consultas"} deducidos del caso por el decoder; None si falla (se sigue sin expansión)."""
    mensajes = [{"role": "system", "content": SISTEMA_CONSULTAS},
                {"role": "user", "content": _USUARIO_CONSULTAS.format(caso=str(item.get("pregunta") or "").strip())}]
    try:
        crudo = motor.generar_lote([mensajes], [ESQUEMA_CONSULTAS], max_tokens=MAX_TOKENS_CONSULTAS)[0]
        r = json.loads(crudo)
    except Exception:
        return None
    if not isinstance(r, dict) or not r.get("consultas"):
        return None
    return {"problema_juridico": " ".join(str(r.get("problema_juridico") or "").split()),
            "consultas": [" ".join(str(c).split()) for c in r["consultas"] if str(c).strip()][:4]}


def _clave(p: dict) -> tuple:
    return (p.get("doc_id"), p.get("inicio"), p.get("fin"))


def fusionar(base: list[dict], nuevo: list[dict], n: int = 10, k: int = 60) -> list[dict]:
    """RRF de las dos listas FINALES de pasajes (la de siempre y la expandida): un pasaje que está en las
    dos sube; uno que está en una sola conserva su lugar relativo. Así la expansión AÑADE evidencia (la norma
    que el relato ocultaba) sin desplazar la que la recuperación original ya tenía bien. Con la expansión
    "pura" (reemplazar la lista) 4 de 5 abiertas empeoraron en RAGAS aunque 1 mejoró mucho."""
    acum: dict[tuple, float] = {}
    dato: dict[tuple, dict] = {}
    for lista in (base, nuevo):
        for pos, p in enumerate(lista, start=1):
            c = _clave(p)
            acum[c] = acum.get(c, 0.0) + 1.0 / (k + pos)
            dato.setdefault(c, p)
    orden = sorted(acum, key=lambda c: (-acum[c], str(c)))
    return [dato[c] for c in orden][:n]


def recuperar_expandido(item: dict, rec: dict, motor, recuperador, modo: str = "rrf") -> dict:
    """Recuperación de un caso con consultas deducidas. `modo`: "rrf" (fusiona con la lista original, por defecto)
    o "pura" (usa solo la lista expandida). Devuelve `rec` (la original) si algo falla."""
    d = deducir_consultas(item, motor)
    if not d:
        return rec
    qs = " ".join(preguntas(item.get("pregunta")))
    consulta_rerank = " ".join(x for x in (d["problema_juridico"], qs) if x)
    try:
        nuevo = recuperador.recuperar_expandido(item, [d["problema_juridico"], *d["consultas"]], consulta_rerank)
    except Exception:
        return rec
    if not nuevo.get("pasajes"):
        return rec
    if modo == "rrf":
        nuevo["pasajes"] = fusionar(rec.get("pasajes") or [], nuevo["pasajes"])
    nuevo["senales"] = {**(nuevo.get("senales") or {}), "expansion": d, "expansion_modo": modo}
    return nuevo


# ------------------------------------------------------------------ segunda pasada
SISTEMA_REVISION = ("Eres un revisor jurídico colombiano riguroso. Corriges borradores para que digan solo lo que "
                    "los pasajes o el derecho colombiano establecido respaldan. Responde únicamente con un objeto "
                    "JSON válido con los mismos campos del borrador.")


def mensajes_revision(item: dict, borrador: dict, pasajes_texto: str) -> list[dict]:
    usuario = (
        "Revisa el borrador de respuesta a este caso usando los pasajes.\n\n"
        f"=== PASAJES ===\n{pasajes_texto or '(sin pasajes)'}\n\n=== CASO ===\n{str(item.get('pregunta') or '').strip()}\n\n"
        f"=== BORRADOR ===\n{json.dumps(borrador, ensure_ascii=False)}\n\n"
        "Reglas de la revisión:\n"
        "1. Conserva la conclusión y el orden de las preguntas, salvo que los pasajes contradigan algo.\n"
        "2. Elimina o reformula toda afirmación, artículo, norma o sentencia que NO aparezca en los pasajes y de la "
        "que no estés seguro; nunca inventes números de artículos ni de sentencias.\n"
        "3. Si los pasajes traen la regla que falta para contestar una pregunta, incorpórala con su norma y artículo.\n"
        "4. Quita relleno y repeticiones; entre \"analisis\" y \"conclusion\" deja de 250 a 350 palabras.\n"
        "Devuelve el JSON revisado con los campos marco_normativo, analisis, jurisprudencia y conclusion.")
    return [{"role": "system", "content": SISTEMA_REVISION}, {"role": "user", "content": usuario}]


def _palabras(d: dict) -> int:
    return sum(len(str(d.get(k) or "").split()) for k in ("marco_normativo", "analisis", "jurisprudencia", "conclusion"))


def revisar(item: dict, borrador: dict, pasajes_texto: str, motor, esquema: dict) -> dict:
    """Borrador revisado, o el borrador si la revisión falla o encoge la respuesta a menos de la mitad."""
    try:
        crudo = motor.generar_lote(
            [mensajes_revision(item, borrador, pasajes_texto)], [esquema], max_tokens=MAX_TOKENS_REVISION)[0]
        r = json.loads(crudo)
    except Exception:
        return borrador
    if not isinstance(r, dict) or any(not str(r.get(k) or "").strip() for k in ("marco_normativo", "analisis", "conclusion")):
        return borrador
    return r if _palabras(r) >= 0.5 * _palabras(borrador) else borrador
