"""Fase 7: generación de la respuesta (decoder llama.cpp + prompts + postproceso).

Contrato con la fase 6 (recuperación):
    generar(item, pasajes, motor)              -> dict con el formato de submission.schema.json
    generar_lote(items, pasajes_por_id, motor) -> list[dict]
donde `pasajes` es una lista de {"doc_id", "texto", "inicio"?, "fin"?, "score"?}.
"""
import sys
from pathlib import Path

# citations.py (parser del evaluador) vive en scripts/; igual que en src.procesamiento.
_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
