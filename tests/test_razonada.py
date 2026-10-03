"""Estrategia "razonada" para cerradas y texto libre, sin GPU (decoder falso)."""
import pytest

import src.generacion  # noqa: F401  (agrega scripts/ al path)
from src.generacion import cerradas_razonar as cr
from src.generacion.pipeline import estrategia_activa, generar_lote
from tests.falsos import MotorFalso, MotorRazona

OPC = {"A": "Para proteger derechos individuales.",
       "B": "Cuando un grupo es afectado por una causa común.",
       "C": "Para anular una ley.", "D": "Para cobrar una deuda."}
MC = {"id": 51, "formato": "multiple_choice", "area": "Derecho constitucional",
      "pregunta": "¿En qué caso procede la acción de grupo?", "opciones": OPC}
PASAJES = [
    {"doc_id": "ley_472_1998", "texto": "Artículo 46 de la Ley 472 de 1998. Procedencia de la "
     "acción de grupo.", "inicio": 0, "fin": 80, "score": 3.0, "via": "directo"},
    {"doc_id": "constitucion", "texto": "Artículo 88 de la Constitución Política.", "inicio": 0,
     "fin": 40, "score": 2.0, "via": "opcion", "opcion": "B"},
    {"doc_id": "ley_80_1993", "texto": "Artículo 5 de la Ley 80 de 1993.", "inicio": 0, "fin": 40,
     "score": 1.0, "via": "opcion", "opcion": "C"},
]


def test_ordenes_son_rotaciones_y_el_mapeo_vuelve_a_la_letra_original():
    ords = cr.ordenes(["A", "B", "C", "D"], 4)
    assert ords == [list("ABCD"), list("BCDA"), list("CDAB"), list("DABC")]
    assert cr.ordenes(["A", "B", "C", "D"], 2) == [list("ABCD"), list("BCDA")]
    it, nueva_a_orig, orig_a_nueva = cr._item_permutado(MC, list("BCDA"))
    assert it["opciones"]["A"] == OPC["B"] and nueva_a_orig["A"] == "B" and orig_a_nueva["B"] == "A"
    ps = cr._pasajes_permutados(PASAJES, orig_a_nueva)
    assert [p.get("opcion") for p in ps] == [None, "A", "B"]       # B->A, C->B
    assert PASAJES[1]["opcion"] == "B"                              # no muta los originales


def test_permutable_solo_con_opciones_simples():
    assert cr.permutable(OPC)
    assert not cr.permutable({**OPC, "D": "Todas las anteriores."})
    assert not cr.permutable({**OPC, "C": "(a) y (b)", "D": "Ninguna de las anteriores."})


def test_decidir_politicas():
    p_ens = {"A": 0.1, "B": 0.2, "C": 0.6, "D": 0.1}
    an = {l: {"veredicto": "incorrecta", "razon": "x"} for l in "ABCD"}
    an["C"]["veredicto"] = "correcta"
    assert cr.decidir("razonada", OPC, an, "B", p_ens, "C")[0] == "B"
    assert cr.decidir("ens", OPC, an, "B", p_ens, "C")[0] == "C"
    assert cr.decidir("voto", OPC, an, "B", p_ens, "C") == ("B", "razonada")   # P(B)=0.2 > 0.15
    assert cr.decidir("voto", OPC, an, "B", {**p_ens, "B": 0.1, "A": 0.2}, None) == ("C", "voto_ens")
    assert cr.decidir("voto", OPC, an, "C", p_ens, None) == ("C", "razonada")  # ya coinciden
    assert cr.decidir("resolver", OPC, an, "B", p_ens, None)[0] == "C"        # el veredicto manda
    assert cr.decidir("razonada", OPC, an, "Z", None, None)[0] is None         # letra inválida


def test_responder_razonada_devuelve_salida_ensamblable():
    motor = MotorRazona("B")
    salida = cr.responder(MC, PASAJES, motor, politica="razonada")
    assert salida["respuesta_correcta"] == "B"
    d = salida["decision_cerrada"]
    assert d["letra_ens"] == "B" and d["letra_razonada"] == "B" and d["letra_final"] == "B"
    assert len(d["p_permutaciones"]) == 4 and abs(sum(d["p_ens"].values()) - 1) < 1e-6
    assert "descarte_opciones" in salida and "B" not in salida["descarte_opciones"]
    # un solo reinicio por ítem: la primera llamada reinicia; las demás reutilizan el prefijo
    assert [r for _, r in motor.llamadas].count(True) == 1 and motor.llamadas[0][1] is True


def test_voto_corrige_con_desacuerdo_fuerte_del_ensamble():
    motor = MotorRazona("A")                    # el razonamiento se equivoca; las permutaciones no
    motor.probabilidades_letras = lambda m, letras, reiniciar=True: {
        l: (0.85 if l == MotorRazona._letra_de(m) else 0.05) for l in letras}
    salida = cr.responder(MC, [dict(p) for p in PASAJES], motor, politica="voto")
    assert salida["decision_cerrada"]["letra_ens"] == "B"
    assert salida["decision_cerrada"]["regla"] == "voto_ens"
    assert salida["respuesta_correcta"] == "B"
    assert salida["justificacion"]              # la de la opción elegida, no vacía


def test_estrategia_razonada_en_el_pipeline():
    res = generar_lote([MC], {51: PASAJES}, MotorRazona("B"), estrategia="razonada",
                       senales_por_id={51: {"score_top1": 3.0}})[0]
    assert res["abstencion"] is False and res["respuesta_correcta"] == "B"
    assert res["decision_cerrada"]["estrategia"] == "razonada"
    assert set(res["descarte_opciones"]) == {"A", "C", "D"}
    assert len(res["pasajes_recuperados"]) <= 10


def test_estrategia_razonada_con_decoder_sin_pensar_cae_al_camino_actual():
    res = generar_lote([MC], {51: PASAJES}, MotorFalso(), estrategia="razonada")[0]
    assert res["respuesta_correcta"] == "B" and "decision_cerrada" in res   # el de la gramática actual


def test_texto_libre_usa_el_prompt_por_subtarea():
    capturado = []

    class Motor(MotorFalso):
        def generar_lote(self, conv, esq, max_tokens=0, repeat_penalty=None):
            capturado.append((conv[0][-1]["content"], max_tokens))
            return super().generar_lote(conv, esq, max_tokens)

    semi = {"id": 7, "formato": "semi_open", "area": "Derecho civil",
            "sub_tarea": "Definición básica", "complejidad": "low",
            "pregunta": "¿Cómo se define el litisconsorcio facultativo?"}
    res = generar_lote([semi], {7: PASAJES}, Motor(), estrategia="razonada")[0]
    assert "definicion" in capturado[0][0].lower() and "Máximo 60 palabras" in capturado[0][0]
    assert capturado[0][1] == 450 and res["formato"] == "semi_open"
    abierta = {"id": 9, "formato": "open_ended", "area": "Derecho penal", "pregunta": "Analice el caso."}
    generar_lote([abierta], {9: PASAJES}, Motor(), estrategia="razonada")
    assert "no escribas que no hay jurisprudencia" in capturado[1][0]


def test_estrategia_activa(monkeypatch):
    monkeypatch.delenv("OLIVIA_ESTRATEGIA", raising=False)
    assert estrategia_activa() == "actual" and estrategia_activa("razonada") == "razonada"
    monkeypatch.setenv("OLIVIA_ESTRATEGIA", "razonada")
    assert estrategia_activa() == "razonada"
    with pytest.raises(ValueError):
        estrategia_activa("otra")


def test_estrategia_actual_no_cambia():
    a = generar_lote([MC], {51: PASAJES}, MotorFalso(), estrategia="actual")[0]
    b = generar_lote([MC], {51: PASAJES}, MotorFalso())[0]
    a.pop("latencia_ms"), b.pop("latencia_ms")
    assert a == b


def test_literal_no_llama_al_modelo():
    from tests.test_subtarea import ART_113
    semi = {"id": 865, "formato": "semi_open", "sub_tarea": "Reproducción literal",
            "pregunta": "¿Qué dice el artículo 113 del Código Civil en relación al matrimonio?"}

    class Motor(MotorFalso):
        def generar_lote(self, *a, **k):
            raise AssertionError("no debía generar")
    res = generar_lote([semi], {865: [ART_113]}, Motor(), estrategia="razonada")[0]
    assert res["abstencion"] is False and res["respuesta"].startswith("Artículo 113 del Código Civil: «El matrimonio")
