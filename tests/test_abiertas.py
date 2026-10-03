"""Abiertas: preguntas del caso, tipo, plantilla, expansión de la recuperación y revisión (sin GPU)."""
import json

import src.generacion  # noqa: F401
from src.generacion import abiertas
from src.generacion.pipeline import generar_lote
from src.responder import recuperar_item
from tests.falsos import MotorFalso, PASAJES

CASO = ("El señor Gómez se movilizaba en bus a su trabajo cuando un árbol cayó sobre el bus. "
        "Ante esta situación: ¿Los accidentes ocurridos en el traslado se reconocen como accidentes laborales? "
        "¿Quién responde por las prestaciones que genera un hecho de fuerza mayor?")
ITEM = {"id": 253, "formato": "open_ended", "area": "Derecho laboral", "pregunta": CASO}


def test_preguntas_del_caso_en_orden():
    qs = abiertas.preguntas(CASO)
    assert qs == ["¿Los accidentes ocurridos en el traslado se reconocen como accidentes laborales?",
                  "¿Quién responde por las prestaciones que genera un hecho de fuerza mayor?"]


def test_preguntas_sin_signos_usa_la_oracion_que_pregunta():
    caso = "La alcaldía expide una resolución que afecta el parque. Ante esto, qué acción procede ante dicha situación."
    assert abiertas.preguntas(caso) == ["Ante esto, qué acción procede ante dicha situación."]
    assert abiertas.preguntas("") == []


def test_tipo_de_pregunta():
    assert abiertas.tipo("¿Qué acción procede ante dicha situación?") == "accion"
    assert abiertas.tipo("¿Quién responde por las prestaciones?") == "responsable"
    assert abiertas.tipo("¿Es posible que la empresa prohíba la venta por segunda vez?") == "viabilidad"
    assert abiertas.tipo("Explique el caso.") == "analisis"
    assert abiertas.tipos_del_caso(CASO) == ["analisis", "responsable"]


def test_instrucciones_numeran_las_preguntas_y_prohiben_el_relleno():
    txt = abiertas.instrucciones(ITEM)
    assert "2 pregunta(s)" in txt and "(1) ¿Los accidentes" in txt and "(2) ¿Quién responde" in txt
    assert "no escribas que no hay jurisprudencia" in txt and "una oración por pregunta" in txt
    assert "quién responde o a quién corresponde" in txt.lower()


def test_activas_por_env_y_por_config(monkeypatch):
    monkeypatch.delenv("OLIVIA_ABIERTAS", raising=False)
    assert abiertas.activas() == set()
    assert abiertas.activas({"abiertas": ["plantilla", "expansion", "otra"]}) == {"plantilla", "expansion"}
    monkeypatch.setenv("OLIVIA_ABIERTAS", "revision, plantilla")
    assert abiertas.activas({"abiertas": ["expansion"]}) == {"revision", "plantilla"}
    monkeypatch.setenv("OLIVIA_ABIERTAS", "")
    assert abiertas.activas({"abiertas": ["expansion"]}) == set()


class MotorConsultas(MotorFalso):
    def __init__(self, consultas=True):
        self.consultas, self.prompts = consultas, []

    def generar_lote(self, conversaciones, esquemas, max_tokens=0, repeat_penalty=None):
        if "problema_juridico" in esquemas[0]["properties"]:
            self.prompts.append(conversaciones[0][-1]["content"])
            return [json.dumps({"problema_juridico": "Si el accidente in itinere es laboral y quién responde.",
                                "consultas": ["accidente in itinere Ley 1562 de 2012",
                                              "responsabilidad ARL fuerza mayor"]}) if self.consultas else "no json"]
        return super().generar_lote(conversaciones, esquemas, max_tokens)


class RecuperadorExpandible:
    def __init__(self):
        self.llamadas = []

    def recuperar(self, item):
        return {"pasajes": [dict(PASAJES[0])], "senales": {"score_top1": 1.0}}

    def recuperar_expandido(self, item, extras, consulta_rerank=None):
        self.llamadas.append((extras, consulta_rerank))
        return {"pasajes": [dict(p) for p in PASAJES], "senales": {"score_top1": 4.0}}


def test_recuperar_expandido_usa_consultas_deducidas_y_rerank_corto(monkeypatch):
    monkeypatch.delenv("OLIVIA_ABIERTAS", raising=False)
    rec_orig = {"pasajes": [dict(PASAJES[0])], "senales": {"score_top1": 1.0}}
    motor, recuperador = MotorConsultas(), RecuperadorExpandible()
    rec = abiertas.recuperar_expandido(ITEM, rec_orig, motor, recuperador)
    extras, rerank = recuperador.llamadas[0]
    assert extras[0].startswith("Si el accidente in itinere") and "accidente in itinere Ley 1562 de 2012" in extras
    assert "¿Quién responde" in rerank and "Gómez" not in rerank           # solo problema + preguntas, no el relato
    assert len(rec["pasajes"]) == 2 and rec["senales"]["expansion"]["consultas"]
    assert "Gómez" in motor.prompts[0]                                      # el decoder ve el caso completo


def test_recuperar_expandido_si_el_decoder_falla_deja_la_recuperacion_original():
    rec_orig = {"pasajes": [dict(PASAJES[0])], "senales": {}}
    assert abiertas.recuperar_expandido(ITEM, rec_orig, MotorConsultas(consultas=False),
                                        RecuperadorExpandible()) is rec_orig


def test_recuperar_item_solo_expande_abiertas_con_razonada_y_la_pieza(monkeypatch):
    monkeypatch.delenv("OLIVIA_ABIERTAS", raising=False)
    monkeypatch.delenv("OLIVIA_ESTRATEGIA", raising=False)
    cfg = {"estrategia": "razonada", "abiertas": ["expansion"]}
    r1 = RecuperadorExpandible()
    assert len(recuperar_item(ITEM, r1, MotorConsultas(), cfg)["pasajes"]) == 2 and len(r1.llamadas) == 1
    for item, c in ((dict(ITEM, formato="semi_open"), cfg), (ITEM, {**cfg, "abiertas": []}),
                    (ITEM, {"estrategia": "actual", "abiertas": ["expansion"]})):
        r2 = RecuperadorExpandible()
        assert len(recuperar_item(item, r2, MotorConsultas(), c)["pasajes"]) == 1 and not r2.llamadas


class MotorRevisa(MotorFalso):
    def __init__(self, revision):
        self.revision, self.llamadas = revision, 0

    def generar_lote(self, conversaciones, esquemas, max_tokens=0, repeat_penalty=None):
        if "BORRADOR" in conversaciones[0][-1]["content"]:
            self.llamadas += 1
            return [json.dumps(self.revision)]
        return super().generar_lote(conversaciones, esquemas, max_tokens)


def _borrador():
    return {"marco_normativo": "Ley 1562 de 2012, artículo 3.", "analisis": " ".join(["Aplica la regla al caso."] * 30),
            "jurisprudencia": "Principio general.", "conclusion": "Sí se reconoce."}


def test_revisar_acepta_la_revision_y_rechaza_la_que_encoge_demasiado():
    ok = {**_borrador(), "analisis": " ".join(["Aplica la regla corregida al caso."] * 30)}
    esquema = {"type": "object"}
    assert abiertas.revisar(ITEM, _borrador(), "[P1] texto", MotorRevisa(ok), esquema) == ok
    corta = {**_borrador(), "analisis": "Corto."}
    assert abiertas.revisar(ITEM, _borrador(), "[P1] texto", MotorRevisa(corta), esquema) == _borrador()
    vacia = {**_borrador(), "conclusion": ""}
    assert abiertas.revisar(ITEM, _borrador(), "[P1] texto", MotorRevisa(vacia), esquema) == _borrador()


def test_pipeline_aplica_plantilla_y_revision_solo_a_las_abiertas():
    motor = MotorRevisa({**_borrador(), "conclusion": "Conclusión revisada."})
    r = generar_lote([ITEM], {253: PASAJES}, motor, estrategia="razonada", abiertas={"plantilla", "revision"})[0]
    assert motor.llamadas == 1 and r["conclusion"] == "Conclusión revisada."
    sin = MotorRevisa({})
    r2 = generar_lote([ITEM], {253: PASAJES}, sin, estrategia="razonada", abiertas=set())[0]
    assert sin.llamadas == 0 and r2["formato"] == "open_ended"
    semi = {"id": 7, "formato": "semi_open", "area": "Derecho civil", "pregunta": "¿Qué es la mora?"}
    sin2 = MotorRevisa({})
    generar_lote([semi], {7: PASAJES}, sin2, estrategia="razonada", abiertas={"plantilla", "revision"})
    assert sin2.llamadas == 0
