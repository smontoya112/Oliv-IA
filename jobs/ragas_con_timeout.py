"""Envoltorio NO oficial para scripts/evaluate.py --ragas: le agrega un timeout corto y
pocos reintentos al cliente del juez, sin modificar scripts/evaluate.py (archivo oficial
del evaluador de la hackathon, inmodificable).

scripts/evaluate.py hace `from langchain_openai import ChatOpenAI` DENTRO de score_ragas()
(import local, en tiempo de ejecucion). Si para entonces ya reemplazamos
langchain_openai.ChatOpenAI por una subclase con timeout/max_retries por defecto, ese
import local recoge la version parcheada sin tocar el archivo oficial.

Motivo: sin timeout, el cliente de OpenAI espera hasta 600s por llamada y reintenta solo
antes de fallar; con ~35 preguntas de texto libre eso puede colgar el job 30+ minutos sin
ningun mensaje (ver logs/evaluar_ragas_751603.out, Paso 7.5).

Uso identico a scripts/evaluate.py, mismos argumentos:
    python jobs/ragas_con_timeout.py --submission <sub>.jsonl --split sample --ragas --out <salida>.json
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import langchain_openai  # noqa: E402

_ChatOpenAIOriginal = langchain_openai.ChatOpenAI
TIMEOUT_SEGUNDOS = 60
MAX_REINTENTOS = 2


class _ChatOpenAIConTimeout(_ChatOpenAIOriginal):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("timeout", TIMEOUT_SEGUNDOS)
        kwargs.setdefault("max_retries", MAX_REINTENTOS)
        super().__init__(*args, **kwargs)


langchain_openai.ChatOpenAI = _ChatOpenAIConTimeout

import evaluate  # noqa: E402  (scripts/evaluate.py; recoge la clase ya parcheada)

if __name__ == "__main__":
    sys.exit(evaluate.main())
