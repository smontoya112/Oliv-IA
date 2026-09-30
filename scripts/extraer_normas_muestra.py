"""
Paso 1.1 - Extraccion de normas citadas en data/sample_50.jsonl.

Parsea el campo `legal_basis` de las 50 preguntas de muestra, identifica cada
cuerpo normativo citado (leyes, decretos, codigos por nombre/sigla y
sentencias), lo agrupa por cuerpo normativo y lo cruza contra
data/seed_targets.json para reportar que esta cubierto y que falta.

Uso:
    python scripts/extraer_normas_muestra.py
    python scripts/extraer_normas_muestra.py --json > reporte.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_PATH = ROOT / "data" / "sample_50.jsonl"
SEED_PATH = ROOT / "data" / "seed_targets.json"

# --------------------------------------------------------------------------
# Alias de codigos y estatutos citados por nombre/sigla, sin numero de ley.
# Cada alias resuelve a una clave canonica (tipo, numero, anio) tal como se
# representa (tras las correcciones anteriores) en seed_targets.json.
# --------------------------------------------------------------------------
ALIAS_CODIGOS = [
    (r"c\.?\s*g\.?\s*p\.?\b", ("codigo_general_proceso", None, None), "Codigo General del Proceso"),
    (r"c[oó]digo\s+general\s+del\s+proceso", ("codigo_general_proceso", None, None), "Codigo General del Proceso"),
    (r"c\.?\s*s\.?\s*t\.?\b", ("codigo_sustantivo_trabajo", None, None), "Codigo Sustantivo del Trabajo"),
    (r"c[oó]digo\s+sustantivo\s+del?\s+trabajo", ("codigo_sustantivo_trabajo", None, None), "Codigo Sustantivo del Trabajo"),
    (r"cpaca\b", ("ley", "1437", "2011"), "CPACA"),
    (r"c[oó]digo\s+(de\s+)?procedimiento\s+administrativo", ("ley", "1437", "2011"), "CPACA"),
    (r"c[oó]digo\s+contencioso\s+administrativo", ("ley", "1437", "2011"), "CPACA (o Decreto 1 de 1984, version anterior)"),
    (r"c\.?\s*c\.?\b", ("ley", "84", "1873"), "Codigo Civil"),
    (r"c[oó]digo\s+civil", ("ley", "84", "1873"), "Codigo Civil"),
    (r"c[oó]digo\s+penal\b(?!\s+militar)", ("ley", "599", "2000"), "Codigo Penal"),
    (r"c[oó]digo\s+de\s+comercio", ("decreto", "410", "1971"), "Codigo de Comercio"),
    (r"c[oó]digo\s+de\s+procedimiento\s+penal", ("ley", "906", "2004"), "Codigo de Procedimiento Penal"),
    (r"estatuto\s+(del\s+)?consumidor", ("estatuto_consumidor", None, None), "Estatuto del Consumidor"),
    (r"estatuto\s+tributario", ("estatuto_tributario", None, None), "Estatuto Tributario"),
    (r"estatuto\s+org[aá]nico\s+del?\s+sistema\s+financiero", ("decreto", "663", "1993"), "Estatuto Organico del Sistema Financiero"),
    (r"c[oó]digo\s+de\s+la\s+infancia", ("codigo_infancia", None, None), "Codigo de Infancia y Adolescencia"),
    (r"constituci[oó]n\s+pol[ií]tica", ("constitucion", None, None), "Constitucion Politica"),
]

RE_DECRETO_LEY = re.compile(
    r"decreto\s+ley\s+(\d{1,5})\s+de\s+(\d{4})", re.IGNORECASE
)
RE_LEY = re.compile(
    r"\bley\s+(\d{1,5})\s+de\s+(\d{4})", re.IGNORECASE
)
RE_DECRETO = re.compile(
    r"\bdecreto\s+(\d{1,5})\s+de\s+(\d{4})", re.IGNORECASE
)
RE_SENTENCIA_LARGA = re.compile(
    r"(sentencia\s+(?:de\s+unificaci[oó]n\s+)?)?\b([CT]|SU|SL|SP|SC)[\s-]?(\d{1,5})\s*(?:de|del|/)\s*(\d{2,4})",
    re.IGNORECASE,
)
RE_SENTENCIA_CORTA = re.compile(
    r"\b([CT]|SU|SL|SP|SC)-(\d{1,5})/(\d{2})\b", re.IGNORECASE
)

SALA_MAP = {"SL": "Corte Suprema (Sala Laboral)", "SP": "Corte Suprema (Sala Penal)",
            "SC": "Corte Suprema (Sala Civil)", "C": "Corte Constitucional",
            "T": "Corte Constitucional", "SU": "Corte Constitucional"}


def _year4(y: str) -> str:
    if len(y) == 2:
        return "20" + y if int(y) < 50 else "19" + y
    return y


def extraer_referencias(texto: str):
    """Devuelve una lista de dicts {clave, etiqueta, tipo} para un legal_basis."""
    if not texto:
        return []
    texto_low = texto.lower()
    refs = []

    for patron, clave, etiqueta in ALIAS_CODIGOS:
        if re.search(patron, texto_low):
            refs.append({"clave": clave, "etiqueta": etiqueta, "tipo": "codigo/estatuto"})

    decreto_ley_spans = []
    for m in RE_DECRETO_LEY.finditer(texto):
        num, anio = m.group(1), m.group(2)
        refs.append({"clave": ("decreto", num, anio), "etiqueta": f"Decreto Ley {num} de {anio}", "tipo": "decreto"})
        decreto_ley_spans.append(m.span())

    def _dentro_de_decreto_ley(span):
        return any(a <= span[0] and span[1] <= b for a, b in decreto_ley_spans)

    for m in RE_LEY.finditer(texto):
        if _dentro_de_decreto_ley(m.span()):
            continue
        num, anio = m.group(1), m.group(2)
        refs.append({"clave": ("ley", num, anio), "etiqueta": f"Ley {num} de {anio}", "tipo": "ley"})

    for m in RE_DECRETO.finditer(texto):
        if _dentro_de_decreto_ley(m.span()):
            continue
        num, anio = m.group(1), m.group(2)
        refs.append({"clave": ("decreto", num, anio), "etiqueta": f"Decreto {num} de {anio}", "tipo": "decreto"})

    for m in RE_SENTENCIA_CORTA.finditer(texto):
        sala, num, anio2 = m.group(1).upper(), m.group(2), m.group(3)
        anio = _year4(anio2)
        codigo = f"{sala}-{num}"
        refs.append({"clave": ("jurisprudencia", codigo, anio),
                     "etiqueta": f"Sentencia {codigo} de {anio} ({SALA_MAP.get(sala, '?')})",
                     "tipo": "jurisprudencia"})

    for m in RE_SENTENCIA_LARGA.finditer(texto):
        sala, num, anio_raw = m.group(2).upper(), m.group(3), m.group(4)
        anio = _year4(anio_raw)
        codigo = f"{sala}-{num}"
        clave = ("jurisprudencia", codigo, anio)
        if not any(r["clave"] == clave for r in refs):
            refs.append({"clave": clave,
                         "etiqueta": f"Sentencia {codigo} de {anio} ({SALA_MAP.get(sala, '?')})",
                         "tipo": "jurisprudencia"})

    return refs


def cargar_muestra():
    items = []
    with SAMPLE_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def cargar_seed():
    with SEED_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def construir_indice_seed(seed):
    """Construye:
    - claves_exactas: set de (tipo, numero, anio) tal como aparecen en canonico
    - claves_solo_tipo: set de tipo cuando numero/anio son null (codigos con slug propio)
    """
    claves_exactas = set()
    claves_slug = set()
    for d in seed["documentos"]:
        tipo, num, anio = d["canonico"]
        if num is None and anio is None:
            claves_slug.add(tipo)
        else:
            claves_exactas.add((tipo, str(num), str(anio)))
    return claves_exactas, claves_slug


# Normas que en seed_targets.json estan registradas bajo un slug propio
# (canonico = [slug, null, null]) pero que en el texto libre de legal_basis
# suelen citarse por su numero de ley/decreto. Sin este mapa, ambas formas
# contarian como cuerpos normativos distintos aunque sean el mismo documento.
EQUIVALENCIAS_NUMERICAS_A_SLUG = {
    ("ley", "1564", "2012"): "codigo_general_proceso",
    ("ley", "1480", "2011"): "estatuto_consumidor",
    ("decreto", "2663", "1950"): "codigo_sustantivo_trabajo",
    ("ley", "1098", "2006"): "codigo_infancia",
}


def esta_cubierta(clave, claves_exactas, claves_slug):
    tipo, num, anio = clave
    if num is None and anio is None:
        return tipo in claves_slug
    clave_norm = (tipo, str(num), str(anio))
    if clave_norm in claves_exactas:
        return True
    slug_equivalente = EQUIVALENCIAS_NUMERICAS_A_SLUG.get(clave_norm)
    return slug_equivalente is not None and slug_equivalente in claves_slug


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="Emite el reporte en JSON en vez de texto")
    parser.add_argument("--out", type=str, default=None, help="Escribe el JSON a este archivo (UTF-8) en vez de stdout")
    args = parser.parse_args()

    items = cargar_muestra()
    seed = cargar_seed()
    claves_exactas, claves_slug = construir_indice_seed(seed)

    agrupado = defaultdict(lambda: {"etiqueta": None, "tipo": None, "ids": [], "cubierta": None})
    sin_parsear = []

    for item in items:
        legal_basis = item.get("legal_basis")
        refs = extraer_referencias(legal_basis or "")
        if not refs:
            sin_parsear.append({"id": item["id"], "legal_basis": legal_basis, "area": item.get("area")})
            continue
        for r in refs:
            entry = agrupado[r["clave"]]
            entry["etiqueta"] = r["etiqueta"]
            entry["tipo"] = r["tipo"]
            entry["ids"].append(item["id"])
            entry["cubierta"] = esta_cubierta(r["clave"], claves_exactas, claves_slug)

    cubiertas = {k: v for k, v in agrupado.items() if v["cubierta"]}
    faltantes = {k: v for k, v in agrupado.items() if not v["cubierta"]}

    if args.json:
        out = {
            "cubiertas": [
                {"clave": list(k), **v} for k, v in sorted(cubiertas.items(), key=lambda kv: -len(kv[1]["ids"]))
            ],
            "faltantes": [
                {"clave": list(k), **v} for k, v in sorted(faltantes.items(), key=lambda kv: -len(kv[1]["ids"]))
            ],
            "sin_parsear": sin_parsear,
            "totales": {
                "preguntas_muestra": len(items),
                "cuerpos_normativos_distintos": len(agrupado),
                "cubiertos": len(cubiertas),
                "faltantes": len(faltantes),
                "preguntas_sin_referencia_parseable": len(sin_parsear),
            },
        }
        if args.out:
            with open(args.out, "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False, indent=2)
        else:
            json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
            print()
        return

    print(f"Preguntas de muestra analizadas: {len(items)}")
    print(f"Cuerpos normativos distintos citados: {len(agrupado)}")
    print(f"  -> cubiertos en seed_targets.json: {len(cubiertas)}")
    print(f"  -> FALTANTES en seed_targets.json: {len(faltantes)}")
    print(f"Preguntas sin referencia normativa parseable: {len(sin_parsear)}")
    print()

    print("=" * 78)
    print("CUBIERTOS (ya estan en seed_targets.json)")
    print("=" * 78)
    for k, v in sorted(cubiertas.items(), key=lambda kv: -len(kv[1]["ids"])):
        print(f"  [{len(v['ids']):2d}x] {v['etiqueta']:<55s} ids={v['ids']}")

    print()
    print("=" * 78)
    print("FALTANTES (citados en la muestra, ausentes de seed_targets.json)")
    print("=" * 78)
    for k, v in sorted(faltantes.items(), key=lambda kv: -len(kv[1]["ids"])):
        print(f"  [{len(v['ids']):2d}x] {v['etiqueta']:<55s} ids={v['ids']}")

    print()
    print("=" * 78)
    print("SIN REFERENCIA NORMATIVA PARSEABLE (revisar a mano)")
    print("=" * 78)
    for s in sin_parsear:
        print(f"  id={s['id']:<5} area={s['area']:<45} legal_basis={s['legal_basis']!r}")


if __name__ == "__main__":
    main()
