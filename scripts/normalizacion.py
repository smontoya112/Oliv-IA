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

Pensado para reutilizarse en expansion de consultas, verificacion de citas,
analisis de errores y la interfaz.
"""
from __future__ import annotations

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


def slug_to_norma(slug: str) -> Optional[tuple[str, str, str]]:
    """Devuelve (tipo, numero, anio) para un slug del YAML de alias, si se conoce."""
    entry = _ALIAS_DICT.get("codigos", {}).get(slug)
    if not entry:
        return None
    tipo, numero, anio = entry.get("tipo"), entry.get("numero"), entry.get("anio")
    if tipo is None or numero is None or anio is None:
        return None
    return (str(tipo), str(numero), str(anio))


def to_canonical_id(cita: tuple) -> str:
    """Convierte una tupla de citations.extract() al ID canonico de la Fase 4.

    Ejemplos:
        ("ley", "1564", "2012", "391")       -> "ley_1564_2012#art_391"
        ("codigo_general_proceso", None, None, "6") -> "ley_1564_2012#art_6"
        ("jurisprudencia", "C-355", "2006", None)   -> "sentencia_C-355_2006"
    """
    cuerpo, numero, anio, articulo = cita

    if cuerpo == "jurisprudencia":
        base = f"sentencia_{numero}_{anio}"
    elif numero and anio:
        base = f"{cuerpo}_{numero}_{anio}"
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


def extract_canonical(text: str) -> set[str]:
    """Extrae y normaliza las citas de un texto a IDs canonicos (Fase 4)."""
    return {to_canonical_id(c) for c in citations.extract(text)}
