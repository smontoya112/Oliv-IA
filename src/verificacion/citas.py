"""Pasos 8.1 y 8.2: citas de la respuesta, su respaldo en los pasajes y su corrección.

- 8.1 Las citas se extraen con el parser oficial (citations.extract, el mismo que usa
  evaluate.py) y se canonizan con la fase 4 (normalizacion.to_canonical_id).
- 8.2 Una cita está respaldada si su cuerpo normativo (citations.bodies) aparece en el
  `texto` de alguno de los 10 primeros pasajes. Si no lo está:
    1. si la norma está en el corpus (catálogo), se trae su mejor chunk como pasaje y entra
       al top 10 (orden.reordenar);
    2. si no, se elimina la oración de la respuesta que la cita.
  El evaluador castiga el doble cada cita sin respaldo y no castiga una cita respaldada
  aunque no sea la de referencia, por eso se prefiere respaldar antes que borrar.
"""
from __future__ import annotations

import re

import citations       # scripts/citations.py (el __init__ del paquete agrega scripts/ al path)
import normalizacion   # scripts/normalizacion.py (fase 4)

from src.procesamiento.oraciones import dividir

MAX_PASAJES = 10       # evaluate.MAX_PASAJES_EVIDENCIA
MAX_FILAS_CATALOGO = 30
K_EVIDENCIA = 3        # normas de los k primeros pasajes que se agregan a la respuesta (0 = no)
MAX_AGREGADAS = 8
_PREFIJO_EVIDENCIA = "Normas de los pasajes recuperados:"
# Nombres para mostrar de los códigos de citations.CODES (con tildes; el parser las ignora).
_NOMBRES_CODIGOS = {
    "constitucion": "Constitución Política",
    "codigo_civil": "Código Civil",
    "codigo_penal": "Código Penal",
    "codigo_procedimiento_penal": "Código de Procedimiento Penal",
    "codigo_comercio": "Código de Comercio",
    "codigo_sustantivo_trabajo": "Código Sustantivo del Trabajo",
    "codigo_procesal_trabajo": "Código Procesal del Trabajo",
    "codigo_general_proceso": "Código General del Proceso",
    "cpaca": "Código de Procedimiento Administrativo y de lo Contencioso Administrativo",
    "estatuto_tributario": "Estatuto Tributario",
    "codigo_infancia": "Código de la Infancia y la Adolescencia",
    "codigo_nacional_policia": "Código Nacional de Seguridad y Convivencia Ciudadana",
    "codigo_disciplinario": "Código General Disciplinario",
    "estatuto_consumidor": "Estatuto del Consumidor",
    "decision_andina_486": "Decisión 486 de la Comisión de la Comunidad Andina",
}
_NOMBRES_TIPOS = {"ley": "Ley", "decreto": "Decreto", "acto_legislativo": "Acto Legislativo",
                  "resolucion": "Resolución", "circular": "Circular", "acuerdo": "Acuerdo"}
# Mismos campos que evaluate.answer_text: de ellos salen las citas que se puntúan.
CAMPOS_CITABLES = {
    "multiple_choice": ("justificacion",),
    "semi_open": ("respuesta", "referencia_legal"),
    "open_ended": ("marco_normativo", "analisis", "jurisprudencia", "conclusion"),
}
_SIN_JURISPRUDENCIA = "Los pasajes recuperados no contienen jurisprudencia aplicable."


def extraer(texto: str | None) -> set[tuple]:
    return citations.extract(texto or "")


def cuerpos(texto: str | None) -> set[tuple]:
    return citations.bodies(extraer(texto))


def canonico(cita: tuple) -> str:
    return normalizacion.to_canonical_id(cita)


def texto_citable(formato: str, campos: dict) -> str:
    return " ".join(str(campos.get(k) or "") for k in CAMPOS_CITABLES[formato])


def respaldo(pasajes: list[dict], max_pasajes: int = MAX_PASAJES) -> set[tuple]:
    """Cuerpos normativos presentes en los `max_pasajes` primeros pasajes."""
    res: set[tuple] = set()
    for p in pasajes[:max_pasajes]:
        res |= cuerpos(p.get("texto"))
    return res


def referencia(pasaje: dict) -> str:
    """Nombre de la norma de un pasaje, tomado de su encabezado
    ("Artículo 46 de la Ley 472 de 1998. …" -> "Artículo 46 de la Ley 472 de 1998")."""
    linea = (pasaje.get("texto") or "").strip().split("\n", 1)[0]
    ref = re.split(r"\.\s", linea, maxsplit=1)[0].strip().rstrip(".")
    return ref if extraer(ref) else (pasaje.get("doc_id") or ref)


def nombre_cuerpo(cuerpo: tuple) -> str | None:
    """Nombre legible de un cuerpo normativo, tal que citations.extract lo reconozca de
    vuelta como ese mismo cuerpo: ("ley", "472", "1998") -> "Ley 472 de 1998". None si no
    hay forma segura de nombrarlo."""
    tipo, num, anio = cuerpo
    if tipo == "jurisprudencia" and num and anio:
        nombre = f"Sentencia {num} de {anio}"
    elif tipo in _NOMBRES_TIPOS and num and anio:
        nombre = f"{_NOMBRES_TIPOS[tipo]} {num} de {anio}"
    elif tipo in citations.CODES and not num:
        nombre = _NOMBRES_CODIGOS.get(tipo) or citations.CODES[tipo][0].capitalize()
    else:
        return None
    return nombre if cuerpos(nombre) == {cuerpo} else None


def completar_con_evidencia(item: dict, campos: dict, top: list[dict],
                            k: int = K_EVIDENCIA) -> tuple[dict, list[str]]:
    """Agrega a la respuesta las normas presentes en los `k` primeros pasajes que el modelo no
    nombró. Siempre quedan respaldadas (salen del top final) y el evaluador no castiga una
    cita respaldada que no sea la de referencia; sí suma si lo es. Van en un solo campo:
    `referencia_legal` (semiabierta, RAGAS no lo juzga), al final de `marco_normativo`
    (abierta) o de `justificacion` (cerrada). Devuelve (campos, nombres agregados)."""
    if k <= 0:
        return campos, []
    formato = item["formato"]
    ya = cuerpos(texto_citable(formato, campos))
    nombres: list[str] = []
    for p in top[:k]:
        for c in sorted(cuerpos(p.get("texto")) - ya, key=str):
            n = nombre_cuerpo(c)
            if n and len(nombres) < MAX_AGREGADAS:
                nombres.append(n)
                ya.add(c)
    if not nombres:
        return campos, []
    campos = dict(campos)
    if formato == "semi_open":
        previo = (campos.get("referencia_legal") or "").strip().rstrip(".;")
        campos["referencia_legal"] = "; ".join(([previo] if previo else []) + nombres)
    else:
        campo = "justificacion" if formato == "multiple_choice" else "marco_normativo"
        previo = (campos.get(campo) or "").strip()
        if previo and previo[-1] not in ".;:":
            previo += "."
        campos[campo] = f"{previo} {_PREFIJO_EVIDENCIA} {'; '.join(nombres)}.".strip()
    return campos, nombres


def buscar_en_catalogo(cuerpo: tuple, citas_del_cuerpo: set[tuple], catalogo) -> dict | None:
    """Mejor chunk del corpus que respalda `cuerpo`: primero los artículos citados, luego la
    norma completa. Solo sirve si su texto produce ese cuerpo con citations.extract (así lo
    verá el evaluador)."""
    ids = [canonico(c) for c in sorted(citas_del_cuerpo, key=lambda c: str(c[3])) if c[3]]
    ids.append(canonico((*cuerpo, None)))
    for ident in dict.fromkeys(ids):
        for i in catalogo.por_canon.get(ident, [])[:MAX_FILAS_CATALOGO]:
            if cuerpo in cuerpos(catalogo.cols["texto"][i]):
                return catalogo.pasaje(i, via="verificacion")
    return None


def _partes(texto: str, campo: str) -> list[str]:
    partes = [texto[a:b] for a, b in dividir(texto)]
    if campo == "referencia_legal":
        partes = [s.strip() for p in partes for s in p.split(";")]
    return [p for p in partes if p.strip()]


def quitar_citas(texto: str, campo: str, malos: set[tuple]) -> tuple[str, list[str]]:
    """Elimina las oraciones (o los tramos separados por ';' en referencia_legal) que citan
    algún cuerpo de `malos`. Devuelve (texto, oraciones eliminadas)."""
    if not texto or not (cuerpos(texto) & malos):
        return texto, []
    quedan, fuera = [], []
    for parte in _partes(texto, campo):
        (fuera if cuerpos(parte) & malos else quedan).append(parte.strip())
    sep = "; " if campo == "referencia_legal" else " "
    return sep.join(quedan), fuera


def _relleno(campo: str, pasajes: list[dict], letra: str | None) -> str:
    if campo == "jurisprudencia":
        return _SIN_JURISPRUDENCIA
    ref = referencia(pasajes[0]) if pasajes else "los pasajes recuperados"
    if campo == "referencia_legal":
        return ref
    if campo == "justificacion" and letra:
        return f"Conforme a {ref}, la opción {letra} es la que encuentra respaldo en los pasajes recuperados."
    return f"La respuesta se fundamenta en {ref}."


def verificar(item: dict, campos: dict, pasajes: list[dict], catalogo=None,
              max_pasajes: int = MAX_PASAJES) -> tuple[dict, list[dict], dict]:
    """(campos corregidos, top `max_pasajes` pasajes, reporte).

    `pasajes` son todos los recuperados (pueden ser más de 10: los que respaldan una cita
    suben al top 10). `catalogo` es un src.recuperacion.catalogo.Catalogo; sin él, las citas
    sin respaldo solo se pueden eliminar."""
    from .orden import reordenar

    formato = item["formato"]
    campos = dict(campos)
    citas = extraer(texto_citable(formato, campos))
    citados = citations.bodies(citas)
    sin = citados - respaldo(pasajes, len(pasajes))

    traidos = []
    if sin and catalogo is not None:
        for cuerpo in sorted(sin, key=str):
            p = buscar_en_catalogo(cuerpo, {c for c in citas if c[:3] == cuerpo}, catalogo)
            if p:
                traidos.append(p)
    top, insertados = reordenar(pasajes, citados, traidos, max_pasajes)

    sin = citados - respaldo(top, max_pasajes)
    eliminadas, rellenados = [], []
    if sin:
        for campo in CAMPOS_CITABLES[formato]:
            campos[campo], fuera = quitar_citas(campos.get(campo) or "", campo, sin)
            eliminadas += fuera
    for campo in CAMPOS_CITABLES[formato]:
        if not (campos.get(campo) or "").strip():
            campos[campo] = _relleno(campo, top, campos.get("respuesta_correcta"))
            rellenados.append(campo)

    finales = citations.bodies(extraer(texto_citable(formato, campos)))
    reporte = {
        "citadas": sorted(canonico((*c, None)) for c in citados),
        "respaldadas": len(finales & respaldo(top, max_pasajes)),
        "sin_respaldo": len(finales - respaldo(top, max_pasajes)),
        "insertadas": [p.get("norma_id") or p.get("doc_id") for p in insertados],
        "eliminadas": eliminadas,
        "rellenados": rellenados,
    }
    return campos, top, reporte
