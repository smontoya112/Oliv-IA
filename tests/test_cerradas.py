"""Cerradas: análisis por opción, opciones compuestas y decisión determinista (sin GPU)."""
import src.generacion  # noqa: F401  (agrega scripts/ al path)
from src.generacion import cerradas
from src.generacion.esquemas import ESQUEMAS, esquema_item
from src.generacion.postproceso import ensamblar, normalizar
from src.generacion.prompts import construir_mensajes

OPCIONES = {"A": "uno", "B": "dos", "C": "tres", "D": "cuatro"}
P472 = [{"doc_id": "ley_472_1998", "texto": "Artículo 46 de la Ley 472 de 1998. Procedencia."}]


def _an(**v):
    """_an(A="c", B="i") -> análisis con veredictos correcta/incorrecta."""
    return {l: {"veredicto": "correcta" if x == "c" else "incorrecta", "razon": f"razón {l}"}
            for l, x in v.items()}


def test_clasificar_opciones_compuestas():
    t = cerradas.clasificar({"A": "(a) y (b)", "B": "El apoyo moral", "C": "Ninguna de las anteriores.",
                             "D": "B y C"})
    assert t["A"]["tipo"] == "simple"                  # se nombra a sí misma: ambigua (ítem 647)
    assert t["C"]["tipo"] == "ninguna"
    assert t["D"] == {"tipo": "combinacion", "refs": ["B", "C"]}
    assert cerradas.clasificar({"B": "Todas las anteriores."})["B"]["tipo"] == "todas"
    assert cerradas.clasificar({"A": "Ley y orden"})["A"]["tipo"] == "simple"
    assert "TODAS" in cerradas.nota_opcion({"tipo": "todas", "refs": []})
    assert cerradas.nota_opcion({"tipo": "simple", "refs": []}) == ""


def test_resolver_corrige_letra_que_contradice_los_veredictos():
    # ítem 51: el análisis respalda C pero la letra fue B
    assert cerradas.resolver(OPCIONES, _an(A="i", B="i", C="c", D="i"), "B") == ("C", "veredicto_unico")
    assert cerradas.resolver(OPCIONES, _an(A="i", B="c", C="c", D="i"), "B") == ("B", "modelo")
    assert cerradas.resolver(OPCIONES, _an(A="i", B="c", C="c", D="i"), "A") == ("B", "varias_correctas")
    assert cerradas.resolver(OPCIONES, _an(A="i", B="i", C="i", D="i"), "D") == ("D", "modelo_sin_veredictos")
    assert cerradas.resolver(OPCIONES, {}, "A") == ("A", "modelo_sin_veredictos")


def test_resolver_opciones_compuestas():
    op = {"A": "Conflicto residencia-fuente", "B": "Todas las anteriores.", "C": "Conflicto residencia-residencia",
          "D": "Conflicto fuente-fuente"}
    # ítem 671: el modelo marcó "Todas" pero solo C es correcta
    assert cerradas.resolver(op, _an(A="i", B="c", C="c", D="i"), "B") == ("C", "veredicto_unico")
    assert cerradas.resolver(op, _an(A="c", B="i", C="c", D="c"), "A") == ("B", "compuesta_todas")
    ninguna = {"A": "uno", "B": "dos", "C": "Ninguna de las anteriores.", "D": "cuatro"}
    assert cerradas.resolver(ninguna, _an(A="i", B="i", C="i", D="i"), "A") == ("C", "compuesta_ninguna")
    assert cerradas.resolver(ninguna, _an(A="i", B="c", C="c", D="i"), "C") == ("B", "veredicto_unico")
    combo = {"A": "uno", "B": "dos", "C": "tres", "D": "A y B"}
    assert cerradas.resolver(combo, _an(A="c", B="c", C="i", D="i"), "A") == ("D", "compuesta_combinacion")
    assert cerradas.resolver(combo, _an(A="c", B="i", C="i", D="c"), "D") == ("A", "veredicto_unico")


def test_esquema_pide_analisis_antes_de_la_letra():
    props = list(ESQUEMAS["multiple_choice"]["properties"])
    assert props == ["analisis_opciones", "justificacion", "respuesta_correcta"]
    tres = esquema_item({"formato": "multiple_choice", "opciones": {"A": "x", "B": "y", "C": "z"}})
    assert tres["properties"]["respuesta_correcta"]["enum"] == ["A", "B", "C"]
    assert tres["properties"]["analisis_opciones"]["required"] == ["A", "B", "C"]
    assert esquema_item({"formato": "multiple_choice", "opciones": OPCIONES}) is ESQUEMAS["multiple_choice"]


def test_prompt_marca_las_compuestas():
    item = {"formato": "multiple_choice", "pregunta": "¿Cuál?",
            "opciones": {"A": "uno", "B": "dos", "C": "Ninguna de las anteriores.", "D": "A y B"}}
    u = construir_mensajes(item, "[P1] x")[-1]["content"]
    assert "C. Ninguna de las anteriores. [opción compuesta: solo es correcta si NINGUNA" in u
    assert "D. A y B [opción compuesta: equivale a que A y B sean correctas" in u
    assert "B. dos\n" in u


def test_normalizar_y_ensamblar_con_analisis():
    item = {"id": 51, "formato": "multiple_choice", "pregunta": "¿Cuál?", "opciones": OPCIONES}
    salida = {"analisis_opciones": _an(A="i", B="i", C="c", D="i"),
              "justificacion": "Justificación escrita para B.", "respuesta_correcta": "B"}
    n = normalizar(item, salida)
    assert n["respuesta_correcta"] == "C" and n["justificacion"] == "razón C"   # la de la opción final
    assert n["descarte_opciones"] == {"A": "razón A", "B": "razón B", "D": "razón D"}
    assert n["decision_cerrada"]["letra_modelo"] == "B" and n["decision_cerrada"]["regla"] == "veredicto_unico"
    s = ensamblar(item, salida, P472)
    assert s["respuesta_correcta"] == "C" and s["decision_cerrada"]["letra_final"] == "C"
    assert "decision_cerrada" not in s["salida_modelo"] and not s["abstencion"]
    # una salida vieja (con descarte_opciones y sin análisis) se sigue aceptando
    vieja = normalizar(item, {"justificacion": "j", "respuesta_correcta": "A",
                              "descarte_opciones": {"B": "no", "C": "no", "D": "no"}})
    assert vieja["respuesta_correcta"] == "A" and "decision_cerrada" not in vieja
