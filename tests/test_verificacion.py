"""Pruebas de la fase 8 (verificación de citas y abstención), sin GPU ni índices."""
import src.verificacion  # noqa: F401  (agrega scripts/ al path)
from src.generacion.postproceso import ensamblar
from src.recuperacion.catalogo import Catalogo
from src.verificacion import abstencion, aplicar, esquema
from src.verificacion.citas import cuerpos, quitar_citas, referencia, respaldo, verificar
from src.verificacion.orden import reordenar

SEMI = {"id": 7, "formato": "semi_open", "area": "Derecho civil", "pregunta": "¿Qué es la mora?"}
ABIERTA = {"id": 9, "formato": "open_ended", "area": "Derecho penal", "pregunta": "Analice."}
MC = {"id": 51, "formato": "multiple_choice", "pregunta": "¿Cuál?",
      "opciones": {"A": "uno", "B": "dos", "C": "tres", "D": "cuatro"}}

P472 = {"doc_id": "ley_472_1998", "chunk_id": "c472", "norma_id": "ley_472_1998#art_46",
        "texto": "Artículo 46 de la Ley 472 de 1998. Procedencia de las acciones de grupo.",
        "inicio": 0, "fin": 70, "score": 5.0}
RELLENO = [{"doc_id": f"d{i}", "chunk_id": f"r{i}", "texto": f"Texto sin normas número {i}.",
            "score": 1.0 - i / 100} for i in range(12)]
LEY_472 = ("ley", "472", "1998")
CC = ("codigo_civil", None, None)


def _catalogo():
    filas = [("cc1608", "codigo_civil", "codigo_civil#art_1608",
              "Artículo 1608 del Código Civil. El deudor está en mora cuando no ha cumplido."),
             ("cc1", "codigo_civil", "codigo_civil#art_1", "Artículo 1 del Código Civil. La ley.")]
    cols = {"chunk_id": [f[0] for f in filas], "doc_id": [f[1] for f in filas],
            "norma_id_canonico": [f[2] for f in filas], "areas": [["civil"]] * len(filas),
            "texto": [f[3] for f in filas], "inicio": [0] * len(filas), "fin": [10] * len(filas),
            "sha1_texto": [f[0] for f in filas]}
    return Catalogo.desde_columnas(cols)


def _semi(respuesta, ref):
    return {"respuesta": respuesta, "palabras_clave": ["mora"], "referencia_legal": ref}


def test_respaldo_por_cuerpo_en_los_10_primeros():
    assert LEY_472 in cuerpos(P472["texto"])
    assert respaldo([P472]) == {LEY_472}
    assert respaldo(RELLENO[:10] + [P472]) == set()               # posición 11: no cuenta
    assert referencia(P472) == "Artículo 46 de la Ley 472 de 1998"


def test_cita_respaldada_se_mantiene():
    campos = _semi("Según el artículo 46 de la Ley 472 de 1998, procede la acción.", "Ley 472 de 1998, art. 46")
    nuevos, top, rep = verificar(SEMI, campos, [P472] + RELLENO)
    assert nuevos == campos and len(top) == 10 and top[0] is P472
    assert rep["respaldadas"] == 1 and rep["sin_respaldo"] == 0 and not rep["eliminadas"]


def test_sin_catalogo_se_elimina_la_oracion():
    campos = _semi("Procede la acción de grupo. El artículo 1608 del Código Civil define la mora.",
                   "Ley 472 de 1998, art. 46; Código Civil, art. 1608")
    nuevos, top, rep = verificar(SEMI, campos, [P472])
    assert nuevos["respuesta"] == "Procede la acción de grupo."
    assert nuevos["referencia_legal"] == "Ley 472 de 1998, art. 46"
    assert rep["sin_respaldo"] == 0 and len(rep["eliminadas"]) == 2
    assert quitar_citas("Sin citas.", "respuesta", {CC}) == ("Sin citas.", [])


def test_con_catalogo_se_trae_el_pasaje_y_desplaza_al_peor():
    campos = _semi("El artículo 1608 del Código Civil define la mora.", "Código Civil, art. 1608")
    nuevos, top, rep = verificar(SEMI, campos, RELLENO[:10], _catalogo())
    assert nuevos == campos and rep["sin_respaldo"] == 0 and rep["insertadas"]
    assert len(top) == 10 and top[0]["chunk_id"] == "cc1608" and top[0]["via"] == "verificacion"
    assert "r9" not in {p["chunk_id"] for p in top}               # el de menor puntaje sale


def test_reordenar_sube_al_top10_el_pasaje_citado():
    top, nuevos = reordenar(RELLENO + [P472], {LEY_472})
    assert len(top) == 10 and top[0] is P472 and nuevos == []
    top, _ = reordenar(RELLENO, set())
    assert top == RELLENO[:10]


def test_campo_vaciado_se_rellena_con_la_referencia_del_top():
    campos = _semi("La mora es el retardo culpable.", "Código Civil, art. 1608")
    nuevos, _, rep = verificar(SEMI, campos, [P472])
    assert nuevos["referencia_legal"] == "Artículo 46 de la Ley 472 de 1998"
    assert rep["rellenados"] == ["referencia_legal"]


def test_cerrada_sin_salida_responde_con_la_evidencia_por_opcion():
    pasajes = [dict(P472), {**RELLENO[0], "opcion": "C", "score": 3.0},
               {**RELLENO[1], "opcion": "B", "score": 1.0}]
    s = ensamblar(MC, None, pasajes)
    assert s["abstencion"] is False and s["respuesta_correcta"] == "C"
    assert set(s["descarte_opciones"]) == {"A", "B", "D"} and "Ley 472 de 1998" in s["justificacion"]
    assert esquema.validar([s]) == []
    vacia = ensamblar(MC, None, [])                               # sin pasajes sí se abstiene...
    assert vacia["abstencion"] is True and vacia["respuesta_correcta"] in MC["opciones"]
    assert esquema.validar([vacia]) == []                         # ...con una letra válida para el schema


def test_politica_de_abstencion():
    campos = {"marco_normativo": "Sin normas.", "analisis": "Análisis.", "jurisprudencia": "Ninguna.",
              "conclusion": "Conclusión."}
    malo = {"score_top1": -3.0}
    assert abstencion.decidir(ABIERTA, campos, [P472], malo, {"respaldadas": 0}) == (False, "")
    assert abstencion.decidir(ABIERTA, campos, [P472], malo, {"respaldadas": 0}, umbral=0.0)[0]
    assert not abstencion.decidir(ABIERTA, campos, [P472], malo, {"respaldadas": 1}, umbral=0.0)[0]
    assert abstencion.decidir(ABIERTA, campos, [P472], {"error": "x"}) == (True, "error_recuperacion")
    assert abstencion.decidir(ABIERTA, None, [P472]) == (True, "generacion_fallida")
    s = ensamblar(ABIERTA, campos, [P472], senales=malo, umbral=0.0)
    assert s["abstencion"] is True and s["pasajes_recuperados"] and esquema.validar([s]) == []


def test_validar_detecta_errores_de_schema_y_de_reglas():
    ok = ensamblar(SEMI, _semi("Según la Ley 472 de 1998, procede.", "Ley 472 de 1998"), [P472])
    assert esquema.validar([ok]) == []
    mc_malo = {"id": 51, "formato": "multiple_choice", "abstencion": True, "respuesta_correcta": "",
               "justificacion": "", "descarte_opciones": {}, "pasajes_recuperados": []}
    assert any("respuesta_correcta" in p for p in esquema.validar([mc_malo]))
    sin_pasajes = {**ok, "pasajes_recuperados": []}
    assert any("sin pasajes_recuperados" in p for p in esquema.validar([sin_pasajes]))
    assert any("sin respuesta" in p for p in esquema.validar([ok], {7, 8}))


def test_aplicar_reensambla_con_los_pasajes_de_la_recuperacion():
    generada = {"id": 7, "formato": "semi_open", "abstencion": False, "latencia_ms": 3,
                **_semi("El artículo 1608 del Código Civil define la mora.", "Código Civil, art. 1608"),
                "pasajes_recuperados": [P472]}
    recuperada = {"id": 7, "pasajes": RELLENO[:10], "senales": {"score_top1": 1.0}}
    [s] = aplicar.aplicar([SEMI], {7: generada}, {7: recuperada}, _catalogo())
    assert s["abstencion"] is False and s["verificacion"]["insertadas"] and s["latencia_ms"] == 3
    assert aplicar.resumen([s], [])["citas_insertadas"] == 1


def test_nombre_cuerpo_ida_y_vuelta():
    import json
    from pathlib import Path

    import citations
    from src.verificacion.citas import nombre_cuerpo
    todos = {(c, None, None) for c in citations.CODES} | {LEY_472, ("jurisprudencia", "C-355", "2006")}
    ruta = Path("data/recuperacion/sample_50.jsonl")
    if ruta.exists():
        for linea in ruta.read_text(encoding="utf-8").splitlines():
            for p in json.loads(linea)["pasajes"]:
                todos |= cuerpos(p["texto"])
    for c in todos:
        assert cuerpos(nombre_cuerpo(c)) == {c}, c
    assert nombre_cuerpo(("ley", None, None)) is None


def test_completar_con_evidencia_por_formato():
    from src.verificacion.citas import completar_con_evidencia
    cc = {"doc_id": "cc", "texto": "Artículo 1608 del Código Civil. El deudor está en mora."}
    semi, agregadas = completar_con_evidencia(SEMI, _semi("La mora.", "Ley 472 de 1998"), [P472, cc])
    assert agregadas == ["Código Civil"] and semi["referencia_legal"] == "Ley 472 de 1998; Código Civil"
    assert semi["respuesta"] == "La mora."                        # el texto que juzga RAGAS no cambia
    mc, _ = completar_con_evidencia(MC, {"respuesta_correcta": "A", "justificacion": "Así es",
                                         "descarte_opciones": {}}, [cc])
    assert mc["justificacion"] == "Así es. Normas de los pasajes recuperados: Código Civil."
    ab, _ = completar_con_evidencia(ABIERTA, {"marco_normativo": "", "analisis": "a", "jurisprudencia": "j",
                                              "conclusion": "c"}, [cc])
    assert ab["marco_normativo"] == "Normas de los pasajes recuperados: Código Civil."
    assert completar_con_evidencia(SEMI, _semi("x", "Código Civil"), [cc]) == (_semi("x", "Código Civil"), [])
    assert completar_con_evidencia(SEMI, _semi("x", "r"), [cc], k=0)[1] == []
    assert completar_con_evidencia(SEMI, _semi("x", "r"), RELLENO[:3] + [cc], k=3)[1] == []   # fuera del top k


def test_ensamblar_guarda_salida_modelo_y_linea_base():
    salida = _semi("El artículo 1608 del Código Civil define la mora.", "Código Civil, art. 1608")
    s = ensamblar(SEMI, salida, [P472])
    assert s["salida_modelo"]["referencia_legal"] == "Código Civil, art. 1608"   # antes de la fase 8
    assert "Código Civil" not in s["referencia_legal"] and "Ley 472 de 1998" in s["referencia_legal"]
    base = ensamblar(SEMI, salida, [P472], fase8=False)
    assert base["referencia_legal"] == "Código Civil, art. 1608" and "verificacion" not in base
    [re] = aplicar.aplicar([SEMI], {7: s}, {7: {"pasajes": [P472]}}, fase8=False)
    assert re["referencia_legal"] == "Código Civil, art. 1608"   # se reconstruye desde salida_modelo
    assert ensamblar(MC, None, [], fase8=False)["abstencion"] is True
