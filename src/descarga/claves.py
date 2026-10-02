"""Identidad de un documento normativo, independiente de la URL con que se llegó a él.

La misma norma aparece con rutas distintas: Senado `basedoc/ley_0599_2000.html`, el esquema
antiguo `basedoc/ley/2000/ley_0599_2000_pr012.html` o el normograma de la DIAN
`.../docs/ley_0599_2000.htm`; con o sin `www`, con `http` o `https`, con ceros a la izquierda.
Comparar URLs literales las trata como documentos distintos y el corpus se llena de copias. Aquí
todas esas formas se reducen a una clave (`ley_599_2000`, `sentencia_C-355_2006`, ...) con el mismo
formato que los ids canónicos de la fase 4.
"""
from __future__ import annotations

import re
from urllib.parse import unquote, urlsplit

_NORMA = re.compile(
    r"^(ley|decreto|acto_legislativo|decreto_ley|resolucion|circular|acuerdo)_0*(\d+)_(\d{4})$", re.I)
_SENTENCIA = re.compile(r"^(C|T|SU|A)-?0*(\d+)-(\d{2})$", re.I)
_EXT = re.compile(r"\.(html?|pdf|php|aspx?|jsp)$", re.I)
_PARTE = re.compile(r"_pr\d{3}$", re.I)


def clave_url(url: str) -> str:
    """Clave de la norma a la que apunta una URL (ignora host, ruta, esquema, fragmento y _prNNN)."""
    p = urlsplit((url or "").strip())
    host = p.netloc.lower().removeprefix("www.")
    nombre = _PARTE.sub("", _EXT.sub("", unquote(p.path.rsplit("/", 1)[-1])))
    if m := _NORMA.match(nombre):
        return f"{m.group(1).lower()}_{int(m.group(2))}_{m.group(3)}"
    if "corteconstitucional" in host and (m := _SENTENCIA.match(nombre)):
        anio = re.search(r"/relatoria/(\d{4})/", p.path)
        yy = int(m.group(3))
        anio = anio.group(1) if anio else str((2000 if yy < 50 else 1900) + yy)
        return f"sentencia_{m.group(1).upper()}-{int(m.group(2))}_{anio}"
    ruta = _PARTE.sub("", _EXT.sub("", p.path.lower()))
    return f"{host}{ruta}" + (f"?{p.query.lower()}" if p.query else "")


def clave_canonico(canonico) -> str | None:
    """Clave de la tupla `canonico` del manifest (["ley","80","1993"], ["codigo_civil",None,None]...)."""
    if not canonico:
        return None
    cuerpo, numero, anio = (list(canonico) + [None, None, None])[:3]
    if cuerpo == "jurisprudencia" and numero and anio:
        return f"sentencia_{numero}_{anio}"
    if numero and anio:
        num = str(int(numero)) if str(numero).isdigit() else str(numero)
        return f"{cuerpo}_{num}_{anio}"
    try:                      # códigos por nombre: codigo_civil -> ley_84_1873 (diccionario de alias de la fase 4)
        import normalizacion
        norma = normalizacion.slug_to_norma(cuerpo)
        if norma:
            return f"{norma[0]}_{int(norma[1])}_{norma[2]}"
    except Exception:         # sin pyyaml o sin scripts/: se queda el nombre
        pass
    return str(cuerpo)


def claves_objetivo(obj: dict) -> set[str]:
    """Claves de un objetivo de descarga (antes de bajarlo)."""
    claves = {clave_url(obj["url"]), *(clave_url(u) for u in obj.get("urls_alternativas") or [])}
    if c := clave_canonico(obj.get("canonico")):
        claves.add(c)
    return claves


def claves_registro(reg: dict) -> set[str]:
    """Claves de un registro del manifest (descargado o fallido)."""
    claves = {clave_url(u) for u in [reg.get("url"), *(reg.get("urls_partes") or [])] if u}
    if c := clave_canonico(reg.get("canonico")):
        claves.add(c)
    return claves


def prefiere(url: str) -> tuple:
    """Orden de preferencia entre URLs de la misma norma: primero el Senado (texto más limpio)."""
    return (0 if "secretariasenado.gov.co" in url.lower() else 1, len(url))
