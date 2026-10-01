"""Une prompts + motor + postproceso. Es la interfaz que usará la fase 6/8."""
from __future__ import annotations

import time

from .esquemas import esquema
from .postproceso import ensamblar, parsear_json
from .prompts import construir_mensajes, formatear_pasajes

PRESUPUESTO_TOKENS = 4500          # contexto de pasajes (el paso 6.7 pide entre 3.000 y 5.000)
MAX_TOKENS_SALIDA = {"multiple_choice": 700, "semi_open": 600, "open_ended": 1100}


def preparar(item: dict, pasajes: list[dict], presupuesto: int = PRESUPUESTO_TOKENS,
             ejemplos: dict[str, list[dict]] | None = None):
    """(mensajes, esquema, pasajes_incluidos) de un ítem."""
    texto, usados = formatear_pasajes(pasajes, presupuesto)
    msgs = construir_mensajes(item, texto, (ejemplos or {}).get(item["formato"]))
    return msgs, esquema(item["formato"]), usados


def generar_lote(items: list[dict], pasajes_por_id: dict, motor,
                 presupuesto: int = PRESUPUESTO_TOKENS,
                 ejemplos: dict[str, list[dict]] | None = None) -> list[dict]:
    """Genera todos los ítems en un solo lote vLLM. Devuelve las líneas de submissions.jsonl
    (con latencia_ms = tiempo del lote / n, la medición fina está en bench.py)."""
    prep = [preparar(it, pasajes_por_id.get(it["id"], []), presupuesto, ejemplos) for it in items]
    t0 = time.perf_counter()
    # vLLM acepta un tope de tokens por llamada: se usa el mayor de los formatos presentes.
    tope = max(MAX_TOKENS_SALIDA[it["formato"]] for it in items)
    crudos = motor.generar_lote([p[0] for p in prep], [p[1] for p in prep], max_tokens=tope)
    ms = int((time.perf_counter() - t0) * 1000 / max(len(items), 1))
    return [ensamblar(it, parsear_json(c), p[2], ms)
            for it, c, p in zip(items, crudos, prep)]


def generar(item: dict, pasajes: list[dict], motor, **kw) -> dict:
    return generar_lote([item], {item["id"]: pasajes}, motor, **kw)[0]
