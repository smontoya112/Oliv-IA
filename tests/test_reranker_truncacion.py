"""El reranker no debe fallar cuando la consulta, por sí sola, no cabe en la ventana (ids 86 y 695 del test)."""
from contextlib import contextmanager

import pytest

from src.recuperacion.reranker import Reranker

MENSAJE = "Truncation error: Sequence to truncate too short to respect the provided max_length"


class _Lista(list):
    def view(self, *_):
        return self

    def float(self):
        return self

    def cpu(self):
        return self

    def tolist(self):
        return list(self)


class _Enc(dict):
    def to(self, _):
        return self


class _Torch:
    @contextmanager
    def inference_mode(self):
        yield


class _Tok:
    """Una palabra = un token. Falla como el tokenizador real cuando la consulta no deja espacio al pasaje."""

    def __init__(self):
        self.llamadas = []

    def __call__(self, a, b=None, **kw):
        if b is None:                                    # tokenización de la consulta sola
            return {"input_ids": list(range(len(a.split())))}
        n = len(a[0].split())
        self.llamadas.append(n)
        if n >= kw["max_length"] - 2:
            raise Exception(MENSAJE)
        return _Enc(consultas=a, pasajes=b)

    def decode(self, ids):
        return " ".join(f"t{i}" for i in ids)


class _Modelo:
    def __call__(self, consultas, pasajes):
        return type("Salida", (), {"logits": _Lista([float(len(p.split())) for p in pasajes])})()


def _reranker(max_tokens=512, lote=2):
    r = object.__new__(Reranker)
    r.torch, r.tok, r.model, r.device = _Torch(), _Tok(), _Modelo(), "cpu"
    r.lote, r.max_tokens = lote, max_tokens
    return r


def test_consulta_que_cabe_se_puntua_sin_recortar():
    r = _reranker()
    assert r.puntuar("una consulta corta", ["a b", "c d e", "f"]) == [2.0, 3.0, 1.0]
    assert r.tok.llamadas == [3, 3]            # un solo intento por lote: nada se recorta


def test_consulta_larga_se_recorta_y_se_puntua():
    r = _reranker()
    consulta = " ".join(f"w{i}" for i in range(700))   # no cabe en 512 tokens
    assert r.puntuar(consulta, ["a b", "c d e", "f"]) == [2.0, 3.0, 1.0]
    assert r.tok.llamadas[0] == 700 and 256 in r.tok.llamadas   # primer intento fallido y reintento con 96 + 160 tokens


def test_recorte_conserva_inicio_y_final():
    r = _reranker()
    ids = " ".join(f"w{i}" for i in range(700))
    corto = r.recortar_consulta(ids).split()
    assert len(corto) == 256 and corto[0] == "t0" and corto[95] == "t95" and corto[-1] == "t699"


class _TokRoto(_Tok):
    def __call__(self, a, b=None, **kw):
        if b is None:
            return {"input_ids": []}
        raise RuntimeError("otra cosa")


def test_otros_errores_no_se_ocultan():
    r = _reranker()
    r.tok = _TokRoto()
    with pytest.raises(RuntimeError):
        r.puntuar("x", ["a"])
