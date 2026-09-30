"""Línea de contexto que se antepone a cada fragmento.

El evaluador da por respaldada una cita solo si `citations.extract` encuentra la norma
en el texto del pasaje. Estos nombres están escritos para que la reconozca: usan las
variantes de `citations.CODES` o la forma "Ley N de AAAA".
"""
from __future__ import annotations

import citations

# doc_id -> (preposición ante el nombre, nombre de la norma, sigla para la jerarquía)
NOMBRES: dict[str, tuple[str, str, str]] = {
    "ley_1564_2012": ("del", "Código General del Proceso (Ley 1564 de 2012)", "CGP"),
    "codigo_civil": ("del", "Código Civil (Ley 57 de 1887)", "C.C."),
    "codigo_comercio": ("del", "Código de Comercio (Decreto 410 de 1971)", "C.Co."),
    "codigo_penal": ("del", "Código Penal (Ley 599 de 2000)", "C.P."),
    "codigo_procedimiento_penal": ("del", "Código de Procedimiento Penal (Ley 906 de 2004)",
                                   "C.P.P."),
    "cpaca": ("del", "Código de Procedimiento Administrativo y de lo Contencioso "
                     "Administrativo (Ley 1437 de 2011)", "CPACA"),
    "decision_andina_486": ("de la", "Decisión 486 de la Comisión de la Comunidad Andina "
                                     "(Régimen Común sobre Propiedad Industrial)", "Decisión 486"),
    "decreto_2591_1991": ("del", "Decreto 2591 de 1991 (acción de tutela)", "Decreto 2591"),
    "ley_1996_2019": ("de la", "Ley 1996 de 2019 (capacidad legal de las personas con "
                               "discapacidad)", "Ley 1996"),
    "ley_80_1993": ("de la", "Ley 80 de 1993 (Estatuto General de Contratación de la "
                             "Administración Pública)", "Ley 80"),
}

_TIPOS = {"ley": ("de la", "Ley"), "decreto": ("del", "Decreto"),
          "acto_legislativo": ("del", "Acto Legislativo"), "resolucion": ("de la", "Resolución")}


def nombre_norma(meta: dict) -> tuple[str, str, str]:
    """(preposición, nombre, sigla). Si el documento no está en NOMBRES se arma del manifest."""
    doc_id = meta.get("doc_id", "")
    if doc_id in NOMBRES:
        return NOMBRES[doc_id]
    tipo, numero, anio = meta.get("tipo_norma"), meta.get("numero"), meta.get("anio")
    if tipo == "sentencia":
        nombre = f"Sentencia {numero} de {anio}"
        return "de la", nombre, nombre
    prep, etiqueta = _TIPOS.get(tipo, ("de la", "Ley"))
    nombre = f"{etiqueta} {numero} de {anio}" if numero and anio else meta.get("titulo", doc_id)
    return prep, nombre, nombre


def cuerpo_canonico(meta: dict) -> tuple | None:
    """Tupla (cuerpo, número, año) con la que el evaluador identifica la norma."""
    if meta.get("canonico"):
        return tuple(meta["canonico"])
    cuerpos = citations.bodies(citations.extract(nombre_norma(meta)[1]))
    # Preferir el alias de código (p. ej. codigo_general_proceso) sobre ("ley", n, a).
    return min(cuerpos, key=lambda c: (c[1] is not None, c)) if cuerpos else None


def norma_id(meta: dict, articulo: str | None) -> str:
    """ID canónico derivado de la tupla del evaluador: codigo_general_proceso#art_391,
    ley_1996_2019#art_5, jurisprudencia_C-355_2006."""
    cuerpo = cuerpo_canonico(meta)
    base = "_".join(str(p) for p in cuerpo if p) if cuerpo else meta.get("doc_id", "")
    return f"{base}#art_{articulo}" if articulo else base


def encabezado_articulo(meta: dict, articulo: str, titulo: str, jerarquia: str,
                        parte: tuple[int, int] | None = None) -> str:
    prep, nombre, _ = nombre_norma(meta)
    etiqueta = f"Artículo {articulo}" if not articulo.startswith("T") else \
        f"Artículo transitorio {articulo[1:]}"
    linea = f"{etiqueta} {prep} {nombre}."
    if jerarquia:
        linea += f" {jerarquia}."
    if titulo:
        linea += f" {titulo.rstrip('.')}."
    if parte and parte[1] > 1:
        linea += f" (parte {parte[0]}/{parte[1]})"
    return linea


def encabezado_documento(meta: dict, seccion: str = "", parte: tuple[int, int] | None = None) -> str:
    """Para fragmentos que no son artículos: preámbulo de una norma o sentencias."""
    _, nombre, _ = nombre_norma(meta)
    linea = f"{nombre}."
    if seccion:
        linea += f" {seccion}."
    if parte and parte[1] > 1:
        linea += f" (parte {parte[0]}/{parte[1]})"
    return linea
