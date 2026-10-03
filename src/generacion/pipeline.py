"""Une prompts + motor + postproceso. Es la interfaz que usará la fase 6/8."""
from __future__ import annotations

import json
import logging
import os
import time

from src.verificacion import abstencion

from .ejemplos import EJEMPLOS
from .esquemas import esquema_item
from .postproceso import ensamblar, normalizar, parsear_json
from .prompts import SISTEMA_LIBRE, construir_mensajes, formatear_pasajes

log = logging.getLogger("generacion")
PRESUPUESTO_TOKENS = 4500          # contexto de pasajes (el paso 6.7 pide entre 3.000 y 5.000)
MAX_TOKENS_SALIDA = {"multiple_choice": 900, "semi_open": 600, "open_ended": 1100}
PENALIZACION_REINTENTO = 1.2       # repeat_penalty al reintentar: Qwen3 en voraz entra en bucles
ESTRATEGIAS = ("actual", "razonada")
MAX_TOKENS_LIBRE = {"semi_open": 450, "open_ended": 1000}      # prompt v2 (respuestas más cortas)


def estrategia_activa(estrategia: str | None = None) -> str:
    """"actual" (un JSON por pregunta) o "razonada" (cerradas: razonar y comprometer; texto libre:
    prompt por sub-tarea). Sale del argumento, de OLIVIA_ESTRATEGIA o de config/responder.json."""
    e = estrategia or os.environ.get("OLIVIA_ESTRATEGIA") or "actual"
    if e not in ESTRATEGIAS:
        raise ValueError(f"estrategia desconocida: {e!r} (válidas: {ESTRATEGIAS})")
    return e


def preparar(item: dict, pasajes: list[dict], presupuesto: int = PRESUPUESTO_TOKENS,
             ejemplos: dict[str, list[dict]] | None = None, contar=None):
    """(mensajes, esquema, pasajes_incluidos) de un ítem. `contar` es el contador de tokens
    del decoder (Motor.contar); sin él se estima por caracteres.

    `ejemplos` por defecto (None) usa los few-shot propios de la Fase 7.3
    (src.generacion.ejemplos.EJEMPLOS); pasa `{}` para desactivarlos (p. ej. en una
    ablación de tiempo/calidad)."""
    ejemplos = EJEMPLOS if ejemplos is None else ejemplos
    texto, usados = formatear_pasajes(pasajes, presupuesto, contar)
    msgs = construir_mensajes(item, texto, ejemplos.get(item["formato"]))
    return msgs, esquema_item(item), usados


def _fallida(item: dict, crudo: str) -> bool:
    salida = parsear_json(crudo)
    return salida is None or abstencion.vacio(normalizar(item, salida))


def _reintentar_fallidos(items: list[dict], prep: list, crudos: list[str], motor,
                         tope: int) -> None:
    """Una salida sin JSON válido se abstendría y dejaría el ítem en cero. En el ítem 247 el
    modelo repetía texto hasta el tope (el doble de tokens tampoco lo cerraba), así que se
    regenera una vez con el MISMO tope y repeat_penalty. Modifica `crudos`."""
    malos = [k for k, (it, c) in enumerate(zip(items, crudos)) if _fallida(it, c)]
    if not malos:
        return
    for k in malos:
        c = crudos[k] or ""
        log.warning("salida inválida del ítem %s (%d caracteres), inicio=%r fin=%r",
                    items[k]["id"], len(c), c[:120], c[-120:])
    log.warning("reintentando %d ítems con repeat_penalty=%s", len(malos), PENALIZACION_REINTENTO)
    try:
        nuevos = motor.generar_lote([prep[k][0] for k in malos], [prep[k][1] for k in malos],
                                    max_tokens=tope, repeat_penalty=PENALIZACION_REINTENTO)
    except Exception as e:
        log.warning("reintento fallido (%s): se conserva la primera salida", e)
        return
    for k, nuevo in zip(malos, nuevos):
        if not _fallida(items[k], nuevo):
            crudos[k] = nuevo


def _salida_razonada(item: dict, pasajes: list[dict], motor, presupuesto: int, contar):
    """(item para ensamblar, salida cruda) con la estrategia "razonada"."""
    from . import cerradas_razonar, subtarea
    if item["formato"] == "multiple_choice":
        if getattr(motor, "admite_pensar", False) and hasattr(motor, "probabilidades_letras"):
            return item, cerradas_razonar.responder(item, pasajes, motor, presupuesto=presupuesto,
                                                    contar=contar)
        msgs, esquema, _ = preparar(item, pasajes, presupuesto, None, contar)
        crudo = motor.generar_lote([msgs], [esquema], max_tokens=MAX_TOKENS_SALIDA[item["formato"]])[0]
        return item, parsear_json(crudo)
    it = {**item, "_limites": subtarea.limites(item)}
    if it["formato"] == "semi_open" and subtarea.clave(it) == "literal":
        copiada = subtarea.literal(it, pasajes)          # el texto del artículo, sin generar
        if copiada:
            return it, copiada
    texto, _ = formatear_pasajes(pasajes, presupuesto, contar)
    msgs = construir_mensajes(it, texto, None, instrucciones=subtarea.instrucciones(it),
                              sistema=SISTEMA_LIBRE if os.environ.get("OLIVIA_SISTEMA_LIBRE", "1") == "1" else None)
    crudo = motor.generar_lote([msgs], [esquema_item(it)],
                               max_tokens=MAX_TOKENS_LIBRE[it["formato"]])[0]
    salida = parsear_json(crudo)
    if salida is None or abstencion.vacio(normalizar(it, salida)):   # un solo reintento, como antes
        nuevo = motor.generar_lote([msgs], [esquema_item(it)],
                                   max_tokens=MAX_TOKENS_LIBRE[it["formato"]],
                                   repeat_penalty=PENALIZACION_REINTENTO)[0]
        salida = parsear_json(nuevo) or salida
    return it, salida


def _generar_razonada(items: list[dict], pasajes_por_id: dict, motor, presupuesto: int,
                      senales_por_id: dict | None, catalogo) -> list[dict]:
    contar = getattr(motor, "contar", None)
    senales_por_id = senales_por_id or {}
    res = []
    for it in items:
        t0 = time.perf_counter()
        pasajes = pasajes_por_id.get(it["id"], [])
        item, salida = _salida_razonada(it, pasajes, motor, presupuesto, contar)
        ms = int((time.perf_counter() - t0) * 1000)
        res.append(ensamblar(item, salida, pasajes, ms, senales_por_id.get(it["id"]), catalogo))
    return res


def generar_lote(items: list[dict], pasajes_por_id: dict, motor,
                 presupuesto: int = PRESUPUESTO_TOKENS,
                 ejemplos: dict[str, list[dict]] | None = None,
                 senales_por_id: dict | None = None, catalogo=None,
                 estrategia: str | None = None) -> list[dict]:
    """Genera todos los ítems en un solo lote. Devuelve las líneas de submissions.jsonl
    (con latencia_ms = tiempo del lote / n, la medición fina está en bench.py).

    `ensamblar` recibe todos los pasajes recuperados (no solo los del prompt) para que la
    fase 8 pueda verificar las citas contra el top 10 completo.

    `estrategia` ("actual" | "razonada", ver `estrategia_activa`): la razonada procesa cada ítem
    por separado (razonamiento libre en cerradas, prompt por sub-tarea en texto libre)."""
    if estrategia_activa(estrategia) == "razonada":
        return _generar_razonada(items, pasajes_por_id, motor, presupuesto, senales_por_id, catalogo)
    contar = getattr(motor, "contar", None)
    prep = [preparar(it, pasajes_por_id.get(it["id"], []), presupuesto, ejemplos, contar)
            for it in items]
    t0 = time.perf_counter()
    # El motor recibe un solo tope de tokens por lote: se usa el mayor de los formatos presentes.
    tope = max(MAX_TOKENS_SALIDA[it["formato"]] for it in items)
    crudos = list(motor.generar_lote([p[0] for p in prep], [p[1] for p in prep], max_tokens=tope))
    _reintentar_fallidos(items, prep, crudos, motor, tope)
    ms = int((time.perf_counter() - t0) * 1000 / max(len(items), 1))
    senales_por_id = senales_por_id or {}
    return [ensamblar(it, parsear_json(c), pasajes_por_id.get(it["id"], []), ms,
                      senales_por_id.get(it["id"]), catalogo)
            for it, c in zip(items, crudos)]


def generar(item: dict, pasajes: list[dict], motor, **kw) -> dict:
    return generar_lote([item], {item["id"]: pasajes}, motor, **kw)[0]
