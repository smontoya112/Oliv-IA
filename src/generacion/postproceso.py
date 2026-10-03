"""Postproceso estricto de la salida del modelo: longitudes, letras, campos y ensamblado."""
from __future__ import annotations

import json
import re

from src.procesamiento.oraciones import dividir
from src.verificacion import abstencion
from src.verificacion.citas import K_EVIDENCIA, completar_con_evidencia, verificar

from . import cerradas

MAX_PASAJES = 10          # solo cuentan los 10 primeros en la evaluación (evaluate.py)
_SIN_RAZON = abstencion._SIN_RAZON
_CAMPOS_PASAJE = ("doc_id", "inicio", "fin", "texto", "score", "chunk_id", "norma_id", "via",
                  "opcion")


def contar_palabras(texto: str) -> int:
    return len(texto.split())


def recortar(texto: str, max_oraciones: int, max_palabras: int | None = None) -> str:
    """Conserva las primeras oraciones completas sin pasar de los límites. No parte citas
    como "art." o "Ley 80 de 1993" (usa src.procesamiento.oraciones). Si la primera oración
    sola excede el máximo de palabras, la corta por palabras y la cierra con punto."""
    texto = " ".join((texto or "").split())
    if not texto:
        return ""
    oraciones = [texto[a:b] for a, b in dividir(texto)][:max_oraciones]
    salida: list[str] = []
    for o in oraciones:
        if max_palabras and contar_palabras(" ".join(salida + [o])) > max_palabras:
            break
        salida.append(o)
    if not salida:
        palabras = oraciones[0].split()[: max_palabras or None]
        return " ".join(palabras).rstrip(",;:") + "."
    return " ".join(salida)


def parsear_json(crudo: str) -> dict | None:
    """Extrae el primer objeto JSON de la salida del modelo (tolera texto o ```json)."""
    if not crudo:
        return None
    ini, fin = crudo.find("{"), crudo.rfind("}")
    if ini < 0 or fin <= ini:
        return None
    try:
        obj = json.loads(crudo[ini: fin + 1])
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def _letra(valor, opciones: dict) -> str | None:
    m = re.search(r"[A-Da-d]", str(valor or ""))
    letra = m.group(0).upper() if m else None
    return letra if letra in opciones else None


def _texto(valor) -> str:
    return " ".join(str(valor or "").split())


def _razon(analisis: dict, letra: str) -> str:
    v = analisis.get(letra)
    return _texto(v.get("razon") if isinstance(v, dict) else v)


def _normalizar_cerrada(item: dict, salida: dict) -> dict:
    """Con `analisis_opciones` (esquema actual) la letra final la decide
    src.generacion.cerradas.resolver y `descarte_opciones` sale de las razones de las opciones
    no elegidas; si la letra cambió, la justificación pasa a ser la razón de la opción final.
    Sin análisis (salidas de antes o `salida_modelo` ya normalizada) se usa lo que traiga."""
    opciones = item["opciones"]
    letra = _letra(salida.get("respuesta_correcta"), opciones)
    just = _texto(salida.get("justificacion"))
    analisis = salida.get("analisis_opciones")
    decision = None
    if isinstance(analisis, dict) and analisis:
        final, regla = cerradas.resolver(opciones, analisis, letra)
        decision = {"letra_modelo": letra, "letra_final": final, "regla": regla,
                    "veredictos": cerradas.veredictos(analisis, sorted(opciones))}
        if final != letra and final:
            just = _razon(analisis, final) or just
        letra = final
        descarte = {l: _razon(analisis, l) for l in opciones}
    else:
        descarte = salida.get("descarte_opciones")
        descarte = descarte if isinstance(descarte, dict) else {}
        if isinstance(salida.get("decision_cerrada"), dict):   # estrategia "razonada": ya decidió
            decision = salida["decision_cerrada"]
    campos = {"respuesta_correcta": letra,
              "justificacion": recortar(just, 6),
              "descarte_opciones": {l: _texto(descarte.get(l)) or _SIN_RAZON
                                    for l in sorted(opciones) if l != letra}}
    if decision:
        campos["decision_cerrada"] = decision
    return campos


def normalizar(item: dict, salida: dict) -> dict:
    """Deja solo los campos del formato, con tipos y longitudes válidos."""
    f = item["formato"]
    if f == "multiple_choice":
        return _normalizar_cerrada(item, salida)
    if f == "semi_open":
        claves = salida.get("palabras_clave") or []
        claves = claves if isinstance(claves, list) else [claves]
        vistas, limpias = set(), []
        for c in map(_texto, claves):
            if c and c.lower() not in vistas:
                vistas.add(c.lower())
                limpias.append(c)
        max_or, max_pal = item.get("_limites") or (5, 150)      # prompt v2: por sub-tarea
        return {"respuesta": recortar(_texto(salida.get("respuesta")), max_or, max_pal),
                "palabras_clave": limpias[:8],
                "referencia_legal": _texto(salida.get("referencia_legal"))}
    if f == "open_ended":
        return {"marco_normativo": _texto(salida.get("marco_normativo")),
                "analisis": recortar(_texto(salida.get("analisis")), 8),
                "jurisprudencia": _texto(salida.get("jurisprudencia")),
                "conclusion": _texto(salida.get("conclusion"))}
    raise ValueError(f"formato desconocido: {f!r}")


def _vacios(item: dict) -> dict:
    return {"multiple_choice": {"respuesta_correcta": "", "justificacion": "",
                                "descarte_opciones": {}},
            "semi_open": {"respuesta": "", "palabras_clave": [], "referencia_legal": ""},
            "open_ended": {"marco_normativo": "", "analisis": "", "jurisprudencia": "",
                           "conclusion": ""}}[item["formato"]]


def _limpiar(pasajes: list[dict]) -> list[dict]:
    return [{k: p[k] for k in _CAMPOS_PASAJE if p.get(k) is not None} for p in pasajes[:MAX_PASAJES]]


def ensamblar(item: dict, salida: dict | None, pasajes: list[dict],
              latencia_ms: int | None = None, senales: dict | None = None, catalogo=None,
              umbral: float | None = abstencion.UMBRAL_TOP1, k_evidencia: int = K_EVIDENCIA,
              fase8: bool = True) -> dict:
    """Línea final de submissions.jsonl, con la fase 8 aplicada: verificación de citas
    (8.1-8.3, src.verificacion.citas), normas de la evidencia principal y abstención (8.4,
    src.verificacion.abstencion).

    `pasajes` son TODOS los recuperados (no solo los que cupieron en el prompt): los que
    respaldan una cita suben al top 10. `senales` vienen de la recuperación (fase 6) y
    `catalogo` (src.recuperacion.catalogo) permite traer el pasaje de una norma citada que no
    estaba entre los recuperados; sin él, las citas sin respaldo se eliminan.

    `salida_modelo` guarda los campos normalizados ANTES de la fase 8, para poder reaplicarla
    (src.verificacion.aplicar). Con `fase8=False` solo se normaliza: es la línea base.
    En las cerradas, `decision_cerrada` registra la letra del modelo, la final y la regla
    aplicada (src.generacion.cerradas)."""
    base = {"id": item["id"], "formato": item["formato"]}
    if latencia_ms is not None:
        base["latencia_ms"] = latencia_ms
    campos = normalizar(item, salida) if salida else None
    decision = campos.pop("decision_cerrada", None) if campos else None
    crudo = {"salida_modelo": campos, **({"decision_cerrada": decision} if decision else {})}
    if not fase8:
        if abstencion.vacio(campos) or not pasajes:
            return {**base, **_abstenido(item, pasajes), "pasajes_recuperados": _limpiar(pasajes),
                    **crudo}
        return {**base, "abstencion": False, **campos, "pasajes_recuperados": _limpiar(pasajes),
                **crudo}
    if item["formato"] == "multiple_choice" and pasajes:
        campos = abstencion.completar_cerrada(item, campos, pasajes)
    top, reporte = _limpiar(pasajes), None
    if campos is not None and not abstencion.vacio(campos) and pasajes:
        campos, top, reporte = verificar(item, campos, pasajes, catalogo)
        top = _limpiar(top)
    abstiene, motivo = abstencion.decidir(item, campos, top, senales, reporte, umbral)
    if abstiene:
        return {**base, **_abstenido(item, pasajes), "pasajes_recuperados": top,
                "verificacion": {"motivo_abstencion": motivo}, **crudo}
    campos, agregadas = completar_con_evidencia(item, campos, top, k_evidencia)
    reporte["agregadas"] = agregadas
    return {**base, "abstencion": False, **campos, "pasajes_recuperados": top,
            "verificacion": reporte, **crudo}


def _abstenido(item: dict, pasajes: list[dict]) -> dict:
    vacios = _vacios(item)
    if item["formato"] == "multiple_choice":     # el enum del schema no admite "" ni null
        vacios["respuesta_correcta"] = abstencion.letra_respaldo(item, pasajes)
    return {"abstencion": True, **vacios}
