"""Fase 8: verificación de citas y abstención (sin GPU, sin modelos).

    verificar(item, campos, pasajes, catalogo)  -> (campos, pasajes, reporte)   (citas.py, 8.1-8.3)
    decidir(item, campos, pasajes, senales, reporte) -> (abstiene, motivo)      (abstencion.py, 8.4)
    validar(lineas, ids)                         -> list[str]                    (esquema.py, 8.5)

El respaldo se mide igual que scripts/evaluate.py: cuerpos normativos (citations.bodies) de
citations.extract sobre el `texto` de los 10 primeros pasajes_recuperados.
"""
import sys
from pathlib import Path

# scripts/citations.py, scripts/normalizacion.py y scripts/evaluate.py se importan tal cual.
_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
