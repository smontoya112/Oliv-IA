"""Igual que jobs/ragas_con_timeout.py (mismo scripts/evaluate.py, sin tocarlo) pero guarda además el
puntaje de RAGAS POR ÍTEM, que el evaluador oficial descarta y sin el cual no se puede ver qué ítems
mejoran o empeoran entre dos corridas.

    OLIVIA_RAGAS_ITEMS=<salida_items>.json python jobs/ragas_por_item.py --submission <sub>.jsonl \
        --split sample --ragas --out <reporte>.json

`<salida_items>.json` es una lista de {user_input, response, reference, answer_correctness}; las filas
salen en el orden de los ítems de texto libre respondidos de `sample_50` (se cruzan con `pregunta`).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ragas_con_timeout  # noqa: E402,F401  (aplica el timeout al juez y baja la concurrencia)
import ragas  # noqa: E402

_evaluate_con_run_config = ragas.evaluate


def _evaluate_y_guardar(*args, **kwargs):
    res = _evaluate_con_run_config(*args, **kwargs)
    destino = os.environ.get("OLIVIA_RAGAS_ITEMS")
    if destino:
        try:
            df = res.to_pandas()
            Path(destino).parent.mkdir(parents=True, exist_ok=True)
            df.to_json(destino, orient="records", force_ascii=False, indent=1)
            print(f"puntajes por ítem -> {destino} ({len(df)} filas)", flush=True)
        except Exception as e:                       # nunca tumbar la evaluación por esto
            print(f"AVISO: no se pudo guardar el detalle por ítem: {type(e).__name__}: {e}", file=sys.stderr)
    return res


ragas.evaluate = _evaluate_y_guardar

import evaluate  # noqa: E402  (scripts/evaluate.py)

if __name__ == "__main__":
    sys.exit(evaluate.main())
