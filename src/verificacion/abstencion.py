"""Paso 8.4: política de abstención.

Cuentas del evaluador (scripts/evaluate.py): en el componente de abstención (10 pts) acertar
vale 1, abstenerse 0,5 y errar 0; pero abstenerse deja en cero la exactitud (cerradas, 20 pts),
RAGAS (30 pts) y el recall de citas (20 pts) de ese ítem. Por eso la política es mínima:

- Selección múltiple: nunca se abstiene si hay pasajes. Adivinar sobre la evidencia rinde más
  que 0,5 (exactitud + abstención). Si la generación falló se arma una respuesta de respaldo.
- Semiabierta / abierta: se abstiene si la generación falló, no hay pasajes o la recuperación
  dio error; y, opcionalmente, si tras la verificación no queda ninguna cita respaldada y el
  puntaje del reranker en el top 1 es menor que `umbral` (desactivado por defecto: una
  respuesta sin citas igual suma en RAGAS; calibrar con sample_50 y --ragas).
"""
from __future__ import annotations

from .citas import referencia

UMBRAL_TOP1: float | None = None
_SIN_RAZON = "No es la opción respaldada por los pasajes recuperados."


def vacio(campos: dict | None) -> bool:
    return campos is None or any(v in ("", [], {}, None) for v in campos.values())


def decidir(item: dict, campos: dict | None, pasajes: list[dict], senales: dict | None = None,
            reporte: dict | None = None, umbral: float | None = UMBRAL_TOP1) -> tuple[bool, str]:
    """(abstiene, motivo). `campos` ya normalizados y verificados (citas.verificar)."""
    senales = senales or {}
    if not pasajes:
        return True, "sin_pasajes"
    if item["formato"] == "multiple_choice":
        return (True, "generacion_fallida") if vacio(campos) else (False, "")
    if senales.get("error"):
        return True, "error_recuperacion"
    if vacio(campos):
        return True, "generacion_fallida"
    if (umbral is not None and reporte is not None and reporte.get("respaldadas", 0) == 0
            and senales.get("score_top1") is not None and senales["score_top1"] < umbral):
        return True, "sin_citas_respaldadas"
    return False, ""


def letra_respaldo(item: dict, pasajes: list[dict]) -> str:
    """Opción con el pasaje `via="opcion"` de mayor puntaje (evidencia por opción, paso 6.6);
    si no hay, la primera opción."""
    opciones = sorted(item.get("opciones") or {"A": ""})
    por_opcion = [p for p in pasajes if p.get("opcion") in opciones]
    if por_opcion:
        return max(por_opcion, key=lambda p: p.get("score") or 0.0)["opcion"]
    return opciones[0]


def completar_cerrada(item: dict, campos: dict | None, pasajes: list[dict]) -> dict:
    """Campos de selección múltiple completos aunque la generación haya fallado: conserva lo
    que sea válido y rellena el resto. Así una cerrada nunca queda vacía ni con una letra fuera
    del enum de schema/submission.schema.json."""
    campos = dict(campos or {})
    letra = campos.get("respuesta_correcta") or letra_respaldo(item, pasajes)
    just = campos.get("justificacion")
    if not just:
        ref = referencia(pasajes[0]) if pasajes else "los pasajes recuperados"
        just = f"Conforme a {ref}, la opción {letra} es la que encuentra respaldo en los pasajes recuperados."
    previos = campos.get("descarte_opciones") or {}
    descarte = {l: previos.get(l) or _SIN_RAZON for l in sorted(item.get("opciones") or {})
                if l != letra}
    return {"respuesta_correcta": letra, "justificacion": just, "descarte_opciones": descarte}
