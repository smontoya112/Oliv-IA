"""Conversión de HTML y PDF a Markdown limpio, conservando el texto normativo
intacto (tildes, números, símbolos, mayúsculas)."""
from __future__ import annotations

import io
import logging
import re
import shutil
import struct
import subprocess
import zipfile
import xml.etree.ElementTree as ET
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin

import charset_normalizer
import ftfy
from bs4 import BeautifulSoup, Comment
from markdownify import markdownify

log = logging.getLogger(__name__)

# ---------------------------------------------------------------- codificación
_CHARSET_HTTP = re.compile(r"charset=([\w\-]+)", re.I)
_CHARSET_META = re.compile(rb"<meta[^>]+charset=[\"']?\s*([a-zA-Z0-9_\-]+)", re.I)
# windows-1252 es superconjunto de latin-1 y es lo que realmente usan muchos sitios .gov.co
_EQUIVALENTES = {"iso-8859-1": "cp1252", "latin-1": "cp1252", "latin1": "cp1252",
                 "us-ascii": "cp1252", "ascii": "cp1252", "windows-1252": "cp1252"}
_MOJIBAKE = re.compile(r"[ÃÂ].")   # ftfy decide con cuidado si de verdad hay mojibake


def decodificar(contenido: bytes, content_type: str | None = None) -> tuple[str, str]:
    """Devuelve (texto, codificación usada)."""
    candidatas = []
    if content_type and (m := _CHARSET_HTTP.search(content_type)):
        candidatas.append(m.group(1))
    if m := _CHARSET_META.search(contenido[:4096]):
        candidatas.append(m.group(1).decode("ascii", "ignore"))
    for enc in candidatas:
        enc = _EQUIVALENTES.get(enc.lower(), enc.lower())
        try:
            return _reparar(contenido.decode(enc)), enc
        except (LookupError, UnicodeDecodeError):
            continue
    mejor = charset_normalizer.from_bytes(contenido).best()
    if mejor is not None:
        return _reparar(str(mejor)), mejor.encoding
    return contenido.decode("utf-8", errors="replace"), "utf-8(replace)"


def _reparar(texto: str) -> str:
    if _MOJIBAKE.search(texto):
        texto = ftfy.fix_encoding(texto)
    return texto


# ------------------------------------------------------------------- HTML → MD
_NAVEGACION = {"siguiente", "anterior", "imprimir", "ir al inicio", "inicio", "volver", "arriba"}
_NOTA_EDITORIAL = re.compile(r"<([^<>]{3,1000})>")
_ARTICULO_NUMERADO = re.compile(r"ART[ÍI]CULO[ \t]+\d", re.I)
_LINEA_INDICE = re.compile(r"\d+[A-Z]?(-\d+)?")
_ACTUALIZACION = re.compile(r"Última actualización:\s*([^\n(]+)", re.I)
_BOILERPLATE = [
    re.compile(r"^\s*Última actualización:.*$", re.I | re.M),
    re.compile(r"^\s*Derechos de autor reservados.*$", re.I | re.M),
]
_CORTE_PIE = re.compile(r"^\s*Disposiciones analizadas por Avance Jur[íi]dico", re.I | re.M)


@dataclass
class ResultadoHTML:
    markdown: str
    notas: list[str] = field(default_factory=list)       # contenido oculto (notas de vigencia, etc.)
    enlaces: list[str] = field(default_factory=list)     # enlaces salientes, para descubrir fuentes
    siguiente: str | None = None                         # paginación tipo "Siguiente"
    fecha_actualizacion_fuente: str | None = None
    titulo: str | None = None                            # contenido de <title>


def _es_oculto(tag) -> bool:
    if not getattr(tag, "attrs", None):
        return False
    estilo = tag.get("style", "").replace(" ", "").lower()
    return "display:none" in estilo or "visibility:hidden" in estilo or tag.has_attr("hidden")


def _es_indice(el) -> bool:
    """Detecta bloques tipo índice: muchas líneas cortas, mayoría números de artículo."""
    texto = el.get_text("\n", strip=True)
    if _ARTICULO_NUMERADO.search(texto):
        return False
    lineas = [l.strip() for l in texto.split("\n") if l.strip()]
    if len(lineas) < 30:
        return False
    cortas = sum(len(l) <= 40 for l in lineas)
    numericas = sum(bool(_LINEA_INDICE.fullmatch(l)) for l in lineas)
    return cortas / len(lineas) > 0.9 and numericas / len(lineas) > 0.4


def html_a_markdown(html: str, url: str) -> ResultadoHTML:
    soup = BeautifulSoup(html, "lxml")
    res = ResultadoHTML(markdown="")

    if soup.title and soup.title.string:
        res.titulo = " ".join(soup.title.string.split())
    texto_plano = soup.get_text("\n")
    if m := _ACTUALIZACION.search(texto_plano):
        res.fecha_actualizacion_fuente = m.group(1).strip(" -")

    # 1. Paginación, antes de borrar enlaces.
    for a in soup.find_all("a", href=True):
        if a.get_text(" ", strip=True).lower() == "siguiente":
            res.siguiente = urljoin(url, a["href"])
            break

    # 2. Elementos que nunca son contenido.
    for c in soup.find_all(string=lambda s: isinstance(s, Comment)):
        c.extract()
    for tag in soup(["title", "script", "style", "noscript", "iframe", "form", "img", "button",
                     "nav", "header", "footer", "select", "input", "link", "meta", "svg"]):
        tag.decompose()

    # 3. Contenido oculto (notas desplegables): se guarda aparte, fuera del texto normativo.
    for el in soup.find_all(_es_oculto):
        if el.decomposed:
            continue
        if t := el.get_text("\n", strip=True):
            res.notas.append(t)
        el.decompose()

    # 4. Enlaces: se registran y se reemplazan por su texto.
    for a in soup.find_all("a"):
        if a.decomposed:
            continue
        href = (a.get("href") or "").strip()
        texto = a.get_text(" ", strip=True)
        if href.lower().startswith("javascript:") or texto.lower() in _NAVEGACION or not texto:
            a.decompose()
            continue
        if href and not href.startswith("#"):
            res.enlaces.append(urljoin(url, href))
        a.unwrap()

    # 5. Índices laterales (listas de números de artículo).
    for el in soup.find_all(["div", "table", "ul", "ol", "td", "span", "p"]):
        if not el.decomposed and _es_indice(el):
            el.decompose()

    # 6. Texto tachado (partes declaradas INEXEQUIBLES): se marca con ~~ ~~.
    for el in soup.find_all(["strike", "s", "del"]) + soup.find_all(
            style=re.compile(r"line-through", re.I)):
        if el.decomposed:
            continue
        el.insert_before("~~")
        el.insert_after("~~")
        el.unwrap()

    # 7. Notas editoriales "<Inciso modificado por…>" → "{{…}}" para que Markdown
    #    no las trate como etiquetas HTML y la fase 3 pueda extraerlas.
    soup.smooth()
    for s in soup.find_all(string=True):
        if "<" in s:
            s.replace_with(_NOTA_EDITORIAL.sub(lambda m: "{{" + " ".join(m.group(1).split()) + "}}", s))

    md = markdownify(str(soup), heading_style="ATX", escape_asterisks=False,
                     escape_underscores=False, escape_misc=False)
    res.markdown = _normalizar_md(md)
    return res


def _normalizar_md(md: str) -> str:
    md = unicodedata.normalize("NFC", md).replace("\xa0", " ")
    if m := _CORTE_PIE.search(md):
        md = md[: m.start()]
    for patron in _BOILERPLATE:
        md = patron.sub("", md)
    md = re.sub(r"[ \t]+", " ", md)
    md = re.sub(r" *\n *", "\n", md)
    md = md.replace("~~~~", "")
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip() + "\n"


# ------------------------------------------------------------ formato del archivo
def detectar_formato(contenido: bytes, content_type: str | None = None) -> str:
    """pdf | docx | doc | html, mirando los primeros bytes (el Content-Type y la extensión
    mienten: la Corte Suprema sirve .doc y .docx desde enlaces que parecen páginas web)."""
    if contenido[:5] == b"%PDF-" or ("pdf" in (content_type or "").lower() and b"%PDF-" in contenido[:1024]):
        return "pdf"
    if contenido[:4] == b"PK\x03\x04":
        try:
            with zipfile.ZipFile(io.BytesIO(contenido)) as z:
                if "word/document.xml" in z.namelist():
                    return "docx"
        except zipfile.BadZipFile:
            pass
    if contenido[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":     # contenedor OLE2 (.doc)
        return "doc"
    return "html"


# ------------------------------------------------------------ Word (.docx / .doc)
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _parrafos_docx(xml: bytes) -> list[str]:
    salida = []
    for p in ET.fromstring(xml).iter(_W + "p"):
        partes = []
        for el in p.iter():
            if el.tag == _W + "t":
                partes.append(el.text or "")
            elif el.tag == _W + "tab":
                partes.append("\t")
            elif el.tag in (_W + "br", _W + "cr"):
                partes.append("\n")
        salida.append("".join(partes))
    return salida


def docx_a_markdown(ruta: Path) -> "ResultadoPDF":
    """Texto de un .docx leyendo el XML directamente (sin dependencias)."""
    parrafos = []
    with zipfile.ZipFile(ruta) as z:
        for nombre in ("word/document.xml", "word/footnotes.xml", "word/endnotes.xml"):
            if nombre in z.namelist():
                parrafos += _parrafos_docx(z.read(nombre))
    return ResultadoPDF(_normalizar_md("\n\n".join(p for p in parrafos if p.strip())), "docx", 1)


def _texto_doc_olefile(ruta: Path) -> str:
    """Extrae el texto de un .doc binario (Word 97-2003) recorriendo la tabla de piezas."""
    import olefile
    with olefile.OleFileIO(str(ruta)) as ole:
        wd = ole.openstream("WordDocument").read()
        tabla = ole.openstream("1Table" if struct.unpack_from("<H", wd, 0x0A)[0] & 0x0200
                               else "0Table").read()
    fc_clx, lcb_clx = struct.unpack_from("<II", wd, 0x01A2)
    clx = tabla[fc_clx: fc_clx + lcb_clx]
    i = 0
    while clx[i] == 0x01:                                # bloques Prc: se saltan
        i += 3 + struct.unpack_from("<H", clx, i + 1)[0]
    if clx[i] != 0x02:
        raise ValueError("estructura .doc no reconocida")
    lcb = struct.unpack_from("<I", clx, i + 1)[0]
    plc = clx[i + 5: i + 5 + lcb]
    n = (lcb - 4) // 12
    cps = struct.unpack_from(f"<{n + 1}I", plc, 0)
    trozos = []
    for k in range(n):
        fc = struct.unpack_from("<I", plc, 4 * (n + 1) + 8 * k + 2)[0]
        largo = cps[k + 1] - cps[k]
        if fc & 0x40000000:                              # texto comprimido: cp1252
            ini = (fc & ~0x40000000) // 2
            trozos.append(wd[ini: ini + largo].decode("cp1252", "replace"))
        else:                                            # UTF-16 LE
            trozos.append(wd[fc: fc + 2 * largo].decode("utf-16-le", "replace"))
    return "".join(trozos)


def doc_a_markdown(ruta: Path) -> "ResultadoPDF":
    """.doc: primero herramientas externas si existen (mejor fidelidad), si no, el lector propio."""
    texto = None
    if exe := shutil.which("antiword"):
        r = subprocess.run([exe, "-m", "UTF-8.txt", str(ruta)], capture_output=True)
        if r.returncode == 0 and r.stdout.strip():
            texto = r.stdout.decode("utf-8", "replace")
    if texto is None:
        texto = _texto_doc_olefile(ruta)
    texto = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", texto.replace("\r", "\n").replace("\x07", " "))
    return ResultadoPDF(_normalizar_md(texto), "doc", 1)


# -------------------------------------------------------------------- PDF → MD
@dataclass
class ResultadoPDF:
    markdown: str
    metodo: str        # pdf_texto | pdf_ocr | pdf_sin_texto | pdf_texto_ilegible | docx | doc
    paginas: int


_NUMERO_PAGINA = re.compile(r"(p[áa]g(ina)?\.?\s*)?[-–]?\s*\d{1,4}\s*((de|/)\s*\d{1,4})?\s*[-–]?", re.I)


def _quitar_encabezados(paginas: list[str]) -> list[str]:
    """Elimina números de página y encabezados/pies que se repiten idénticos en las dos
    primeras o dos últimas líneas de más de la mitad de las páginas."""
    def es_numero_pagina(l: str) -> bool:
        return bool(_NUMERO_PAGINA.fullmatch(l.strip()))

    conteo = Counter()
    if len(paginas) >= 4:
        for p in paginas:
            lineas = [l.strip() for l in p.splitlines() if l.strip()]
            if len(lineas) >= 6:
                conteo.update({l for l in lineas[:2] + lineas[-2:]
                               if len(l) <= 80 and not _ARTICULO_NUMERADO.match(l)})
    repetidas = {l for l, n in conteo.items() if n > len(paginas) / 2}
    return ["\n".join(l for l in p.splitlines()
                      if l.strip() not in repetidas and not es_numero_pagina(l))
            for p in paginas]


def _texto_pdf(ruta: Path) -> list[str]:
    try:
        import pymupdf
    except ImportError:          # versiones antiguas de PyMuPDF
        import fitz as pymupdf
    with pymupdf.open(ruta) as doc:
        return [p.get_text("text") for p in doc]


def _capa_ilegible(paginas: list[str]) -> bool:
    """Escaneos con un OCR malo incrustado: el texto existe pero está lleno de caracteres
    que no son del español (ideogramas, anchos completos...). >2 % es basura."""
    texto = "".join(paginas)
    raros = sum(1 for c in texto if ord(c) > 0x24F and not 0x2000 <= ord(c) <= 0x206F)
    return len(texto.strip()) > 0 and raros / len(texto) > 0.02


def pdf_a_markdown(ruta: Path, idioma_ocr: str = "spa") -> ResultadoPDF:
    paginas = _texto_pdf(ruta)
    promedio = sum(len(p.strip()) for p in paginas) / max(len(paginas), 1)
    metodo = "pdf_texto"
    sin_texto, ilegible = promedio < 100, _capa_ilegible(paginas)
    if sin_texto or ilegible:                 # escaneado, o con una capa de texto inservible
        if shutil.which("ocrmypdf"):
            salida = ruta.with_suffix(".ocr.pdf")
            if not salida.exists():
                log.info("OCR de %s (puede tardar varios minutos)", ruta.name)
                # --force-ocr rehace también las páginas que ya traen (mala) capa de texto
                subprocess.run(["ocrmypdf", "-l", idioma_ocr,
                                "--force-ocr" if ilegible else "--skip-text", "--quiet",
                                str(ruta), str(salida)], check=True)
            paginas = _texto_pdf(salida)
            metodo = "pdf_ocr"
        else:
            log.warning("%s necesita OCR y no está instalado ocrmypdf (con tesseract-ocr-spa)",
                        ruta.name)
            metodo = "pdf_sin_texto" if sin_texto else "pdf_texto_ilegible"

    paginas = _quitar_encabezados(paginas)
    bloques = []
    for i, p in enumerate(paginas, start=1):
        p = re.sub(r"([a-záéíóúñ])-\n([a-záéíóúñ])", r"\1\2", p)        # palabras cortadas
        p = re.sub(r"(?<=[^.:;\n])\n(?=[a-záéíóúñ])", " ", p)             # líneas partidas
        bloques.append(f"<!-- pagina {i} -->\n{p.strip()}")
    return ResultadoPDF(_normalizar_md("\n\n".join(bloques)), metodo, len(paginas))
