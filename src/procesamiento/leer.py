"""Lectura de data/md/<doc_id>.md y limpieza mínima del cuerpo.

El texto limpio que devuelve `leer` es el documento de referencia de los offsets
`inicio`/`fin` de cada fragmento; build.py lo guarda en data/processed/texto/.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_FRONT = re.compile(r"\A---\n(.*?)\n---\n", re.S)
_PARTE = re.compile(r"^<!-- parte (\S+) \| (\S+) -->$", re.M)
_TABLA = re.compile(r"^[|\s]+$")
_HASH_VACIO = re.compile(r"^#+\s*$")
_NEGRITA = re.compile(r"\*\*")
_CURSIVA = re.compile(r"(?<=\S)\*+|\*+(?=\S)")      # no toca viñetas "* item"
_FIN_ORACION = re.compile(r"[.:;!?)\]”\"}]$")
_INICIO_CONTINUACION = re.compile(r"^[a-záéíóúñü(,;]")
_COMENTARIO_PAGINA = re.compile(r"<!-- pagina \d+ -->")          # marcas de PyMuPDF
_ENCABEZADO_MD = re.compile(r"^#{1,6}\s+")                      # "### SENTENCIA" -> "SENTENCIA"
_SEPARADOR_TABLA = re.compile(r"\|?(?:\s*:?-{3,}:?\s*\|)+\s*:?-*:?\s*")   # "| --- | --- |"
# Notas de vigencia que el scraper no pasó a {{…}}: "<Parágrafo eliminado por…>".
_NOTA_ANGULAR = re.compile(r"<((?:Par[áa]grafo|Art[íi]culo|Inciso|Numeral|Literal|Aparte|NOTA|"
                           r"Ver|Texto|Expresi[óo]n|Cap[íi]tulo|T[íi]tulo)[^<>]{3,600})>")
_PUNTO_SUELTO = re.compile(r"^[.,;:]+\s*(?=ART[ÍI]CULO\b)")    # ".ARTÍCULO 2o." en el CPACA


@dataclass
class Documento:
    doc_id: str
    meta: dict
    texto: str                                           # cuerpo limpio
    partes: list[tuple[int, str]] = field(default_factory=list)   # (offset, url)

    def url_en(self, offset: int) -> str | None:
        """URL de la parte del sitio de origen que contiene el offset."""
        url = self.partes[0][1] if self.partes else self.meta.get("url")
        for ini, u in self.partes:
            if ini > offset:
                break
            url = u
        return url

    @property
    def formato(self) -> str:
        origen = self.meta.get("formato_origen") or []
        return "pdf" if any(str(f).startswith("pdf") for f in origen) else "html"


def limpiar_control(texto: str) -> str:
    """Quita caracteres de control y de formato Unicode, salvo salto de línea y tabulación."""
    texto = unicodedata.normalize("NFC", texto).replace("\xa0", " ").replace("\r", "")
    return "".join(c for c in texto
                   if c in "\n\t" or unicodedata.category(c) not in ("Cc", "Cf"))


def reunir_parrafos(texto: str) -> str:
    """Une las líneas partidas a mitad de oración (texto extraído de PDF).

    Une solo cuando la línea no cierra oración y la siguiente empieza en minúscula;
    si empieza en dígito no se une, porque sería un numeral.
    """
    salida: list[str] = []
    for linea in texto.split("\n"):
        if (salida and salida[-1] and linea
                and not _FIN_ORACION.search(salida[-1])
                and _INICIO_CONTINUACION.match(linea)):
            salida[-1] = salida[-1] + " " + linea
        else:
            salida.append(linea)
    return "\n".join(salida)


def limpiar(texto: str, unir_lineas: bool = False) -> str:
    """Limpieza mínima e idempotente. No quita tildes, números, °, § ni guiones."""
    texto = limpiar_control(texto)
    lineas = []
    for linea in texto.split("\n"):
        linea = re.sub(r"[ \t]+", " ", linea).strip()
        if _TABLA.fullmatch(linea) or _HASH_VACIO.fullmatch(linea):
            linea = ""
        linea = _CURSIVA.sub("", _NEGRITA.sub("", linea)).strip()
        if _COMENTARIO_PAGINA.fullmatch(linea):
            linea = ""
        linea = _PUNTO_SUELTO.sub("", _ENCABEZADO_MD.sub("", linea))
        linea = _NOTA_ANGULAR.sub(lambda m: "{{" + m.group(1).strip() + "}}", linea)
        if _SEPARADOR_TABLA.fullmatch(linea):
            linea = ""
        elif linea.startswith("|") and linea.endswith("|"):
            linea = linea.strip("| ")          # fila de tabla: se conservan las celdas
        lineas.append(linea)
    texto = "\n".join(lineas)
    if unir_lineas:
        texto = reunir_parrafos(texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip()


def leer(ruta: Path) -> Documento:
    crudo = ruta.read_text(encoding="utf-8")
    meta, cuerpo = {}, crudo
    if m := _FRONT.match(crudo):
        meta = yaml.safe_load(m.group(1)) or {}
        cuerpo = crudo[m.end():]
    doc_id = meta.get("doc_id") or ruta.stem
    unir = meta.get("tipo_norma") == "sentencia" or any(
        str(f).startswith("pdf") for f in meta.get("formato_origen") or [])

    # Cada parte se limpia por separado para conservar su URL de origen.
    trozos: list[tuple[str | None, str]] = []
    ultimo, url = 0, None
    for m in _PARTE.finditer(cuerpo):
        trozos.append((url, cuerpo[ultimo:m.start()]))
        url, ultimo = m.group(2), m.end()
    trozos.append((url, cuerpo[ultimo:]))

    texto, partes = "", []
    for url, trozo in trozos:
        limpio = limpiar(trozo, unir_lineas=unir)
        if not limpio:
            continue
        if texto:
            texto += "\n\n"
        partes.append((len(texto), url or meta.get("url")))
        texto += limpio
    return Documento(doc_id=doc_id, meta=meta, texto=texto, partes=partes)
