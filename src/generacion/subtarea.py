"""Texto libre: la forma de la respuesta depende de la sub-tarea de la pregunta.

El enunciado del reto define un catálogo fijo de sub-tareas para las semiabiertas (baja: existencia
normativa, autoridad, juez, jerarquía, definición, clasificación, elementos; media: sentido del fallo,
reproducción literal, precedente, vigencia, distinción, requisitos, excepciones, imparcialidad;
alta: conflicto, supuestos fácticos, postura procesal, problema jurídico, fundamento central,
ponderación, interpretación sistemática). Una definición pide 1-2 oraciones; la reproducción literal
pide el texto del artículo; un caso con hechos pide la conclusión primero. Un único prompt para todo
(3-5 oraciones) añade afirmaciones que no se piden (falsos positivos en RAGAS) o se queda corto.

`sample_50` trae `sub_tarea` y `complejidad`; si el test no las trae, `inferir` las deduce del
enunciado con reglas. Todo es determinista y no usa respuestas de ninguna muestra.
"""
from __future__ import annotations

import re
import unicodedata

# nombre normalizado (sin tildes, minúsculas) -> clave interna; se busca por subcadena
_NOMBRES = [
    ("existencia normativa", "existencia"), ("autoridad competente", "autoridad"),
    ("juez que decide", "juez"), ("jerarquia", "jerarquia"), ("definicion", "definicion"),
    ("clasificacion", "clasificacion"), ("elemento", "elementos"),
    ("sentido del fallo", "sentido_fallo"), ("reproduccion literal", "literal"),
    ("precedente", "precedente"), ("vigencia", "vigencia"), ("distincion", "distincion"),
    ("requisitos", "requisitos"), ("excepcion", "excepciones"), ("imparcialidad", "imparcialidad"),
    ("conflicto normativo", "conflicto"), ("supuesto", "caso"), ("postura procesal", "caso"),
    ("problema juridico", "problema"), ("fundamento juridico", "ratio"), ("ratio", "ratio"),
    ("ponderacion", "caso"), ("interpretacion sistematica", "caso"),
    ("antecedentes facticos", "antecedentes"),
]

# clave -> (instrucción para "respuesta", palabras objetivo, oraciones máximas)
_FORMAS = {
    "definicion": ("Define el concepto en una o dos oraciones y cita la norma y el artículo que "
                   "lo establece.", 60, 3),
    "elementos": ("Enumera los elementos esenciales en una sola oración continua y cita la norma "
                  "y el artículo.", 60, 3),
    "existencia": ("Empieza con \"Sí\" o \"No\". Nombra la norma (tipo, número y año, o el "
                   "artículo del código) y di en una oración qué regula.", 45, 3),
    "autoridad": ("Nombra la autoridad competente y la norma que le atribuye la competencia.",
                  50, 3),
    "juez": ("Nombra el juez o corporación que decide y la norma que le atribuye la competencia.",
             50, 3),
    "jerarquia": ("Indica el lugar de la norma en la jerarquía normativa y por qué, citando su "
                  "fundamento.", 60, 3),
    "clasificacion": ("Clasifica jurídicamente la figura o el supuesto y justifícalo con la "
                      "norma.", 60, 3),
    "literal": ("Transcribe literalmente, entre comillas, el texto del artículo, numeral o inciso "
                "que se pide, tal como aparece en los pasajes, e indica antes \"Artículo N de la "
                "<norma>\". No expliques ni parafrasees.", 120, 8),
    "sentido_fallo": ("En la primera oración di qué decidió la Corte (por ejemplo exequible, "
                      "inexequible, condicionada) y en una o dos más sus razones centrales. Nombra "
                      "la sentencia con tipo, número y año.", 90, 4),
    "precedente": ("Nombra la sentencia o sentencias (tipo, número y año) que constituyen el "
                   "precedente y resume en una o dos oraciones la regla que fijaron.", 90, 4),
    "vigencia": ("Indica si la norma está vigente, modificada o derogada, por cuál norma y desde "
                 "cuándo, según los pasajes.", 70, 3),
    "distincion": ("Contrasta los conceptos en 2 a 4 oraciones, señalando el criterio que los "
                   "distingue y citando la norma.", 100, 4),
    "requisitos": ("Enumera los requisitos o supuestos exigidos en 2 a 4 oraciones y cita la norma "
                   "y el artículo.", 100, 4),
    "excepciones": ("Enuncia la regla general y luego las excepciones que prevé la norma, con el "
                    "artículo.", 100, 4),
    "imparcialidad": ("Explica en 2 o 3 oraciones cómo garantiza la ley la imparcialidad "
                      "(impedimentos, recusaciones u otros mecanismos), citando el artículo.",
                      100, 4),
    "problema": ("Formula el problema jurídico que abordó la Corte como \"determinar si …\" en una "
                 "o dos oraciones y menciona la sentencia (tipo, número y año).", 100, 4),
    "ratio": ("Enuncia la regla o subregla que sustenta la decisión (ratio decidendi) en 3 a 5 "
              "oraciones: primero la regla y después su fundamento normativo y constitucional.",
              140, 5),
    "antecedentes": ("Resume en orden cronológico los hechos relevantes que dieron origen al caso, "
                     "en 3 a 5 oraciones.", 140, 5),
    "conflicto": ("Identifica las normas en tensión, el criterio de solución (jerarquía, "
                  "competencia, especialidad o temporalidad) y la conclusión, citando artículos.",
                  140, 5),
    "caso": ("Responde primero de forma directa a lo que se pregunta (Sí, No, o qué procede); "
             "luego enuncia la regla con su artículo y por último aplícala a los hechos, en 3 a 5 "
             "oraciones.", 140, 5),
}
_POR_COMPLEJIDAD = {"low": "definicion", "medium": "requisitos", "high": "caso"}

_REGLAS_INFERENCIA = [
    ("literal", r"(cit[eé]|transcrib|reproduzc|copie|qu[eé] dice|texto (literal|exacto)|"
                r"literalmente|fragmento).{0,80}art[ií]culo|art[ií]culo.{0,60}(literal|textual)"),
    ("problema", r"problema jur[ií]dico"),
    ("ratio", r"fundamento jur[ií]dico central|ratio decidendi|subregla"),
    ("antecedentes", r"antecedentes f[aá]cticos|hechos (relevantes )?(de|que|en) la sentencia"),
    ("sentido_fallo", r"sentido del fallo|qu[eé] (resolvi[oó]|decidi[oó]) la corte"),
    ("precedente", r"precedente|qu[eé] (defini[oó]|estableci[oó]) la corte"),
    ("conflicto", r"conflicto normativo|antinomia"),
    ("existencia", r"^\W*(existe|hay)\s+(alguna|una)?\s*(norma|ley|disposici)|"
                   r"cu[aá]l es (el|la) (art[ií]culo|norma|ley) .{0,40}(regula|define|establece)"),
    ("distincion", r"diferencias? entre|distingue|distinci[oó]n"),
    ("requisitos", r"requisitos|qu[eé] se requiere|cu[aá]ndo procede|condiciones para"),
    ("excepciones", r"excepciones?\b"),
    ("vigencia", r"vigente|derogad|vigencia"),
    ("definicion", r"^\W*(qu[eé] es|qu[eé] son|c[oó]mo se define|en qu[eé] consiste|cu[aá]l es la "
                   r"definici[oó]n|explique en qu[eé])"),
]


def _sin_tildes(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", str(t or "")) if unicodedata.category(c) != "Mn")


def normalizar_nombre(nombre: str | None) -> str | None:
    """Clave interna de un nombre de sub-tarea del catálogo (None si no se reconoce)."""
    n = _sin_tildes(nombre).lower().strip()
    if not n:
        return None
    for fragmento, clave in _NOMBRES:
        if fragmento in n:
            return clave
    return None


def inferir(pregunta: str, complejidad: str | None = None) -> str:
    """Clave deducida del enunciado. Un enunciado largo sin sentencia nombrada es un caso."""
    t = _sin_tildes(pregunta).lower()
    palabras = len(t.split())
    nombra_sentencia = bool(re.search(r"\bsentencia\b|\b[ctsu]{1,2}[- ]?\d{1,4}(?:[/ -]| de )\d{2,4}", t))
    for clave, patron in _REGLAS_INFERENCIA:
        if re.search(_sin_tildes(patron), t):
            if clave == "problema" and not nombra_sentencia and palabras > 40:
                return "caso"
            return clave
    if palabras > 45 and not nombra_sentencia:
        return "caso"
    return _POR_COMPLEJIDAD.get((complejidad or "").lower(), "requisitos")


def clave(item: dict) -> str:
    c = normalizar_nombre(item.get("sub_tarea"))
    if c == "problema" and len(str(item.get("pregunta") or "").split()) > 40 \
            and not re.search(r"sentencia", _sin_tildes(item.get("pregunta")).lower()):
        return "caso"                   # "problema jurídico" planteado como caso con hechos
    return c or inferir(item.get("pregunta") or "", item.get("complejidad"))


def plan(item: dict) -> dict:
    """{"clave", "forma", "palabras", "max_palabras", "max_oraciones"} de una semiabierta."""
    k = clave(item)
    forma, palabras, oraciones = _FORMAS[k]
    return {"clave": k, "forma": forma, "palabras": palabras,
            "max_palabras": int(palabras * 1.25), "max_oraciones": oraciones}


def instrucciones(item: dict) -> str:
    """Bloque de instrucciones del prompt v2 para semi_open y open_ended."""
    if item["formato"] == "semi_open":
        p = plan(item)
        return (f"Pregunta semiabierta (tipo de respuesta: {p['clave'].replace('_', ' ')}).\n"
                "Campos del JSON:\n"
                f"- \"respuesta\": {p['forma']} Máximo {p['palabras']} palabras. La primera "
                "oración responde directamente a lo que se pregunta; no repitas la pregunta ni "
                "agregues contexto, advertencias o información que no se pida. Si la pregunta "
                "menciona una sentencia o norma concreta, nómbrala con su nombre completo "
                "(por ejemplo \"Sentencia C-891 de 2012\").\n"
                "- \"palabras_clave\": entre 3 y 5 términos jurídicos clave de la respuesta.\n"
                "- \"referencia_legal\": la norma y el artículo (o la sentencia) que fundamentan "
                "la respuesta, con su nombre completo.")
    return ("Pregunta abierta: caso jurídico.\n"
            "Campos del JSON:\n"
            "- \"marco_normativo\": en 1 a 3 oraciones, las normas y artículos aplicables con su "
            "nombre completo; incluye la norma o sentencia que la pregunta mencione.\n"
            "- \"analisis\": de 5 a 7 oraciones. Empieza con la conclusión (qué procede o qué "
            "ocurre), aplica la regla a los hechos del caso y no repitas el marco normativo.\n"
            "- \"jurisprudencia\": las sentencias que aparezcan en los pasajes y la regla que "
            "fijan. Si no hay ninguna, escribe en una oración el principio jurídico aplicable; no "
            "escribas que no hay jurisprudencia.\n"
            "- \"conclusion\": 1 o 2 oraciones que respondan de forma directa a la pregunta.")


def limites(item: dict) -> tuple[int, int | None]:
    """(oraciones máximas, palabras máximas) del campo principal con el prompt v2."""
    if item["formato"] == "semi_open":
        p = plan(item)
        return p["max_oraciones"], p["max_palabras"]
    return 8, None


# ------------------------------------------------------------------ reproducción literal
_ART = re.compile(r"art[ií]culo\s+(\d+(?:[-.]\d+)?)", re.I)
_NUMERAL = re.compile(r"(?:numeral|ordinal)\s+(\d+)", re.I)
_NORMA_EN_PREGUNTA = re.compile(r"art[ií]culo\s+\d+(?:[-.]\d+)?\s+((?:del?|de la|de el)\s+[^,.?;:\n]+?)"
                                r"(?=\s+(?:que|en|sobre|y|donde|por)\b|[,.?;:\n]|$)", re.I)
_NOTA = re.compile(r"\{\{.*?\}\}")
_TITULO = re.compile(r"^ART[IÍ]CULO\s+\S+?\.\s*(?:(?:\{\{.*?\}\}|[A-ZÁÉÍÓÚÑ0-9][A-ZÁÉÍÓÚÑ0-9 ,;/()\-]*)\.\s*)?")
_ITEM = re.compile(r"(?m)^\s*(\d{1,2})\.\s+(?=\S)")
_PALABRA = re.compile(r"\w+", re.UNICODE)


def _contenido(t: str) -> set[str]:
    stop = {"que", "del", "las", "los", "una", "uno", "por", "para", "con", "como", "sus", "esta",
            "este", "articulo", "numeral", "codigo", "menciona", "fragmento", "cite", "cité", "dice",
            "relacion", "segun", "sobre", "donde", "cual"}
    return {w for w in _PALABRA.findall(_sin_tildes(t).lower()) if len(w) > 3 and w not in stop}


def _limpiar_nota(t: str) -> str:
    t = _NOTA.sub("", t)
    t = re.sub(r"\{([^{}]*)\}", r"\1", t)
    return " ".join(t.split())


def literal(item: dict, pasajes: list[dict], max_palabras: int = 150) -> dict | None:
    """Respuesta de "reproducción literal" copiada del pasaje del artículo pedido, sin generar:
    {"respuesta", "palabras_clave", "referencia_legal"}, o None si el artículo no está entre los
    pasajes (entonces responde el modelo). Si el artículo es una lista numerada y el enunciado pide
    un numeral ("numeral 5") o describe uno (palabras en común), solo se copia ese numeral."""
    pregunta = str(item.get("pregunta") or "")
    m = _ART.search(pregunta)
    if not m:
        return None
    n = m.group(1)
    candidatos = [p for p in pasajes if str(p.get("norma_id") or "").endswith(f"#art_{n}")]
    if not candidatos:
        return None
    p = sorted(candidatos, key=lambda x: x.get("via") != "directo")[0]
    cuerpo = str(p.get("texto") or "").split("\n", 1)
    if len(cuerpo) < 2:
        return None
    texto = _TITULO.sub("", cuerpo[1].strip(), count=1)
    texto = _limpiar_nota(texto)
    nombre = _NORMA_EN_PREGUNTA.search(pregunta)
    nombre = " ".join(nombre.group(1).split()) if nombre else None
    if not nombre:
        h = re.match(r"Art[ií]culo\s+\S+\s+((?:del?|de la)\s+.+?)(?:\s+\(|\.\s|$)", cuerpo[0])
        nombre = h.group(1) if h else "la norma"
    cabecera = f"Artículo {n} {nombre}"
    items_num = list(_ITEM.finditer(cuerpo[1]))
    if len(items_num) >= 2:
        trozos = {}
        for k, mm in enumerate(items_num):
            fin = items_num[k + 1].start() if k + 1 < len(items_num) else len(cuerpo[1])
            trozos[int(mm.group(1))] = _limpiar_nota(cuerpo[1][mm.end():fin])
        pedido = _NUMERAL.search(pregunta)
        elegido = int(pedido.group(1)) if pedido and int(pedido.group(1)) in trozos else None
        if elegido is None:
            q = _contenido(pregunta)
            puntaje = sorted(((len(q & _contenido(t)), k) for k, t in trozos.items()), reverse=True)
            if puntaje and puntaje[0][0] >= 2 and (len(puntaje) == 1 or puntaje[0][0] > puntaje[1][0]):
                elegido = puntaje[0][1]
        if elegido is not None:
            cabecera = f"Numeral {elegido} del artículo {n} {nombre}"
            texto = trozos[elegido]
    palabras = texto.split()
    if len(palabras) > max_palabras:
        texto = " ".join(palabras[:max_palabras]).rstrip(",;:") + "…"
    if not texto:
        return None
    return {"respuesta": f"{cabecera}: «{texto}»",
            "palabras_clave": [f"artículo {n}", nombre.replace("del ", "").replace("de la ", "")],
            "referencia_legal": f"Artículo {n} {nombre}"}
