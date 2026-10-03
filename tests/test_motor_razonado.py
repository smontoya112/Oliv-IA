"""Motor.pensar / probabilidades_letras / reiniciar con un `llm` falso (sin llama.cpp ni GPU)."""
import json
import sys
import types

import numpy as np
import pytest

import src.generacion  # noqa: F401
from src.generacion.motor import Motor


class LlmFalso:
    """Imita lo que usa Motor de llama_cpp.Llama."""

    def __init__(self):
        self.llamadas, self.resets = [], 0

    def reset(self):
        self.resets += 1

    def tokenize(self, datos, add_bos=False, special=False):
        return [ord(datos.decode()[0])] if len(datos) == 1 else list(range(len(datos.split())))

    def create_completion(self, prompt, max_tokens, temperature, seed, stop=None,
                          grammar=None, logits_processor=None, repeat_penalty=None):
        self.llamadas.append({"prompt": prompt, "max_tokens": max_tokens, "stop": stop,
                              "grammar": grammar, "repeat_penalty": repeat_penalty})
        if logits_processor:                          # primera letra: A=1, B=3, C=2, D=0 (logits)
            scores = np.zeros(200, dtype=np.float32)
            for letra, v in zip("ABCD", (1.0, 3.0, 2.0, 0.0)):
                scores[ord(letra)] = v
            for proc in logits_processor:
                proc(np.array([1, 2, 3]), scores)
            return {"choices": [{"text": "B", "finish_reason": "length"}]}
        if grammar is not None:
            return {"choices": [{"text": json.dumps({"respuesta_correcta": "B"}),
                                 "finish_reason": "stop"}]}
        largo = max_tokens >= 50
        return {"choices": [{"text": "  razono esto  ", "finish_reason": "length" if largo else "stop"}]}


@pytest.fixture
def motor(monkeypatch):
    fake = types.ModuleType("llama_cpp")
    fake.LlamaGrammar = types.SimpleNamespace(from_json_schema=lambda s: ("gramatica", s))
    fake.LogitsProcessorList = list
    monkeypatch.setitem(sys.modules, "llama_cpp", fake)
    m = Motor.__new__(Motor)
    m.llm, m.nombre, m.admite_pensar = LlmFalso(), "qwen3-8b", True
    return m


MSGS = [{"role": "system", "content": "sis"}, {"role": "user", "content": "pregunta"}]


def test_chatml_arma_el_prompt_con_el_inicio_de_la_respuesta():
    t = Motor.chatml(MSGS, "<think>\n")
    assert t == ("<|im_start|>system\nsis<|im_end|>\n<|im_start|>user\npregunta<|im_end|>\n"
                 "<|im_start|>assistant\n<think>\n")


def test_pensar_razona_cierra_el_bloque_y_fuerza_el_json(motor):
    r = motor.pensar(MSGS, {"type": "object"}, max_pensar=100, max_final=50)
    pensar, final = motor.llm.llamadas
    assert pensar["stop"] == ["</think>"] and pensar["max_tokens"] == 100 and pensar["grammar"] is None
    assert pensar["prompt"].endswith("<|im_start|>assistant\n<think>\n")
    assert final["grammar"] == ("gramatica", json.dumps({"type": "object"}))
    assert final["prompt"].endswith("<think>\nrazono esto\n</think>\n\n")     # razonamiento adentro
    assert r["cortado"] is True and json.loads(r["final"]) == {"respuesta_correcta": "B"}
    assert motor.llm.resets == 1


def test_pensar_sin_reiniciar_reutiliza_el_prefijo(motor):
    motor.pensar(MSGS, {"type": "object"}, reiniciar=False)
    assert motor.llm.resets == 0


def test_probabilidades_letras_es_un_softmax_entre_las_letras(motor):
    p = motor.probabilidades_letras(MSGS, list("ABCD"))
    assert abs(sum(p.values()) - 1) < 1e-9 and max(p, key=p.get) == "B"
    esperado = np.exp([1, 3, 2, 0]) / np.exp([1, 3, 2, 0]).sum()
    assert [round(p[l], 6) for l in "ABCD"] == [round(float(x), 6) for x in esperado]
    llamada = motor.llm.llamadas[0]
    assert llamada["max_tokens"] == 1 and llamada["prompt"].endswith("<think>\n\n</think>\n\n")
    assert motor.llm.resets == 1


def test_reiniciar_limpia_el_kv_si_la_libreria_lo_ofrece(motor):
    llamado = []
    motor.llm._ctx = types.SimpleNamespace(kv_cache_clear=lambda: llamado.append(1))
    motor.reiniciar()
    assert motor.llm.resets == 1 and llamado == [1]
