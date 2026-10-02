"""Une prompts + motor + postproceso. Es la interfaz que usará la fase 6/8."""
from __future__ import annotations

import logging
import time

from src.verificacion import abstencion

from .ejemplos import EJEMPLOS
from .esquemas import esquema
from .postproceso import ensamblar, normalizar, parsear_json
from .prompts import construir_mensajes, formatear_pasajes

log = logging.getLogger("generacion")
PRESUPUESTO_TOKENS = 4500          # contexto de pasajes (el paso 6.7 pide entre 3.000 y 5.000)
MAX_TOKENS_SALIDA = {"multiple_choice": 700, "semi_open": 600, "open_ended": 1100}
FACTOR_REINTENTO = 2               # el reintento de una salida inválida usa este múltiplo del tope


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
    return msgs, esquema(item["formato"]), usados


def _fallida(item: dict, crudo: str) -> bool:
    salida = parsear_json(crudo)
    return salida is None or abstencion.vacio(normalizar(item, salida))


def _reintentar_fallidos(items: list[dict], prep: list, crudos: list[str], motor,
                         tope: int) -> None:
    """Una salida sin JSON válido (típicamente cortada por el tope de tokens) se abstendría y
    dejaría el ítem en cero; se regenera una vez con el doble de tope. Modifica `crudos`."""
    malos = [k for k, (it, c) in enumerate(zip(items, crudos)) if _fallida(it, c)]
    if not malos:
        return
    log.warning("reintentando %d ítems sin salida válida con max_tokens=%d: %s", len(malos),
                tope * FACTOR_REINTENTO, [items[k]["id"] for k in malos])
    try:
        nuevos = motor.generar_lote([prep[k][0] for k in malos], [prep[k][1] for k in malos],
                                    max_tokens=tope * FACTOR_REINTENTO)
    except Exception as e:                      # p. ej. el tope nuevo no cabe en el contexto
        log.warning("reintento fallido (%s): se conserva la primera salida", e)
        return
    for k, nuevo in zip(malos, nuevos):
        if not _fallida(items[k], nuevo):
            crudos[k] = nuevo


def generar_lote(items: list[dict], pasajes_por_id: dict, motor,
                 presupuesto: int = PRESUPUESTO_TOKENS,
                 ejemplos: dict[str, list[dict]] | None = None,
                 senales_por_id: dict | None = None, catalogo=None) -> list[dict]:
    """Genera todos los ítems en un solo lote. Devuelve las líneas de submissions.jsonl
    (con latencia_ms = tiempo del lote / n, la medición fina está en bench.py).

    `ensamblar` recibe todos los pasajes recuperados (no solo los del prompt) para que la
    fase 8 pueda verificar las citas contra el top 10 completo."""
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
