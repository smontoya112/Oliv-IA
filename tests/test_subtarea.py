"""Router de sub-tareas del texto libre (src.generacion.subtarea)."""
import pytest

import src.generacion  # noqa: F401
from src.generacion import subtarea as st


@pytest.mark.parametrize("nombre,clave", [
    ("Definición básica", "definicion"), ("Reproducción literal", "literal"),
    ("Precedente jurisprudencial", "precedente"), ("Requisitos legales", "requisitos"),
    ("Existencia normativa", "existencia"), ("Elemento esencial", "elementos"),
    ("Fundamento jurídico central (ratio decidendi)", "ratio"), ("Problema jurídico", "problema"),
    ("Antecedentes fácticos", "antecedentes"), ("Conflicto normativo", "conflicto"),
    ("Jerarquía legal", "jerarquia"), ("Distinción conceptual", "distincion"),
    ("Supuestos fácticos", "caso"), (None, None), ("algo raro", None)])
def test_normalizar_nombre(nombre, clave):
    assert st.normalizar_nombre(nombre) == clave


@pytest.mark.parametrize("pregunta,clave", [
    ("¿Qué dice el artículo 113 del Código Civil en relación al matrimonio?", "literal"),
    ("Cité un fragmento de el artículo 60 del código sustantivo del trabajo que menciona la "
     "prohibición", "literal"),
    ("¿Cuál es el problema jurídico abordado en la sentencia SU-455 de 2020 de la Corte "
     "Constitucional?", "problema"),
    ("¿Existe alguna norma en el ordenamiento jurídico colombiano que regule el acoso laboral?",
     "existencia"),
    ("¿Cómo se define el litisconsorcio facultativo?", "definicion"),
    ("¿Qué se requiere para que un aborto sea no punible bajo las causales de la Sentencia "
     "C-355 de 2006?", "requisitos"),
    ("¿Cuál fue el fundamento jurídico central de la sentencia C-891 del 2012?", "ratio"),
    ("¿Cuáles son las principales diferencias entre la función ejecutiva y judicial del Estado?",
     "distincion"),
    ("Una empresa contrata a una persona mediante una Cooperativa de Trabajo Asociado para que "
     "preste servicios de asesoría jurídica exclusivamente para ella, en horario fijo de lunes a "
     "viernes de 8:00 a.m. a 5:00 p.m., bajo instrucciones directas del gerente, durante varios "
     "años y sin autonomía alguna. ¿Existe una relación laboral con las prestaciones del caso?",
     "caso"),
])
def test_inferir(pregunta, clave):
    assert st.inferir(pregunta, None) == clave


def test_plan_prefiere_la_subtarea_dada_y_cae_a_la_complejidad():
    item = {"formato": "semi_open", "pregunta": "¿Qué es la mora?", "sub_tarea": "Reproducción literal"}
    assert st.plan(item)["clave"] == "literal" and st.plan(item)["palabras"] == 120
    sin = {"formato": "semi_open", "pregunta": "Hable de algo.", "complejidad": "high"}
    assert st.plan(sin)["clave"] == "caso"
    largo = {"formato": "semi_open", "sub_tarea": "Problema jurídico",
             "pregunta": " ".join(["hecho"] * 60)}
    assert st.clave(largo) == "caso"        # problema jurídico planteado como caso, sin sentencia


def test_instrucciones_y_limites():
    semi = {"formato": "semi_open", "pregunta": "¿Existe alguna norma sobre el acoso laboral?"}
    txt = st.instrucciones(semi)
    assert "Empieza con \"Sí\" o \"No\"" in txt and "Máximo 45 palabras" in txt
    assert st.limites(semi) == (3, 56)
    abierta = {"formato": "open_ended", "pregunta": "Analice."}
    assert "marco_normativo" in st.instrucciones(abierta) and st.limites(abierta) == (8, None)


ART_113 = {"doc_id": "ley_84_1873", "norma_id": "ley_84_1873#art_113", "via": "directo",
           "texto": "Artículo 113 del Código Civil (Ley 57 de 1887). Libro Primero > Título IV. DEFINICIÓN.\n"
                    "ARTÍCULO 113. {{DEFINICIÓN}}. {{Ver Notas del Editor}} El matrimonio es un contrato "
                    "solemne por el cual un hombre y una mujer se unen con el fin de vivir juntos."}
ART_60 = {"doc_id": "cst", "norma_id": "codigo_sustantivo_trabajo#art_60", "via": "directo",
          "texto": "Artículo 60 de la Código Sustantivo del Trabajo (Decretos 2663 de 1950). Título I.\n"
                   "ARTICULO 60. PROHIBICIONES A LOS TRABAJADORES. Se prohibe a los trabajadores:\n\n"
                   "1. Sustraer de la fábrica los útiles de trabajo. Sin permiso del {empleador}.\n\n"
                   "2. {{Numeral CONDICIONALMENTE exequible}} Presentarse al trabajo en estado de embriaguez.\n\n"
                   "5. Disminuir intencionalmente el ritmo de ejecución del trabajo o suspender labores."}


def test_literal_copia_el_articulo_sin_notas_ni_titulo():
    item = {"formato": "semi_open", "pregunta": "¿Qué dice el artículo 113 del Código Civil en relación al matrimonio?"}
    r = st.literal(item, [ART_113])
    assert r["respuesta"] == ("Artículo 113 del Código Civil: «El matrimonio es un contrato solemne por el "
                              "cual un hombre y una mujer se unen con el fin de vivir juntos.»")
    assert r["referencia_legal"] == "Artículo 113 del Código Civil"


def test_literal_elige_el_numeral_por_numero_o_por_contenido():
    por_contenido = {"formato": "semi_open", "pregunta": "Cité un fragmento de el artículo 60 del código "
                     "sustantivo del trabajo que menciona la prohibición de disminuir el ritmo de trabajo."}
    r = st.literal(por_contenido, [ART_60])
    assert r["respuesta"].startswith("Numeral 5 del artículo 60 del código sustantivo del trabajo: «Disminuir")
    por_numero = {"formato": "semi_open", "pregunta": "Transcriba el numeral 2 del artículo 60 del Código "
                  "Sustantivo del Trabajo."}
    assert "embriaguez" in st.literal(por_numero, [ART_60])["respuesta"]
    assert "Numeral CONDICIONALMENTE" not in st.literal(por_numero, [ART_60])["respuesta"]


def test_literal_devuelve_none_si_el_articulo_no_esta():
    item = {"formato": "semi_open", "pregunta": "¿Qué dice el artículo 999 del Código Civil?"}
    assert st.literal(item, [ART_113]) is None
    assert st.literal({"formato": "semi_open", "pregunta": "Sin artículo."}, [ART_113]) is None
