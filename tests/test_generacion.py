"""Pruebas de la fase 7 sin GPU ni vLLM."""
import json
from pathlib import Path

import pytest

import src.generacion  # noqa: F401  (agrega scripts/ al path)
from src.generacion import contexto_prueba
from src.generacion.ejemplos import EJEMPLOS
from src.generacion.esquemas import ESQUEMAS, esquema
from src.generacion.pipeline import generar_lote, preparar
from src.generacion.postproceso import (contar_palabras, ensamblar, normalizar, parsear_json,
                                        recortar)
from src.generacion.prompts import construir_mensajes, formatear_pasajes

MC = {"id": 51, "formato": "multiple_choice", "area": "Derecho constitucional",
      "pregunta": "¿En cuál caso procede la acción de grupo?",
      "opciones": {"A": "uno", "B": "dos", "C": "tres", "D": "cuatro"}}
SEMI = {"id": 7, "formato": "semi_open", "area": "Derecho civil", "pregunta": "¿Qué es la mora?"}
ABIERTA = {"id": 9, "formato": "open_ended", "area": "Derecho penal", "pregunta": "Analice."}
PASAJES = [{"doc_id": "ley_472_1998", "texto": "Artículo 3o. Acciones de grupo. " * 5,
            "inicio": 0, "fin": 100, "score": 0.9}]


def test_recortar_respeta_oraciones_y_citas():
    texto = ("Según el art. 88 de la Constitución, procede la acción de grupo. "
             "La Ley 472 de 1998 la desarrolla. Tercera oración. Cuarta oración. Quinta oración. "
             "Sexta oración.")
    r = recortar(texto, 5)
    # 5 oraciones exactas: "art." no cuenta como fin de oración y la sexta se descarta
    assert "art. 88" in r and "Quinta" in r and "Sexta" not in r
    largo = recortar("palabra " * 300 + "fin.", 5, 150)
    assert contar_palabras(largo) <= 150 and largo.endswith(".")
    assert contar_palabras(recortar("Una. " + "x " * 200 + ". Otra.", 5, 150)) <= 150
    assert recortar("", 3, 10) == ""


def test_parsear_json_tolerante():
    assert parsear_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parsear_json("sin json") is None
    assert parsear_json('{"a": ') is None
    assert parsear_json("[1,2]") is None


def test_normalizar_multiple_choice():
    out = normalizar(MC, {"justificacion": "Art. 88 C.P.", "respuesta_correcta": "c)",
                          "descarte_opciones": {"A": "no", "B": "tampoco", "C": "x"}})
    assert out["respuesta_correcta"] == "C"
    assert set(out["descarte_opciones"]) == {"A", "B", "D"}          # sin la elegida, con D completada
    assert out["descarte_opciones"]["D"]
    assert normalizar(MC, {"respuesta_correcta": "Z"})["respuesta_correcta"] is None


def test_normalizar_semi_y_abierta():
    s = normalizar(SEMI, {"respuesta": "Una. Dos. Tres. Cuatro. Cinco. Seis. Siete.",
                          "palabras_clave": ["mora", "Mora", " ", "deudor"],
                          "referencia_legal": "art. 1608"})
    assert s["respuesta"].count(". ") == 4 and s["palabras_clave"] == ["mora", "deudor"]
    a = normalizar(ABIERTA, {"marco_normativo": "m", "analisis": " ".join(f"O{i}." for i in range(12)),
                             "jurisprudencia": "j", "conclusion": "c"})
    assert len(a["analisis"].split()) == 8


def test_ensamblar_valido_y_abstencion():
    ok = ensamblar(SEMI, {"respuesta": "Es el retardo. Genera perjuicios. Art. 1608.",
                          "palabras_clave": ["mora"], "referencia_legal": "art. 1608 C.C."},
                   PASAJES, latencia_ms=5)
    assert ok["abstencion"] is False and ok["pasajes_recuperados"][0]["doc_id"] == "ley_472_1998"
    assert ok["latencia_ms"] == 5
    for caso in (ensamblar(SEMI, None, PASAJES), ensamblar(SEMI, {"respuesta": "x"}, PASAJES)):
        # la abstención conserva la evidencia (como el ítem 218 del ejemplo de entrega)
        assert caso["abstencion"] is True and caso["pasajes_recuperados"][0]["doc_id"] == "ley_472_1998"
    sin = ensamblar(SEMI, {"respuesta": "x", "palabras_clave": ["a"], "referencia_legal": "r"}, [])
    assert sin["abstencion"] is True and sin["pasajes_recuperados"] == []
    mc = ensamblar(MC, {"respuesta_correcta": "Q", "justificacion": "j"}, PASAJES)
    # una cerrada nunca se abstiene si hay pasajes (fase 8.4): la letra inválida se reemplaza
    assert mc["abstencion"] is False and mc["respuesta_correcta"] in MC["opciones"]


def test_ensamblar_limita_a_10_pasajes():
    muchos = [{"doc_id": f"d{i}", "texto": "t"} for i in range(15)]
    s = ensamblar(SEMI, {"respuesta": "Una oración.", "palabras_clave": ["a"],
                         "referencia_legal": "r"}, muchos)
    assert len(s["pasajes_recuperados"]) == 10


def test_esquemas_coinciden_con_el_schema_oficial():
    oficial = json.loads(Path("schema/submission.schema.json").read_text(encoding="utf-8"))
    requeridos = {b["if"]["properties"]["formato"]["const"]: set(b["then"]["required"])
                  for b in oficial["allOf"]}
    for formato, esq in ESQUEMAS.items():
        assert set(esq["required"]) == requeridos[formato]
    assert esquema("semi_open") is ESQUEMAS["semi_open"]
    with pytest.raises(ValueError):
        esquema("otro")


def test_formatear_pasajes_respeta_presupuesto():
    pas = [{"doc_id": f"d{i}", "texto": "palabra " * 400} for i in range(10)]
    texto, usados = formatear_pasajes(pas, presupuesto_tokens=1500)
    assert 1 <= len(usados) < 10 and texto.startswith("[P1] d0")
    solo, u = formatear_pasajes([{"doc_id": "x", "texto": "palabra " * 5000}], presupuesto_tokens=300)
    assert len(u) == 1 and len(solo) <= 300 * 3.5 + 20             # siempre incluye el primero, truncado


def test_construir_mensajes_incluye_opciones_y_pasajes():
    msgs = construir_mensajes(MC, "[P1] ley_472_1998\ntexto")
    assert msgs[0]["role"] == "system" and msgs[-1]["role"] == "user"
    u = msgs[-1]["content"]
    assert "A. uno" in u and "D. cuatro" in u and "[P1] ley_472_1998" in u and "descarte_opciones" in u
    assert "Opciones" not in construir_mensajes(SEMI, "")[-1]["content"]
    with pytest.raises(ValueError):
        construir_mensajes({"formato": "x", "pregunta": "p"}, "")


class MotorFalso:
    """Devuelve JSON fijo por formato, para probar el pipeline sin vLLM."""
    def generar_lote(self, conversaciones, esquemas, max_tokens=0):
        salidas = []
        for esq in esquemas:
            if "descarte_opciones" in esq["properties"]:
                salidas.append(json.dumps({"justificacion": "Art. 88 C.P.", "respuesta_correcta": "C",
                                           "descarte_opciones": {"A": "x", "B": "y", "D": "z"}}))
            elif "palabras_clave" in esq["properties"]:
                salidas.append(json.dumps({"respuesta": "Es la regla. Se aplica.",
                                           "palabras_clave": ["a", "b"], "referencia_legal": "art. 1"}))
            else:
                salidas.append("no es json")
        return salidas


def test_pipeline_con_motor_falso():
    items = [MC, SEMI, ABIERTA]
    subs = generar_lote(items, {51: PASAJES, 7: PASAJES, 9: PASAJES}, MotorFalso())
    assert [s["id"] for s in subs] == [51, 7, 9]
    assert subs[0]["respuesta_correcta"] == "C" and not subs[0]["abstencion"]
    assert not subs[1]["abstencion"]
    assert subs[2]["abstencion"] is True                           # salida no parseable -> abstención válida
    msgs, esq, usados = preparar(MC, PASAJES)
    assert esq is ESQUEMAS["multiple_choice"] and usados == PASAJES


class MotorConReintento:
    """Primera pasada: abierta con JSON inválido. Segunda (con repeat_penalty): salida completa."""
    def __init__(self):
        self.llamadas = []

    def generar_lote(self, conversaciones, esquemas, max_tokens=0, repeat_penalty=1.0):
        self.llamadas.append((len(conversaciones), max_tokens, repeat_penalty))
        if len(self.llamadas) == 1:
            return ['{"marco_normativo": "art. 1", "analisis": "corta']
        return [json.dumps({"marco_normativo": "art. 1", "analisis": "Se aplica.",
                            "jurisprudencia": "Sin sentencias.", "conclusion": "Procede."})]


def test_pipeline_reintenta_salida_invalida_con_repeat_penalty():
    motor = MotorConReintento()
    sub = generar_lote([ABIERTA], {9: PASAJES}, motor)[0]
    assert not sub["abstencion"] and sub["conclusion"] == "Procede."
    assert motor.llamadas == [(1, 1100, 1.0), (1, 1100, 1.2)]


def test_pipeline_conserva_abstencion_si_el_reintento_tambien_falla():
    class Siempre:
        def generar_lote(self, conversaciones, esquemas, max_tokens=0, repeat_penalty=1.0):
            return ["no es json"] * len(conversaciones)
    assert generar_lote([ABIERTA], {9: PASAJES}, Siempre())[0]["abstencion"] is True


def test_ejemplos_few_shot_cumplen_el_esquema_de_su_formato():
    assert set(EJEMPLOS) == set(ESQUEMAS)
    for formato, turnos in EJEMPLOS.items():
        assert [t["role"] for t in turnos] == ["user", "assistant"]
        assert "=== PASAJES ===" in turnos[0]["content"]
        respuesta = json.loads(turnos[1]["content"])
        assert set(respuesta) == set(ESQUEMAS[formato]["required"])


def test_preparar_incluye_few_shot_por_defecto_y_se_puede_desactivar():
    con_ejemplos, _, _ = preparar(MC, PASAJES)
    assert len(con_ejemplos) == 4                    # system, user-ejemplo, assistant-ejemplo, user real
    assert [m["role"] for m in con_ejemplos] == ["system", "user", "assistant", "user"]
    assert con_ejemplos[-1]["content"] != con_ejemplos[1]["content"]   # la consulta real, no el ejemplo

    sin_ejemplos, _, _ = preparar(MC, PASAJES, ejemplos={})
    assert len(sin_ejemplos) == 2 and [m["role"] for m in sin_ejemplos] == ["system", "user"]


def test_contexto_oraculo_y_bm25():
    chunks = [
        {"chunk_id": "a", "doc_id": "ley_472_1998", "norma_id_canonico": "ley_472_1998#art_46",
         "texto": "Artículo 46. Procedencia de la acción de grupo por perjuicios", "inicio": 0, "fin": 9,
         "areas": ["constitucional"]},
        {"chunk_id": "b", "doc_id": "codigo_civil", "norma_id_canonico": "codigo_civil#art_1608",
         "texto": "Artículo 1608. El deudor está en mora cuando no ha cumplido", "inicio": 0, "fin": 9,
         "areas": ["civil"]},
    ]
    item = {"id": 1, "legal_basis": "Ley 472 de 1998, artículos 46."}
    assert "ley_472_1998#art_46" in contexto_prueba.ids_de_legal_basis(item["legal_basis"])
    assert [p["doc_id"] for p in contexto_prueba.oraculo(item, chunks)] == ["ley_472_1998"]
    bm = contexto_prueba.BM25Simple(chunks)
    assert bm.buscar("deudor en mora", k=1)[0]["doc_id"] == "codigo_civil"
    assert bm.buscar("palabra inexistente zzz") == []


class MotorQueFallaUnaVez(MotorFalso):
    """La primera llamada corta el JSON de la abierta; el reintento lo devuelve completo."""
    def __init__(self):
        self.llamadas = []

    def generar_lote(self, conversaciones, esquemas, max_tokens=0, repeat_penalty=None):
        self.llamadas.append((len(conversaciones), max_tokens, repeat_penalty))
        if len(self.llamadas) == 1:
            return ['{"marco_normativo": "Ley 472 de 1998"'] * len(conversaciones)
        return [json.dumps({"marco_normativo": "Ley 472 de 1998", "analisis": "Procede.",
                            "jurisprudencia": "Ninguna.", "conclusion": "Sí."})] * len(conversaciones)


def test_pipeline_reintenta_las_salidas_fallidas():
    motor = MotorQueFallaUnaVez()
    [s] = generar_lote([ABIERTA], {9: PASAJES}, motor)
    assert s["abstencion"] is False and s["conclusion"] == "Sí."
    assert motor.llamadas == [(1, 1100, None), (1, 1100, 1.2)]   # mismo tope + repeat_penalty
