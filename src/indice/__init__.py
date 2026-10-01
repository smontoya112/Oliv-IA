"""Fase 5: índices denso (bge-m3 + FAISS) y léxico (bm25s) sobre data/processed/chunks.parquet."""
import sys
from pathlib import Path

# scripts/citations.py es del evaluador oficial y no se modifica: se importa tal cual.
_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
