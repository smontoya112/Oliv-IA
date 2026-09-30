"""Fase 3: limpieza y segmentación de data/md/*.md en fragmentos indexables."""
import sys
from pathlib import Path

# El parser de citas del evaluador (scripts/citations.py) es la referencia de qué
# cuenta como norma reconocida; se reutiliza tal cual, sin copiarlo.
_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
