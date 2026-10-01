"""Fase 6: recuperación. Dado un ítem, devuelve los 10 mejores pasajes y señales para la fase 8.

    recuperar(item) -> {"pasajes": [...], "senales": {...}}      (src.recuperacion.pipeline)

`pasajes` ya tiene la forma que consume src.generacion.pipeline.generar_lote.
"""
import sys
from pathlib import Path

# scripts/citations.py y scripts/normalizacion.py (fase 4) se importan tal cual.
_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
