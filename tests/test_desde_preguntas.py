"""Enriquecimiento del corpus desde las preguntas (src.descarga.desde_preguntas), sin red."""
from src.descarga import desde_preguntas as dp

ITEMS = [
    {"id": 1, "area": "Derecho civil", "formato": "semi_open",
     "pregunta": "Según el artículo 1608 del Código Civil, ¿cuándo hay mora? Explique."},
    {"id": 2, "area": "Derecho administrativo", "formato": "semi_open",
     "pregunta": "¿Qué dispone la Ley 2195 de 2022 sobre transparencia? Considere la Sentencia C-355 de 2006."},
    {"id": 3, "area": "Derecho laboral", "formato": "multiple_choice",
     "pregunta": "¿Qué dijo la Corte Suprema en la sentencia SL-1234 de 2020?",
     "opciones": {"A": "Lo previsto en la Ley 9999 de 2001", "B": "otra"}},
    {"id": 4, "area": "Derecho administrativo", "formato": "semi_open",
     "pregunta": "¿Cómo aplica la ley de contratación estatal? Responda brevemente."},
]
EN_CORPUS = {"ley_84_1873"}            # el Código Civil (clave del manifest)


def test_extrae_y_clasifica_lo_que_falta():
    res = dp.analizar(ITEMS, EN_CORPUS)
    por = {n["clave"]: n for n in res["normas"]}
    assert por["ley_84_1873"]["en_corpus"] and por["ley_84_1873"]["preguntas"] == [1]
    assert not por["ley_2195_2022"]["en_corpus"]
    ids = {f["doc_id"]: f for f in res["fuentes"]}
    assert ids["ley_2195_2022"]["url"].endswith("basedoc/ley_2195_2022.html")
    assert ids["ley_2195_2022"]["origen"] == "preguntas"
    assert ids["sentencia_c-355_2006"]["url"].endswith("relatoria/2006/C-355-06.htm")
    assert [p["canonico"] for p in res["pendientes"]] == [["jurisprudencia", "SL-1234", "2020"]]
    assert "ley_9999_2001" not in por                       # las opciones no se leen por defecto
    assert "ley_9999_2001" in {n["clave"] for n in dp.analizar(ITEMS, EN_CORPUS, con_opciones=True)["normas"]}


def test_fragmentos_y_sin_reconocer():
    res = dp.analizar(ITEMS, EN_CORPUS)
    frag = {r["id"]: r for r in res["fragmentos"]}
    assert frag[1]["fragmentos"][0]["citas"] == [["codigo_civil", None, None]]
    assert frag[1]["fragmentos"][0]["texto"].startswith("Según el artículo 1608")
    assert frag[4]["sin_reconocer"] == ["¿Cómo aplica la ley de contratación estatal?"]
    assert "Explique." not in [f["texto"] for f in frag[1]["fragmentos"]]   # solo oraciones con mención


def test_pendiente_sin_url_no_toma_la_busqueda_como_documento():
    res = dp.analizar([{"id": 9, "area": "Derecho administrativo",
                        "pregunta": "Aplique la Resolución 368 de 2014."}], set())
    assert res["fuentes"] == [] and res["pendientes"][0]["canonico"] == ["resolucion", "368", "2014"]
    assert "?q=" in res["pendientes"][0]["donde_buscar"]
