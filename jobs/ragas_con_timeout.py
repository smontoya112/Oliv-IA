"""Envoltorio NO oficial para scripts/evaluate.py --ragas: le agrega un timeout razonable
al cliente del juez y baja la concurrencia de ragas, sin modificar scripts/evaluate.py
(archivo oficial del evaluador de la hackathon, inmodificable).

scripts/evaluate.py hace `from langchain_openai import ChatOpenAI` y
`from ragas import evaluate as ragas_evaluate` DENTRO de score_ragas() (imports locales,
en tiempo de ejecucion). Si para entonces ya reemplazamos esos atributos, esos imports
locales recogen la version parcheada sin tocar el archivo oficial.

Motivo del primer intento (timeout=60s, max_retries=2): sin timeout, el cliente de OpenAI
espera hasta 600s por llamada y reintenta solo antes de fallar; con ~35 preguntas de texto
libre eso puede colgar el job 30+ minutos sin ningun mensaje (ver
logs/evaluar_ragas_751603.out, Paso 7.5).

Por que se subio despues: con timeout=60s, el job 751646 fallo 18 de 27 items (el juez
z-ai/glm-5.3-flash con reasoning.effort tarda bastante por llamada, y el RunConfig por
defecto de ragas manda 16 llamadas en paralelo, lo que agrava la espera en OpenRouter). Se
sube el timeout del cliente a 180s y se le pasa a ragas_evaluate un RunConfig con menos
workers en paralelo (6) para que cada llamada tarde menos en obtener turno.

Uso identico a scripts/evaluate.py, mismos argumentos:
    python jobs/ragas_con_timeout.py --submission <sub>.jsonl --split sample --ragas --out <salida>.json
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import langchain_openai  # noqa: E402

_ChatOpenAIOriginal = langchain_openai.ChatOpenAI
TIMEOUT_SEGUNDOS = 180
MAX_REINTENTOS = 2


class _ChatOpenAIConTimeout(_ChatOpenAIOriginal):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("timeout", TIMEOUT_SEGUNDOS)
        kwargs.setdefault("max_retries", MAX_REINTENTOS)
        super().__init__(*args, **kwargs)


langchain_openai.ChatOpenAI = _ChatOpenAIConTimeout

import ragas  # noqa: E402

_ragas_evaluate_original = ragas.evaluate
RAGAS_TIMEOUT_SEGUNDOS = 240
RAGAS_MAX_WORKERS = 6
RAGAS_MAX_RETRIES = 5
RAGAS_MAX_WAIT = 30


def _ragas_evaluate_con_run_config(*args, **kwargs):
    if kwargs.get("run_config") is None:
        from ragas.run_config import RunConfig
        deseados = {
            "timeout": RAGAS_TIMEOUT_SEGUNDOS,
            "max_workers": RAGAS_MAX_WORKERS,
            "max_retries": RAGAS_MAX_RETRIES,
            "max_wait": RAGAS_MAX_WAIT,
        }
        validos = inspect.signature(RunConfig.__init__).parameters
        kwargs["run_config"] = RunConfig(**{k: v for k, v in deseados.items() if k in validos})
    return _ragas_evaluate_original(*args, **kwargs)


ragas.evaluate = _ragas_evaluate_con_run_config

import evaluate  # noqa: E402  (scripts/evaluate.py; recoge la clase y el evaluate ya parcheados)

if __name__ == "__main__":
    sys.exit(evaluate.main())
