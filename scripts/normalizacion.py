"""Normalizacion canonica de citas (Fase 4).

Este modulo NO modifica scripts/citations.py (parte del evaluador oficial de
la hackathon, archivo inmodificable). En su lugar:

- Envuelve citations.extract() para convertir sus tuplas
  (cuerpo, numero, anio, articulo) al identificador canonico de la Fase 4
  (Paso 4.1), p. ej. "ley_1564_2012#art_391" o "sentencia_C-355_2006".
- Carga data/alias_normas.yaml (Paso 4.2), el espejo documental de los
  diccionarios CODES/_ALIAS_NUM de citations.py, para poder resolver el
  (tipo, numero, anio) real de un slug como "codigo_general_proceso" cuando
  citations.py solo devolvio el slug (porque la cita usaba el alias y no el
  numero de ley).
- Añade un matcher adicional (_extract_extensiones) para normas derogadas o
  poco citadas por numero presentes en el corpus (data/corpus_manifest.json)
  que citations.py no conoce en absoluto (Código de Procedimiento Civil,
  Código Contencioso Administrativo, Código del Menor, Estatuto Orgánico del
  Sistema Financiero): ver la seccion "extensiones" de data/alias_normas.yaml.
  Importante: scripts/evaluate.py solo usa
  citations.extract(), asi que estas citas extra NUNCA las vera el evaluador
  oficial; solo quedan disponibles para quien use extract_canonical() de este
  modulo (expansion de consultas, interfaz, analisis de errores).

Pensado para reutilizarse en expansion de consultas, verificacion de citas,
analisis de errores y la interfaz.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Optional

import yaml

SCRIPTS_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPTS_DIR.parent / "data"
ALIAS_YAML_PATH = DATA_DIR / "alias_normas.yaml"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import citations  # noqa: E402  (evaluador oficial, no modificar)


def load_alias_dict(path: Path = ALIAS_YAML_PATH) -> dict:
    """Carga data/alias_normas.yaml."""
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


_ALIAS_DICT = load_alias_dict()
_EXTENSIONES = _ALIAS_DICT.get("extensiones", {})


def slug_to_norma(slug: str) -> Optional[tuple[str, str, str]]:
    """Devuelve (tipo, numero, anio) para un slug del YAML de alias, si se conoce."""
    entry = _ALIAS_DICT.get("codigos", {}).get(slug) or _EXTENSIONES.get(slug)
    if not entry:
        return None
    tipo, numero, anio = entry.get("tipo"), entry.get("numero"), entry.get("anio")
    if tipo is None or numero is None or anio is None:
        return None
    return (str(tipo), str(numero), str(anio))


def _sin_ceros(numero: str) -> str:
    """Quita ceros a la izquierda de un numero puramente numerico.

    citations.py conserva el numero tal como aparece en el texto (p. ej.
    "046" en "Decreto 046 de 2024"), asi que sin esto la misma norma citada
    como "Decreto 46 de 2024" y como "Decreto 046 de 2024" produciria dos IDs
    distintos (decreto_46_2024 vs decreto_046_2024), lo que rompe la
    canonicalizacion. Los numeros de sentencia (p. ej. "C-355") ya llegan
    normalizados desde citations.py y no son puramente numericos, por lo que
    no se tocan aqui.
    """
    return str(int(numero)) if numero.isdigit() else numero


def to_canonical_id(cita: tuple) -> str:
    """Convierte una tupla de citations.extract() al ID canonico de la Fase 4.

    Ejemplos:
        ("ley", "1564", "2012", "391")       -> "ley_1564_2012#art_391"
        ("codigo_general_proceso", None, None, "6") -> "ley_1564_2012#art_6"
        ("jurisprudencia", "C-355", "2006", None)   -> "sentencia_C-355_2006"
        ("decreto", "046", "2024", None)      -> "decreto_46_2024"
    """
    cuerpo, numero, anio, articulo = cita

    if cuerpo == "jurisprudencia":
        base = f"sentencia_{numero}_{anio}"
    elif numero and anio:
        base = f"{cuerpo}_{_sin_ceros(numero)}_{anio}"
    else:
        norma = slug_to_norma(cuerpo)
        if norma:
            tipo, num, yr = norma
            base = f"{tipo}_{num}_{yr}"
        else:
            base = cuerpo

    if articulo:
        return f"{base}#art_{articulo}"
    return base


def _extract_extensiones(text: str) -> set[tuple]:
    """Citas de codigos derogados que citations.py no reconoce (ver _EXTENSIONES).

    Replica el criterio de citations.py para codigos citados por alias
    (match de texto + articulo cercano via citations._articles_near), pero
    sobre un universo de normas que el evaluador oficial no cubre.
    """
    t = citations.norm(text)
    found: set[tuple] = set()
    for slug, entry in _EXTENSIONES.items():
        for v in entry["alias"]:
            pat = r"(?<![\w.])" + re.escape(v).replace(r"\ ", r"\s+") + r"(?![\w])"
            for m in re.finditer(pat, t):
                arts = citations._articles_near(t, m.end(), m.start())
                if arts:
                    found.update((slug, None, None, a) for a in arts)
                else:
                    found.add((slug, None, None, None))
    return found


def extract_canonical(text: str) -> set[str]:
    """Extrae y normaliza las citas de un texto a IDs canonicos (Fase 4).

    Combina citations.extract() (evaluador oficial) con _extract_extensiones()
    (codigos derogados ausentes de citations.py, ver modulo docstring).
    """
    citas = citations.extract(text) | _extract_extensiones(text)
    return {to_canonical_id(c) for c in citas}
