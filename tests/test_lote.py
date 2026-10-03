"""Pruebas de la corrida por partes (src/lote.py) sin GPU, con el recuperador y el decoder
falsos de test_responder."""
import json
from collections import Counter

import src.responder as R
from src import lote
from src.responder import Responder

from tests.falsos import CERRADA, MotorFalso, RecuperadorFalso


def _items(n=31):
    formatos = ["multiple_choice", "semi_open", "open_ended"]
    res = []
    for i in range(1, n + 1):
        f = formatos[i % 3 if i % 5 else 2]
        it = {"id": 100 + i, "formato": f, "pregunta": f"¿Pregunta {i} sobre la acción de grupo?"}
        if f == "multiple_choice":
            it["opciones"] = {"A": "a", "B": "b", "C": "c", "D": "d"}
        res.append(it)
    return res


def test_dividir_cubre_todo_sin_repetir_y_balancea_formatos():
    items = _items()
    partes = lote.dividir(items, 3)
    ids = [it["id"] for p in partes for it in p]
    assert sorted(ids) == sorted(it["id"] for it in items) and len(ids) == len(set(ids))
    assert max(map(len, partes)) - min(map(len, partes)) <= 1
    total = Counter(it["formato"] for it in items)
    for f, n in total.items():
        por_parte = [sum(it["formato"] == f for it in p) for p in partes]
        assert max(por_parte) - min(por_parte) <= 1, (f, por_parte)


def test_dividir_es_determinista_sin_importar_el_orden():
    items = _items()
    assert lote.dividir(items, 3) == lote.dividir(list(reversed(items)), 3)


def test_revisar_detecta_problemas():
    items = [{"id": 1, "formato": "semi_open", "pregunta": "¿Qué es?"},
             {"id": 1, "formato": "semi_open", "pregunta": "¿Otra?"},
             {"id": 2, "formato": "semi_open", "pregunta": "  "},
             {"formato": "semi_open", "pregunta": "sin id"}]
    p = " | ".join(lote.revisar(items))
    assert "duplicado" in p and "id 2" in p and "línea 4" in p


def test_lote_y_responder_dan_la_misma_linea():
    item = {"id": 7, "formato": "multiple_choice", "pregunta": "¿En qué caso procede la acción de grupo?",
            "opciones": R.extraer_opciones(CERRADA)[1]}
    vivo = Responder(R.cargar_config(), RecuperadorFalso(), MotorFalso()).responder(item)["submission"]
    rec, mot = RecuperadorFalso(), MotorFalso()
    del_lote = R.responder_item(R.preparar_item(item), rec.recuperar(item), mot)
    sin = lambda s: {k: v for k, v in s.items() if k != "latencia_ms"}
    assert sin(vivo) == sin(del_lote)


def test_correr_reanuda_desde_el_checkpoint(tmp_path):
    items = _items(9)
    salida = tmp_path / "sub_1.jsonl"
    r1 = lote.correr(items[:4], RecuperadorFalso(), MotorFalso(), salida, tmp_path / "rec_1.jsonl")
    assert r1["nuevas"] == 4
    with salida.open("a", encoding="utf-8") as f:
        f.write('{"id": 999, "formato": "semi_o')          # línea cortada por una caída
    r2 = lote.correr(items, RecuperadorFalso(), MotorFalso(), salida, tmp_path / "rec_1.jsonl")
    assert r2["nuevas"] == 5 and not r2["fallidos"]
    lineas = [json.loads(l) for l in salida.read_text(encoding="utf-8").splitlines()]
    assert sorted(l["id"] for l in lineas) == sorted(it["id"] for it in items)


def test_correr_abstiene_un_item_que_falla(tmp_path):
    class Roto(RecuperadorFalso):
        def recuperar(self, item):
            if item["id"] == 102:
                raise RuntimeError("se cayó")
            return super().recuperar(item)
    r = lote.correr(_items(3), Roto(), MotorFalso(), tmp_path / "s.jsonl")
    assert r["fallidos"] == [102]
    subs = lote.hechos(tmp_path / "s.jsonl")
    assert subs[102]["abstencion"] is True and len(subs) == 3


def test_unir_ordena_deduplica_y_valida(tmp_path):
    from src.verificacion.esquema import validar
    items = _items(6)
    partes = lote.dividir(items, 3)
    subs = {}
    for n, p in enumerate(partes, 1):
        ruta = tmp_path / f"sub_{n}.jsonl"
        lote.correr(p, RecuperadorFalso(), MotorFalso(), ruta)
        subs[str(ruta)] = list(lote.hechos(ruta).values())
    subs["extra"] = [subs[str(tmp_path / "sub_1.jsonl")][0], {"id": 5000, "formato": "semi_open"}]
    lineas, avisos = lote.unir(items, subs)
    assert [l["id"] for l in lineas] == sorted(it["id"] for it in items)
    assert any("repetido" in a for a in avisos) and any("5000" in a for a in avisos)
    assert validar(lineas, {it["id"] for it in items}) == []
