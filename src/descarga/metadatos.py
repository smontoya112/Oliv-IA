"""Metadatos automáticos: convierte una lista de links en objetivos de descarga y
completa lo que falte (título, tipo, número, año, áreas...) leyendo el documento.

data/enlaces.txt: un link por línea. Las líneas vacías y las que empiezan con # se ignoran.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from urllib.parse import unquote, urlsplit

FUENTES_POR_HOST = {
    "secretariasenado.gov.co": "Secretaría General del Senado",
    "corteconstitucional.gov.co": "Relatoría de la Corte Constitucional",
    "suin-juriscol.gov.co": "SUIN-Juriscol",
    "funcionpublica.gov.co": "Función Pública (Gestor Normativo)",
    "comunidadandina.org": "Comunidad Andina",
    "cortesuprema.gov.co": "Corte Suprema de Justicia",
    "consejodeestado.gov.co": "Consejo de Estado",
    "dian.gov.co": "DIAN",
}
ORGANO_POR_TIPO = {
    "ley": "Congreso de la República",
    "acto_legislativo": "Congreso de la República",
    "sentencia": "Corte Constitucional",
}
# Palabras clave por área, para clasificar cuando el link no dice el área.
AREAS_CLAVE = {
    "constitucional": ["constituci", "tutela", "derechos fundamentales", "inexequible"],
    "administrativo": ["administrativ", "contratación estatal", "contencioso", "función pública",
                       "servidores públicos", "entidades estatales"],
    "penal": ["penal", "delito", "punible", "pena "],
    "procesal": ["procesal", "procedimiento", "proceso ", "demanda", "juez"],
    "comercial": ["comercio", "mercantil", "sociedad", "insolvencia", "concurso", "títulos valores"],
    "civil": ["civil", "obligaciones", "propiedad", "herencia", "sucesion", "sucesión"],
    "familia": ["familia", "infancia", "adolescen", "matrimonio", "alimentos", "divorcio"],
    "tributario": ["tributari", "impuesto", "renta", "iva", "dian"],
    "laboral": ["trabajo", "laboral", "trabajador", "pensi", "seguridad social", "sindical"],
    "mercados": ["consumidor", "competencia", "datos personales", "propiedad industrial",
                 "propiedad intelectual", "derechos de autor", "valores", "financier"],
}
SIN_AREA = "sin_clasificar"

_EXT = re.compile(r"\.(html?|pdf|php|aspx?|jsp)$", re.I)
_NORMA_URL = re.compile(r"^(ley|decreto|acto_legislativo|decreto_ley|resolucion)_0*(\d+)_(\d{4})$", re.I)
_SENTENCIA_URL = re.compile(r"^(C|T|SU|A)-?0*(\d+)-(\d{2})$", re.I)
_DECISION_URL = re.compile(r"^DEC0*(\d+)$", re.I)
_ANIO_FINAL = re.compile(r"_(1[89]\d\d|20\d\d)$")
_TITULO_NORMA = re.compile(
    r"\b(Ley|Decreto|Acto Legislativo|Sentencia|Resoluci[óo]n)\s+([A-Z]{0,2}-?\d+[A-Z]?)\s+de(?:l)?\s+(\d{4})",
    re.I)
_TITULO_MALO = re.compile(r"^[A-Za-z0-9_\-. ]{0,12}$|^[a-z0-9_]+$", re.I)
_ENCABEZADO_NORMA = re.compile(r"^(LEY|DECRETO|ACTO LEGISLATIVO|RESOLUCI[ÓO]N|C[ÓO]DIGO)\b", re.I)


def _sin_tildes(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", _sin_tildes(s).lower()).strip("_") or "doc"


def leer_enlaces(ruta: Path) -> list[str]:
    urls = []
    for linea in ruta.read_text(encoding="utf-8-sig").splitlines():
        linea = linea.split(" #")[0].strip()      # permite comentarios al final de la línea
        if not linea or linea.startswith("#"):
            continue
        if not re.match(r"https?://", linea, re.I):
            raise ValueError(f"{ruta.name}: '{linea}' no es un link http(s)")
        urls.append(linea)
    return list(dict.fromkeys(urls))


def fuente_de(url: str) -> str:
    host = urlsplit(url).netloc.lower().removeprefix("www.")
    for dominio, nombre in FUENTES_POR_HOST.items():
        if host == dominio or host.endswith("." + dominio):
            return nombre
    return host


def objetivo_desde_url(url: str) -> dict:
    """Deduce todo lo posible solo con la URL. Lo que falte se completa al leer el documento."""
    partes = urlsplit(url)
    nombre = _EXT.sub("", unquote(Path(partes.path).name)) or partes.netloc
    obj = {"url": url, "fuente": fuente_de(url), "auto": True}

    if m := _NORMA_URL.match(nombre):
        tipo, numero, anio = m.group(1).lower(), str(int(m.group(2))), int(m.group(3))
        obj.update(doc_id=f"{tipo}_{numero}_{anio}", tipo_norma=tipo, numero=numero, anio=anio,
                   canonico=[tipo, numero, str(anio)],
                   titulo_provisional=f"{tipo.replace('_', ' ').capitalize()} {numero} de {anio}")
        if tipo in ORGANO_POR_TIPO:
            obj["organo_emisor"] = ORGANO_POR_TIPO[tipo]
    elif ("corteconstitucional.gov.co" in partes.netloc) and (m := _SENTENCIA_URL.match(nombre)):
        tipo, numero = m.group(1).upper(), int(m.group(2))
        anio = re.search(r"/relatoria/(\d{4})/", partes.path)
        anio = int(anio.group(1)) if anio else (2000 + int(m.group(3)) if int(m.group(3)) < 50
                                               else 1900 + int(m.group(3)))
        obj.update(doc_id=f"sentencia_{tipo.lower()}-{numero}_{anio}", tipo_norma="sentencia",
                   numero=f"{tipo}-{numero}", anio=anio, organo_emisor="Corte Constitucional",
                   canonico=["jurisprudencia", f"{tipo}-{numero}", str(anio)],
                   titulo_provisional=f"Sentencia {tipo}-{numero:03d} de {anio}", seguir_paginas=False)
    elif m := _DECISION_URL.match(nombre):
        obj.update(doc_id=f"decision_andina_{int(m.group(1))}", tipo_norma="decision",
                   numero=str(int(m.group(1))))
    else:
        obj["doc_id"] = _slug(nombre)
        stem = _slug(nombre)
        if stem.startswith("codigo"):
            obj["tipo_norma"] = "codigo"
        elif stem.startswith("constitucion"):
            obj["tipo_norma"] = "constitucion"
        if m := _ANIO_FINAL.search(stem):
            obj["anio"] = int(m.group(1))
    return obj


def hacer_ids_unicos(objetivos: list[dict], ocupados: set[str]) -> None:
    for o in objetivos:
        base, i = o["doc_id"], 2
        while o["doc_id"] in ocupados:
            o["doc_id"] = f"{base}-{i}"
            i += 1
        ocupados.add(o["doc_id"])


# ------------------------------------------------------------ completar al leer
def detectar_titulo(titulo_html: str | None, cuerpo: str) -> str | None:
    """Prefiere el <title> si es legible; si no (p. ej. 'LEY_1564_2012'), usa el encabezado."""
    if titulo_html:
        t = " ".join(titulo_html.split())
        if len(t) > 12 and " " in t and not _TITULO_MALO.match(t):
            return t[:250]
    lineas = [re.sub(r"^#+\s*", "", l).strip() for l in cuerpo.splitlines()
              if l.strip() and not l.startswith("<!--")]
    if not lineas:
        return None
    primera = lineas[0]
    if _ENCABEZADO_NORMA.match(primera):
        for l in lineas[1:6]:
            if l.lower().startswith("por "):
                return f"{primera} - {l}"[:250]
    return primera[:250]


def clasificar_areas(titulo: str | None, cuerpo: str) -> list[str]:
    titulo_n = _sin_tildes((titulo or "").lower())
    inicio_n = _sin_tildes(cuerpo[:6000].lower())
    puntajes = {}
    for area, claves in AREAS_CLAVE.items():
        p = 0
        for c in claves:
            c = _sin_tildes(c)
            p += 5 * (c in titulo_n) + min(inicio_n.count(c), 3)
        if p:
            puntajes[area] = p
    ordenadas = sorted(puntajes, key=lambda a: -puntajes[a])
    return ordenadas[:3] or [SIN_AREA]


def completar(obj: dict, titulo_html: str | None, cuerpo: str) -> list[str]:
    """Rellena en `obj` los campos que falten. Devuelve la lista de campos deducidos."""
    puestos = []

    def poner(campo, valor):
        if valor and not obj.get(campo):
            obj[campo] = valor
            puestos.append(campo)

    # Preferimos el título leído del documento; el deducido de la URL es solo respaldo.
    poner("titulo", detectar_titulo(titulo_html, cuerpo) or obj.get("titulo_provisional") or obj["doc_id"])
    if m := _TITULO_NORMA.search(obj["titulo"]):
        tipo = _sin_tildes(m.group(1).lower()).replace(" ", "_")
        poner("tipo_norma", tipo)
        poner("numero", m.group(2).upper())
        poner("anio", int(m.group(3)))
        if tipo in ("ley", "decreto"):
            poner("canonico", [tipo, str(int(m.group(2))), m.group(3)] if m.group(2).isdigit() else None)
        poner("organo_emisor", ORGANO_POR_TIPO.get(tipo))
    poner("fuente", fuente_de(obj["url"]))
    poner("areas", clasificar_areas(obj["titulo"], cuerpo))
    return puestos
