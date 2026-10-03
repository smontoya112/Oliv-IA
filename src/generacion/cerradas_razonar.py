"""Cerradas: razonar primero, comprometer después (estrategia "razonada").

El esquema anterior (src.generacion.cerradas) obligaba a Qwen3 a escribir JSON desde el primer
token: el modelo nunca razonaba y el "análisis por opción" era una justificación posterior al
veredicto. Aquí cada pregunta pasa por tres señales sobre los MISMOS pasajes:

1. Razonamiento: Qwen3 piensa libremente dentro de `<think>` (presupuesto en tokens) y después
   escribe el JSON final del esquema de siempre (`esquemas.esquema_cerrada`).
2. Logits: probabilidad de cada letra sin razonar, promediada sobre permutaciones cíclicas de las
   opciones (quita el sesgo de posición). Si hay opciones compuestas ("todas", "A y B"…) no se
   permuta: sus referencias dependen del orden.
3. Evidencia: la opción cuyos pasajes `via="opcion"` tienen el mayor puntaje del reranker (solo
   diagnóstico: sola acierta 4/15 en `sample_50`, el azar, así que NO entra en ninguna política).

La letra final la decide `decidir` con una política fija (ver POLITICAS). Todas las señales se
guardan en `decision_cerrada` para poder comparar políticas sin volver a generar.
"""
from __future__ import annotations

import json
import os
import time
from collections import defaultdict

from src.verificacion import abstencion

from . import cerradas
from .esquemas import esquema_item
from .prompts import construir_mensajes, formatear_pasajes

POLITICAS = ("razonada", "resolver", "ens", "voto")
POLITICA_DEFECTO = "razonada"
MAX_PENSAR = 1200
MAX_FINAL = 700
PERMUTACIONES = 4
UMBRAL_VOTO = 0.6          # el ensamble tiene que estar bastante seguro de su letra...
UMBRAL_RAZONADA = 0.15     # ...y darle poca probabilidad a la del razonamiento

_INSTRUCCION_RAZONAR = (
    "\n\nAntes de responder, razona de forma breve y ordenada: (1) identifica la norma o regla que "
    "decide la pregunta; (2) contrasta cada opción con el TEXTO de los pasajes (cifras, plazos, "
    "sujetos, condiciones, excepciones); (3) descarta las incorrectas. Si los pasajes no cubren "
    "el punto, apóyate en tu conocimiento del derecho colombiano y elige la opción más probable. "
    "Termina el razonamiento con una sola opción.")


def _pasajes_permutados(pasajes: list[dict], destino: dict[str, str]) -> list[dict]:
    """Copia de los pasajes con la etiqueta `opcion` reescrita a la letra que la opción tiene ahora."""
    return [{**p, "opcion": destino.get(p.get("opcion"), p.get("opcion"))} if p.get("opcion") else p
            for p in pasajes]


def _item_permutado(item: dict, orden: list[str]) -> tuple[dict, dict[str, str], dict[str, str]]:
    """(item con las opciones reordenadas, letra_nueva -> letra_original, original -> nueva)."""
    letras = sorted(item["opciones"])
    nueva_a_orig = {n: o for n, o in zip(letras, orden)}
    orig_a_nueva = {o: n for n, o in nueva_a_orig.items()}
    opciones = {n: item["opciones"][o] for n, o in nueva_a_orig.items()}
    return {**item, "opciones": opciones}, nueva_a_orig, orig_a_nueva


def ordenes(letras: list[str], k: int) -> list[list[str]]:
    """Rotaciones cíclicas: [A,B,C,D], [B,C,D,A], [C,D,A,B], [D,A,B,C] (las primeras k)."""
    n = len(letras)
    return [letras[i:] + letras[:i] for i in range(min(k, n))]


def permutable(opciones: dict) -> bool:
    """Solo si ninguna opción remite a otras (todas / ninguna / "A y B")."""
    return all(t["tipo"] == "simple" for t in cerradas.clasificar(opciones).values())


def mensajes_cerrada(item: dict, pasajes: list[dict], presupuesto: int, contar=None) -> list[dict]:
    texto, _ = formatear_pasajes(pasajes, presupuesto, contar)
    msgs = construir_mensajes(item, texto, None)
    msgs[-1] = {"role": "user", "content": msgs[-1]["content"] + _INSTRUCCION_RAZONAR}
    return msgs


def mensajes_letra(item: dict, pasajes: list[dict], presupuesto: int, contar=None) -> list[dict]:
    """Prompt para leer solo la letra: sin JSON, sin razonamiento."""
    texto, _ = formatear_pasajes(pasajes, presupuesto, contar)
    msgs = construir_mensajes(item, texto, None)
    cuerpo = msgs[-1]["content"].split("\n\n=== PASAJES ===", 1)[1]
    letras = ", ".join(sorted(item["opciones"]))
    usuario = ("Pregunta de opción múltiple de derecho colombiano. Responde ÚNICAMENTE con la "
               f"letra de la opción correcta ({letras}), sin explicación.\n\n=== PASAJES ===" + cuerpo)
    return [msgs[0], {"role": "user", "content": usuario}]


def promedio_permutaciones(motor, item: dict, pasajes: list[dict], presupuesto: int, k: int,
                           contar=None, reiniciar_primero: bool = True,
                           **variante) -> tuple[dict, list[dict]]:
    """(probabilidad media por letra ORIGINAL, lista de probabilidades por permutación)."""
    letras = sorted(item["opciones"])
    ords = ordenes(letras, k) if permutable(item["opciones"]) else [letras]
    por_perm, suma = [], defaultdict(float)
    for j, orden in enumerate(ords):
        it, nueva_a_orig, orig_a_nueva = _item_permutado(item, orden)
        ps = _pasajes_permutados(pasajes, orig_a_nueva)
        p = motor.probabilidades_letras(mensajes_letra(it, ps, presupuesto, contar, **variante),
                                        letras, reiniciar=(j == 0 and reiniciar_primero))
        p_orig = {nueva_a_orig[n]: v for n, v in p.items()}
        por_perm.append({l: round(p_orig[l], 4) for l in letras})
        for l, v in p_orig.items():
            suma[l] += v
    media = {l: suma[l] / len(ords) for l in letras}
    return media, por_perm


def _argmax(p: dict) -> str | None:
    return max(sorted(p), key=lambda l: p[l]) if p else None


def decidir(politica: str, opciones: dict, analisis: dict, letra_razonada: str | None,
            p_ens: dict | None, letra_evidencia: str | None) -> tuple[str | None, str]:
    """(letra final, regla). Políticas, fijadas antes de ver resultados:
    - razonada: la letra del JSON final tras pensar.
    - resolver: igual, pero con las reglas de opciones compuestas de src.generacion.cerradas.
    - ens: argmax de la probabilidad media de las permutaciones (sin razonar).
    - voto: la razonada, salvo desacuerdo fuerte del ensamble: P(ens) >= UMBRAL_VOTO y
      P(razonada) <= UMBRAL_RAZONADA."""
    letras = set(opciones)
    razonada = letra_razonada if letra_razonada in letras else None
    ens = _argmax(p_ens) if p_ens else None
    if politica == "ens":
        return (ens or razonada), "ens"
    if politica == "resolver":
        letra, regla = cerradas.resolver(opciones, analisis, razonada)
        return (letra if letra in letras else razonada), regla
    if politica == "voto":
        if ens and ens != razonada and p_ens[ens] >= UMBRAL_VOTO                 and p_ens.get(razonada, 0.0) <= UMBRAL_RAZONADA:
            return ens, "voto_ens"
        return (razonada or ens), "razonada"
    return razonada, "razonada"


def _texto(v) -> str:
    return " ".join(str(v or "").split())


def _razon(analisis: dict, letra: str) -> str:
    v = analisis.get(letra) if isinstance(analisis, dict) else None
    return _texto(v.get("razon") if isinstance(v, dict) else v)


def salida_final(item: dict, final: dict | None, letra: str | None, decision: dict) -> dict:
    """Dict con la forma que consume postproceso.normalizar (sin `analisis_opciones`, para que
    NO se vuelva a aplicar cerradas.resolver: la política ya decidió la letra)."""
    final = final or {}
    analisis = final.get("analisis_opciones") or {}
    razonada = decision.get("letra_razonada")
    just = _texto(final.get("justificacion")) if letra == razonada else ""
    just = just or _razon(analisis, letra) if letra else just
    return {"respuesta_correcta": letra, "justificacion": just,
            "descarte_opciones": {l: _razon(analisis, l) for l in item["opciones"] if l != letra},
            "decision_cerrada": decision}


def responder(item: dict, pasajes: list[dict], motor, politica: str | None = None,
              presupuesto: int = 4500, max_pensar: int | None = None, k_perm: int | None = None,
              contar=None) -> dict:
    """Salida cruda de una cerrada con la estrategia razonada (ver el docstring del módulo)."""
    politica = politica or os.environ.get("OLIVIA_POLITICA_CERRADAS") or POLITICA_DEFECTO
    max_pensar = max_pensar or int(os.environ.get("OLIVIA_MAX_PENSAR", MAX_PENSAR))
    k_perm = PERMUTACIONES if k_perm is None else k_perm
    contar = contar or getattr(motor, "contar", None)
    opciones = item["opciones"]
    letras = sorted(opciones)

    p_ens, por_perm = None, []
    t0 = time.perf_counter()
    if k_perm > 0 and hasattr(motor, "probabilidades_letras"):
        p_ens, por_perm = promedio_permutaciones(motor, item, pasajes, presupuesto, k_perm, contar)
    t_ens = time.perf_counter() - t0
    t0 = time.perf_counter()
    pens = motor.pensar(mensajes_cerrada(item, pasajes, presupuesto, contar), esquema_item(item),
                        max_pensar=max_pensar, max_final=MAX_FINAL, reiniciar=p_ens is None)
    t_pensar = time.perf_counter() - t0
    try:
        final = json.loads(pens["final"])
        final = final if isinstance(final, dict) else None
    except json.JSONDecodeError:
        final = None
    analisis = (final or {}).get("analisis_opciones") or {}
    razonada = (final or {}).get("respuesta_correcta")
    evidencia = abstencion.letra_respaldo(item, pasajes) if any(
        p.get("opcion") for p in pasajes) else None
    letra, regla = decidir(politica, opciones, analisis, razonada, p_ens, evidencia)
    decision = {"estrategia": "razonada", "politica": politica, "regla": regla,
                "letra_razonada": razonada if razonada in opciones else None,
                "letra_resolver": cerradas.resolver(opciones, analisis, razonada)[0] if analisis else None,
                "letra_ens": _argmax(p_ens) if p_ens else None, "letra_evidencia": evidencia,
                "letra_final": letra,
                "p_ens": {l: round(v, 4) for l, v in (p_ens or {}).items()},
                "p_permutaciones": por_perm, "tokens_pensar": pens["tokens_pensar"],
                "segundos": {"ens": round(t_ens, 1), "pensar": round(t_pensar, 1)},
                "pensamiento_cortado": pens["cortado"]}
    return salida_final(item, final, letra, decision)
