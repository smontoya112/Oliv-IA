"""Pruebas de la fase 11 sin GPU: entrada libre, texto de salida, normas citadas, verificación
en vivo (--comparar) y la API, con un recuperador y un decoder falsos."""
import json

import pytest

import src.responder as R
from src.responder import (Responder, buscar_por_id, comparar, extraer_opciones, normas_citadas,
                           preparar_item, texto_respuesta)

import evaluate  # scripts/evaluate.py (src.responder agrega scripts/ al path)

PASAJES = [
    {"doc_id": "constitucion", "inicio": 0, "fin": 50, "score": 4.2, "via": "hibrido",
     "texto": "Artículo 88 de la Constitución Política. Acciones populares y de grupo."},
    {"doc_id": "ley_472_1998", "inicio": 10, "fin": 90, "score": 3.1, "via": "directo",
     "texto": "Artículo 46 de la Ley 472 de 1998. Procedencia de la acción de grupo."},
]
CERRADA = ("¿En qué caso procede la acción de grupo?\n"
           "A) Para proteger derechos individuales.\n"
           "B) Cuando un grupo es afectado por una causa común.\n"
           "C) Para anular una ley.\n"
           "D) Para cobrar una deuda.")


class RecuperadorFalso:
    def recuperar(self, item):
        return {"pasajes": [dict(p) for p in PASAJES], "senales": {"score_top1": 4.2}}


class MotorFalso:
    """Devuelve JSON válido según el esquema pedido (sin vLLM ni llama.cpp)."""
    def generar_lote(self, conversaciones, esquemas, max_tokens=0):
        salidas = []
        for esq in esquemas:
            props = esq["properties"]
            if "descarte_opciones" in props:
                salidas.append(json.dumps({
                    "justificacion": "Según el artículo 46 de la Ley 472 de 1998 procede por causa común.",
                    "respuesta_correcta": "B",
                    "descarte_opciones": {"A": "individual", "C": "no aplica", "D": "no aplica"}}))
            elif "palabras_clave" in props:
                salidas.append(json.dumps({
                    "respuesta": "La acción de grupo procede por una causa común. Está en la Ley 472 de 1998.",
                    "palabras_clave": ["acción de grupo", "causa común"],
                    "referencia_legal": "Artículo 88 de la Constitución Política; Ley 80 de 1993."}))
            else:
                salidas.append(json.dumps({"marco_normativo": "Constitución Política, artículo 88.",
                                           "analisis": "Primero. Segundo. Tercero.",
                                           "jurisprudencia": "No hay.", "conclusion": "Procede."}))
        return salidas


@pytest.fixture
def responder():
    return Responder(R.cargar_config(), RecuperadorFalso(), MotorFalso())


# ------------------------------------------------------------------ entrada libre
def test_extraer_opciones_en_lineas_y_en_una_sola_linea():
    enun, ops = extraer_opciones(CERRADA)
    assert enun.startswith("¿En qué caso") and list(ops) == ["A", "B", "C", "D"]
    assert ops["B"] == "Cuando un grupo es afectado por una causa común."
    enun2, ops2 = extraer_opciones("¿Cuál aplica? A) uno B) dos C) tres D) cuatro")
    assert enun2 == "¿Cuál aplica?" and ops2["C"] == "tres" and ops2["D"] == "cuatro"
    assert extraer_opciones("¿Qué es la tutela?") == ("¿Qué es la tutela?", {})
    assert extraer_opciones("Pregunta con A) una sola opción")[1] == {}        # faltan B y C


def test_extraer_opciones_une_lineas_de_continuacion():
    _, ops = extraer_opciones("¿Cuál?\nA) primera parte\n   que sigue\nB) b\nC) c")
    assert ops["A"] == "primera parte que sigue"


def test_preparar_item_deduce_el_formato():
    assert preparar_item(CERRADA)["formato"] == "multiple_choice"
    assert preparar_item(CERRADA)["opciones"]["A"].startswith("Para proteger")
    assert preparar_item("¿Qué es la tutela?")["formato"] == "semi_open"
    largo = "Una empresa contrata a una persona. " * 40
    assert preparar_item(largo)["formato"] == "open_ended"
    assert preparar_item("¿Qué es la tutela?", formato="open_ended")["formato"] == "open_ended"
    d = preparar_item({"id": 7, "pregunta": "¿Qué es?", "formato": "semi_open", "area": "Derecho civil"})
    assert d["id"] == 7 and d["area"] == "Derecho civil"


def test_preparar_item_rechaza_entradas_invalidas():
    with pytest.raises(ValueError):
        preparar_item("   ")
    with pytest.raises(ValueError):
        preparar_item("¿Cuál es?", formato="multiple_choice")             # cerrada sin opciones


# ------------------------------------------------------------------ texto de salida
def test_texto_respuesta_por_formato():
    mc = {"formato": "multiple_choice", "abstencion": False, "respuesta_correcta": "B",
          "justificacion": "Art. 46.", "descarte_opciones": {"A": "no", "C": "no", "D": "no"}}
    t = texto_respuesta(mc, {"opciones": {"B": "La causa común"}})
    assert t.startswith("Respuesta: B. La causa común") and "Por qué no las demás" in t
    semi = {"formato": "semi_open", "abstencion": False, "respuesta": "Es así.",
            "referencia_legal": "Ley 472", "palabras_clave": ["a", "b"]}
    assert "Referencia legal: Ley 472" in texto_respuesta(semi) and "Palabras clave: a, b" in texto_respuesta(semi)
    abierta = {"formato": "open_ended", "abstencion": False, "marco_normativo": "m", "analisis": "a",
               "jurisprudencia": "j", "conclusion": "c"}
    assert texto_respuesta(abierta).count("\n\n") == 3
    assert texto_respuesta({"formato": "semi_open", "abstencion": True}) == R.MENSAJE_ABSTENCION


def test_normas_citadas_marca_las_que_no_tienen_respaldo():
    sub = {"formato": "semi_open", "respuesta": "Aplica el artículo 88 de la Constitución Política.",
           "referencia_legal": "Ley 80 de 1993, artículo 5"}
    res = {n["norma"]: n["respaldada"] for n in normas_citadas(sub, PASAJES)}
    assert res["constitucion#art_88"] is True           # un pasaje trae la Constitución
    assert res["ley_80_1993#art_5"] is False            # ningún pasaje trae la Ley 80


# ------------------------------------------------------------------ Responder
def test_responder_cerrada_produce_una_entrega_valida(responder):
    r = responder.responder({"id": 51, "pregunta": CERRADA})
    sub = r["submission"]
    assert sub["respuesta_correcta"] == "B" and not sub["abstencion"] and r["formato"] == "multiple_choice"
    assert evaluate.validate([sub], {51}) == []                       # pasa la validación oficial
    assert r["respuesta"].startswith("Respuesta: B.") and len(r["pasajes"]) == 2
    assert {n["norma"] for n in r["normas_citadas"]} >= {"ley_472_1998#art_46"}


def test_responder_texto_libre_y_solo_recuperar(responder):
    r = responder.responder("¿Qué es la acción de grupo?")
    assert r["formato"] == "semi_open" and r["submission"]["id"] == 0
    s = responder.responder("¿Qué es la acción de grupo?", solo_recuperar=True)
    assert s["respuesta"] == "" and s["pasajes"] and "respuesta" not in s["submission"]


def test_responder_abstiene_si_el_decoder_no_produce_json(responder):
    class Roto(MotorFalso):
        def generar_lote(self, c, e, max_tokens=0):
            return ["esto no es json"] * len(e)
    r = Responder(R.cargar_config(), RecuperadorFalso(), Roto()).responder("¿Qué es la tutela?")
    assert r["abstencion"] is True and r["respuesta"] == R.MENSAJE_ABSTENCION
    assert r["pasajes"]                                                # la interfaz igual muestra lo recuperado


def test_gancho_de_verificacion_se_usa_si_existe(responder, monkeypatch):
    import src.verificacion as v
    monkeypatch.setattr(v, "aplicar", lambda sub, rec: {**sub, "verificada": True}, raising=False)
    assert responder.responder("¿Qué es la acción de grupo?")["submission"]["verificada"] is True


# ------------------------------------------------------------------ verificación en vivo
def test_buscar_por_id_y_comparar(responder, tmp_path):
    ruta = tmp_path / "preguntas.jsonl"
    ruta.write_text(json.dumps({"id": 51, "pregunta": CERRADA}) + "\n", encoding="utf-8")
    assert buscar_por_id(51, [tmp_path / "no_existe.jsonl", ruta])["id"] == 51
    assert buscar_por_id(99, [ruta]) is None
    vivo = responder.responder(buscar_por_id(51, [ruta]))
    entregado = {**vivo["submission"], "latencia_ms": 999999}          # la latencia no cuenta
    c = comparar(vivo, entregado)
    assert c["normas_coinciden"] and c["pasajes_coinciden"] and c["mismo_orden"] and c["respuesta_identica"]
    alterado = {**entregado, "pasajes_recuperados": entregado["pasajes_recuperados"][:1],
                "justificacion": "Ley 100 de 1993, artículo 1."}
    d = comparar(vivo, alterado)
    assert not d["normas_coinciden"] and not d["pasajes_coinciden"] and not d["respuesta_identica"]
    assert d["solo_en_entrega"]


# ------------------------------------------------------------------ API
fastapi = pytest.importorskip("fastapi")


@pytest.fixture
def cliente(responder):
    from fastapi.testclient import TestClient
    from src.api import crear_app
    with TestClient(crear_app(responder)) as c:
        yield c


def test_api_consulta_devuelve_lo_que_lee_la_interfaz(cliente):
    r = cliente.post("/api/consulta", json={"pregunta": CERRADA})
    assert r.status_code == 200
    d = r.json()
    assert d["respuesta"].startswith("Respuesta: B.") and d["formato"] == "multiple_choice"
    assert d["abstencion"] is False and len(d["pasajes"]) == 2 and d["pasajes"][0]["doc_id"] == "constitucion"
    assert d["normas_citadas"] and "latencia_ms" in d and "senales" in d


def test_api_valida_la_entrada(cliente):
    assert cliente.post("/api/consulta", json={"pregunta": ""}).status_code == 422
    assert cliente.post("/api/consulta", json={"pregunta": "   "}).status_code == 422
    assert cliente.post("/api/consulta", json={}).status_code == 422
    assert cliente.post("/api/consulta", json={"pregunta": "¿Cuál es?", "formato": "multiple_choice"}
                        ).status_code == 422                            # cerrada sin opciones
    assert cliente.post("/api/consulta", json={"pregunta": "x" * 7000}).status_code == 422
    assert cliente.post("/api/consulta", json={"pregunta": "¿Qué es?", "formato": "otro"}).status_code == 422


def test_api_salud_y_pagina(cliente):
    assert cliente.get("/api/salud").json()["estado"] == "ok"
    pagina = cliente.get("/")
    assert pagina.status_code == 200 and "Oliv-IA" in pagina.text


def test_api_acepta_formato_y_opciones_explicitos(cliente):
    r = cliente.post("/api/consulta", json={"pregunta": "¿Cuál procede?", "formato": "multiple_choice",
                                            "opciones": {"A": "uno", "B": "dos", "C": "tres", "D": "cuatro"}})
    assert r.status_code == 200 and r.json()["formato"] == "multiple_choice"
