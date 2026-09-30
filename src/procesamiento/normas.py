"""Segmentación de normas en artículos, con su ruta jerárquica.

Se recorre el texto limpio bloque a bloque (párrafos separados por línea en blanco):
  - un encabezado de jerarquía (LIBRO, TÍTULO, CAPÍTULO...) cierra el artículo en curso;
  - "ARTÍCULO N." en mayúsculas abre un artículo;
  - "Artículo N." / "ART. N" solo abren uno si N sigue la secuencia (guarda contra
    citas a otras normas que empiezan párrafo, p. ej. "Artículo 199." en el art. 612 del CGP);
  - todo lo demás (incisos, numerales, parágrafos, notas) queda dentro del artículo.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_NUM = (r"(?P<num>\d+(?:\s*-\s*(?:\d+|[A-ZÁÉÍÓÚÑ])(?![A-Za-zÁÉÍÓÚÑáéíóúñ]))?"
        r"(?:\s?[A-ZÁÉÍÓÚÑ](?![A-Za-zÁÉÍÓÚÑáéíóúñ]))?"
        r"(?:\s+(?:bis|BIS|ter|TER|quáter|QUÁTER|quater|QUATER)\b)?)"
        r"\s*(?:o|°|º)?\s*[.\-–:]")
ART_MAYUS = re.compile(r"^ART[ÍI]CULO\s+" + _NUM)
ART_ESPECIAL = re.compile(
    r"^ART[ÍI]CULO\s+(?P<esp>TRANSITORIO(?:\s+(?P<tn>\d+)o?)?|NUEVO|[ÚU]NICO)\s*[.\-–:]")
ART_MINUS = re.compile(r"^(?:Art[íi]culo|ART\.|Art\.)\s+" + _NUM)

# Ordinales admitidos tras LIBRO/TÍTULO/...: romanos, números u ordinales en letras.
_ORDINAL = (r"(?:[IVXLC]+|\d+[o°º]?|PRELIMINAR|FINAL|[ÚU]NIC[OA]|PRIMER[OA]?|SEGUND[OA]|"
            r"TERCER[OA]?|CUART[OA]|QUINT[OA]|SEXT[OA]|S[ÉE]PTIM[OA]|OCTAV[OA]|NOVEN[OA]|"
            r"D[ÉE]CIM[OA](?:\s+\w+)?|UND[ÉE]CIM[OA]|DUOD[ÉE]CIM[OA]|ADICIONAL|TRANSITORI[OA])")
JERARQUIA = re.compile(
    r"^(?P<nivel>PARTE|LIBRO|SECCI[ÓO]N|T[ÍI]TULO|CAP[ÍI]TULO)\s+(?P<ord>" + _ORDINAL + r")"
    r"\s*\.?(?:\s*[.\-–:]\s*(?P<nombre>[^a-záéíóúñ]{3,}?))?\.?$")
_SUBTITULO = re.compile(r"^(?P<n>\d+)\.\s+(?P<nombre>[A-ZÁÉÍÓÚÑ][^\n]{1,55})$")
# En el Código Civil "PARAGRAFO 2o." + nombre en mayúsculas agrupa artículos (nivel de
# jerarquía), a diferencia del parágrafo que va dentro de un artículo.
_PARAGRAFO_NIVEL = re.compile(r"^PAR[ÁA]GRAFO\s+(?P<ord>\d+[oº°]?|[ÚU]NICO)\.?$")
# Subtítulo sin número de los textos de PDF ("Del Trato Nacional"): corto, sin
# puntuación final y seguido de un artículo.
_SUBTITULO_LIBRE = re.compile(r"^[A-ZÁÉÍÓÚÑ][^\n.:;,]{2,88}$")
# Concordancias que el Senado agrega al final de algunos artículos ("Concepto
# SUPERINDUSTRIA 32214 de 2000", "2017:"). Son títulos de doctrina, no texto normativo.
_CONCORDANCIA = re.compile(r"^(?:(?:Concepto|Directriz|Oficio|Circular(?:\s+Externa)?|"
                           r"Instructivo|Resoluci[óo]n)\s+[A-ZÁÉÍÓÚÑ][\w.\-]*\s+[\d.\-]+\s+de\s+"
                           r"\d{4}(?:\s+Ficha:\s*\S+)?|\d{4}:)$")
_NUMERAL = re.compile(r"^(?P<n>\d+)\.\s")

# Orden de profundidad. SECCIÓN tiene tres posibles alturas; se decide mirando
# cuál es el siguiente encabezado estructural (ver _nivel_seccion).
NIVELES = ["PARTE", "LIBRO", "SECCION_A", "TITULO", "SECCION_M", "CAPITULO", "PARAGRAFO",
           "SECCION_B", "SUBTITULO"]
_ETIQUETA = {"PARTE": "Parte", "LIBRO": "Libro", "SECCION_A": "Sección", "TITULO": "Título",
             "SECCION_M": "Sección", "CAPITULO": "Capítulo", "PARAGRAFO": "Parágrafo",
             "SECCION_B": "Sección", "SUBTITULO": ""}


@dataclass
class Bloque:
    texto: str
    inicio: int
    fin: int


@dataclass
class Articulo:
    num: str                     # normalizado: "42", "397A", "42bis", "42-1", "T5"
    num_base: int | None
    sufijo: str
    titulo: str                  # epígrafe en mayúsculas, si lo tiene
    jerarquia: list[tuple[str, str, str]]    # (nivel, ordinal, nombre)
    bloques: list[Bloque] = field(default_factory=list)

    @property
    def inicio(self) -> int:
        return self.bloques[0].inicio

    @property
    def fin(self) -> int:
        return self.bloques[-1].fin


@dataclass
class Segmentacion:
    preambulo: list[Bloque]
    articulos: list[Articulo]
    huerfanos: list[Bloque]      # texto entre encabezados que no es nombre ni artículo
    rechazados: list[Bloque]     # "Artículo N." descartados por la guarda de secuencia
    concordancias: list[Bloque] = field(default_factory=list)   # doctrina citada, fuera


def _es_cabecera(linea: str) -> bool:
    return bool(ART_MAYUS.match(linea) or ART_ESPECIAL.match(linea) or ART_MINUS.match(linea)
                or JERARQUIA.match(linea))


def bloques(texto: str) -> list[Bloque]:
    """Párrafos separados por línea en blanco. En texto de PDF un artículo puede empezar
    en una línea sin blanco previo, así que también se corta antes de cada cabecera, y un
    encabezado de jerarquía ("TITULO I") queda siempre en su propio bloque."""
    salida = []
    for m in re.finditer(r"[^\n](?:.|\n(?!\n))*", texto):
        pos = m.start()
        ini, actual = pos, ""
        for linea in m.group(0).split("\n"):
            if actual and (_es_cabecera(linea) or JERARQUIA.match(actual.rsplit("\n", 1)[-1])):
                salida.append(Bloque(actual, ini, ini + len(actual)))
                ini, actual = pos, linea
            else:
                actual = f"{actual}\n{linea}" if actual else linea
            pos += len(linea) + 1
        salida.append(Bloque(actual, ini, ini + len(actual)))
    return salida


def normalizar_num(num: str) -> tuple[str, int | None, str]:
    """'42' -> ('42', 42, ''); '397 A' -> ('397A', 397, 'A'); '42 bis' -> ('42bis', 42, 'bis')."""
    limpio = re.sub(r"\s+", "", num)
    limpio = re.sub(r"(?i)(bis|ter|qu[áa]ter)$", lambda m: m.group(1).lower(), limpio)
    m = re.match(r"(\d+)(.*)", limpio)
    base, resto = int(m.group(1)), m.group(2)
    sufijo = resto.lstrip("-") if re.fullmatch(r"-?[A-Z]|bis|ter|qu[áa]ter", resto) else resto
    return limpio, base, sufijo


def _es_nombre(texto: str) -> bool:
    """Línea en mayúsculas que da nombre a un nivel ("JURISDICCIÓN Y COMPETENCIA.")."""
    letras = [c for c in texto if c.isalpha()]
    return (0 < len(texto) <= 250 and "\n" not in texto and letras
            and sum(c.isupper() for c in letras) / len(letras) > 0.8
            and not ART_MAYUS.match(texto) and not ART_ESPECIAL.match(texto)
            and not JERARQUIA.match(texto) and not _PARAGRAFO_NIVEL.match(texto))


def _titulo_articulo(resto: str) -> str:
    """Epígrafe tras el número: 'OBJETO. Este código…' -> 'OBJETO'; '{{DOMICILIO}}. El…' -> 'DOMICILIO'."""
    resto = resto.strip()
    if m := re.match(r"\{\{([^{}]{2,200})\}\}", resto):
        return m.group(1).strip(" .")
    if m := re.match(r"([^a-záéíóúñ{<]{3,250}?)\.(?:\s|$)", resto):
        cand = m.group(1).strip()
        letras = [c for c in cand if c.isalpha()]
        if letras and sum(c.isupper() for c in letras) / len(letras) > 0.8:
            return cand
    return ""


def _nivel_seccion(bls: list[Bloque], i: int) -> str:
    for b in bls[i + 1:]:
        if ART_MAYUS.match(b.texto) or ART_ESPECIAL.match(b.texto):
            return "SECCION_B"
        if m := JERARQUIA.match(b.texto):
            nivel = m.group("nivel").upper().replace("Í", "I").replace("Ó", "O")
            return {"TITULO": "SECCION_A", "CAPITULO": "SECCION_M"}.get(nivel, "SECCION_A")
    return "SECCION_B"


def _siguiente_es_articulo(bls: list[Bloque], i: int) -> bool:
    return i + 1 < len(bls) and _es_cabecera(bls[i + 1].texto) \
        and not JERARQUIA.match(bls[i + 1].texto)


def segmentar(texto: str, pdf: bool = False) -> Segmentacion:
    """pdf=True activa los subtítulos sin número, que en HTML serían riesgosos: un último
    inciso sin punto final se confundiría con un subtítulo."""
    bls = bloques(texto)
    pila: dict[str, tuple[str, str, str]] = {}
    seg = Segmentacion([], [], [], [])
    actual: Articulo | None = None
    esperando_nombre: str | None = None
    ultimo_numeral = 0
    n_transitorio = 0

    def abrir_nivel(nivel: str, ordinal: str, nombre: str) -> None:
        nonlocal actual, esperando_nombre
        prof = NIVELES.index(nivel)
        for n in NIVELES[prof:]:
            pila.pop(n, None)
        pila[nivel] = (nivel, ordinal, nombre)
        actual = None
        esperando_nombre = None if nombre else nivel

    def abrir_articulo(num: str, base: int | None, sufijo: str, b: Bloque, resto: str) -> None:
        nonlocal actual, esperando_nombre, ultimo_numeral
        actual = Articulo(num, base, sufijo, _titulo_articulo(resto),
                          [pila[n] for n in NIVELES if n in pila], [b])
        seg.articulos.append(actual)
        esperando_nombre = None
        ultimo_numeral = 0

    for i, b in enumerate(bls):
        t = b.texto
        if _CONCORDANCIA.match(t):
            seg.concordancias.append(b)
            continue
        if m := JERARQUIA.match(t):
            nivel = m.group("nivel").upper().replace("Í", "I").replace("Ó", "O")
            if nivel == "SECCION":
                nivel = _nivel_seccion(bls, i)
            abrir_nivel(nivel, m.group("ord").strip(), (m.group("nombre") or "").strip(" ."))
            continue
        if esperando_nombre and _es_nombre(t):
            niv, ordn, nombre = pila[esperando_nombre]
            pila[esperando_nombre] = (niv, ordn, (nombre + " " + t.strip(" .")).strip())
            continue
        if m := ART_ESPECIAL.match(t):
            esp = m.group("esp").upper()
            if esp.startswith("TRANSITORIO"):
                n_transitorio += 1
                num = f"T{m.group('tn') or n_transitorio}"
            else:
                num = esp.replace("Ú", "U")
            abrir_articulo(num, None, "", b, t[m.end():])
            continue
        if m := ART_MAYUS.match(t):
            num, base, sufijo = normalizar_num(m.group("num"))
            maximo = max((a.num_base or 0 for a in seg.articulos), default=0)
            if base < maximo - 20:
                # La numeración reinicia: es otra norma transcrita en una nota (p. ej.
                # la Ley 1a. de 1980 dentro del Código de Comercio). No es artículo de
                # este documento; queda registrada en rechazados.
                seg.rechazados.append(b)
                continue
            abrir_articulo(num, base, sufijo, b, t[m.end():])
            continue
        if m := ART_MINUS.match(t):
            num, base, sufijo = normalizar_num(m.group("num"))
            previa = next((a.num_base for a in reversed(seg.articulos) if a.num_base), None)
            en_secuencia = (base == 1 if previa is None
                            else previa < base <= previa + 5 or (base == previa and sufijo))
            if en_secuencia:
                abrir_articulo(num, base, sufijo, b, t[m.end():])
            else:
                seg.rechazados.append(b)
                if actual:
                    actual.bloques.append(b)
            continue
        # Subtítulo numerado ("1. Disposiciones Generales") justo antes de un artículo,
        # que no continúa los numerales del artículo en curso.
        if (m := _SUBTITULO.match(t)) and len(t) <= 60 and _siguiente_es_articulo(bls, i) \
                and (actual is None or int(m.group("n")) != ultimo_numeral + 1):
            abrir_nivel("SUBTITULO", m.group("n"), m.group("nombre").strip(" ."))
            continue
        if (m := _PARAGRAFO_NIVEL.match(t)) and i + 2 < len(bls) and _es_nombre(bls[i + 1].texto) \
                and _siguiente_es_articulo(bls, i + 1):
            abrir_nivel("PARAGRAFO", m.group("ord"), "")
            continue
        if pdf and _SUBTITULO_LIBRE.match(t) and len(t.split()) <= 14 \
                and _siguiente_es_articulo(bls, i):
            abrir_nivel("SUBTITULO", "", t.strip())
            continue
        # Subtítulo en mayúsculas sin número entre artículos (Código Civil: "REGLAS
        # GENERALES SOBRE CAPACIDAD Y DIGNIDAD PARA SUCEDER"), a veces en dos líneas.
        if actual and _es_nombre(t) and (_siguiente_es_articulo(bls, i) or (
                i + 1 < len(bls) and _es_nombre(bls[i + 1].texto)
                and _siguiente_es_articulo(bls, i + 1))):
            abrir_nivel("SUBTITULO", "", t.strip(" ."))
            esperando_nombre = "SUBTITULO"
            continue
        if actual:
            actual.bloques.append(b)
            if m := _NUMERAL.match(t):
                ultimo_numeral = int(m.group("n"))
        elif not seg.articulos and not pila:
            seg.preambulo.append(b)
        else:
            seg.huerfanos.append(b)
    return seg


def ruta_jerarquia(jer: list[tuple[str, str, str]], con_nombres: bool = True) -> str:
    partes = []
    for nivel, ordinal, nombre in jer:
        etiqueta = _ETIQUETA[nivel]
        if re.fullmatch(r"[IVXLC]+", ordinal):
            ord_fmt = ordinal
        elif re.fullmatch(r"\d+[OoºÑ°]?", ordinal):
            ord_fmt = ordinal.lower()
        else:
            ord_fmt = ordinal.title()
        base = f"{etiqueta} {ord_fmt}".strip()
        if nivel == "SUBTITULO":
            base = f"{ordinal}. {nombre}" if ordinal else nombre
        elif con_nombres and nombre:
            base += f" {nombre.capitalize()}"
        partes.append(base)
    return " > ".join(partes)
