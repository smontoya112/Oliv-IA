"""Pruebas de la fase 6 sin GPU ni índices: puente de ids, 6.1-6.3, 6.6, 6.7 y la selección."""
import json
from pathlib import Path

import pytest

import src.recuperacion  # noqa: F401  (agrega scripts/ al path)
from src.generacion import contexto_prueba
from src.generacion.prompts import formatear_pasajes
from src.indice.fusion import colapsar, rrf
from src.recuperacion import alias, area, cerradas, contexto, normas_pregunta, seleccion
from src.recuperacion.catalogo import Catalogo, a_canonico
from src.recuperacion.config import Config

import numpy as np

# ------------------------------------------------------------------ catálogo de juguete
FILAS = [
    # chunk_id, doc_id, norma_id_canonico (formato de encabezado.norma_id), areas, sha1
    ("c0", "codigo_general_proceso", "codigo_general_proceso#art_391", ["procesal"], "h0"),
    ("c1", "codigo_general_proceso", "codigo_general_proceso#art_391", ["procesal"], "h1"),  # parte 2
    ("c2", "codigo_general_proceso", "codigo_general_proceso#art_5", ["procesal"], "h2"),
    ("c3", "ley_472_1998", "ley_472_1998#art_46", ["constitucional"], "h3"),
    ("c4", "constitucion", "constitucion#art_88", ["constitucional"], "h4"),
    ("c5", "codigo_penal", "codigo_penal#art_10", ["penal"], "h5"),
    ("c6", "sentencia_c-355_2006", "jurisprudencia_C-355_2006", ["constitucional"], "h6"),
    ("c7", "decreto_2591_1991", "decreto_2591_1991#art_86", ["constitucional"], "h7"),
    ("c8", "codigo_comercio", "codigo_comercio#art_100", ["comercial"], "h8"),
    ("c9", "copia_cgp", "codigo_general_proceso#art_5", ["procesal"], "h2"),   # duplicado exacto
]


def juguete() -> Catalogo:
    cols = {"chunk_id": [f[0] for f in FILAS], "doc_id": [f[1] for f in FILAS],
            "norma_id_canonico": [f[2] for f in FILAS], "areas": [f[3] for f in FILAS],
            "texto": [f"Texto {f[0]}" for f in FILAS], "inicio": [0] * len(FILAS),
            "fin": [10] * len(FILAS), "sha1_texto": [f[4] for f in FILAS]}
    return Catalogo.desde_columnas(cols)


def ranking(*filas):
    return [(i, 1.0 / (p + 1)) for p, i in enumerate(filas)]


# ------------------------------------------------------------------ puente de ids
@pytest.mark.parametrize("chunk,canonico", [
    ("codigo_general_proceso#art_391", "ley_1564_2012#art_391"),
    ("jurisprudencia_C-355_2006", "sentencia_C-355_2006"),
    ("ley_1996_2019#art_5", "ley_1996_2019#art_5"),
    ("constitucion#art_88", "constitucion#art_88"),
    ("codigo_penal", "ley_599_2000"),
    ("decreto_046_2024", "decreto_46_2024"),
    ("estatuto_tributario#art_10", "decreto_624_1989#art_10"),
])
def test_puente_de_ids(chunk, canonico):
    assert a_canonico(chunk) == canonico


def test_puente_cubre_todo_el_manifest():
    """Cada documento del corpus con `canonico` debe quedar con un id canónico no vacío."""
    m = json.loads(Path("data/corpus_manifest.json").read_text(encoding="utf-8"))
    for r in m:
        if r.get("estado") == "ok" and r.get("canonico"):
            base = "_".join(str(p) for p in r["canonico"] if p)
            ident = a_canonico(base)
            assert ident and not ident.startswith("_"), r["doc_id"]


# ------------------------------------------------------------------ 6.2 alias
def test_alias_expande_siglas_a_nombre_completo():
    extra = alias.terminos("Según el art. 391 del CGP, ¿qué procede?")
    assert "codigo general del proceso" in extra and "ley 1564 de 2012" in extra
    assert "CGP" in alias.expandir("art. 391 del CGP") and "codigo general del proceso" in alias.expandir("art. 391 del CGP")
    assert alias.expandir("¿Qué es la prescripción?") == "¿Qué es la prescripción?"   # nada que expandir


def test_alias_no_repite_lo_que_ya_dice_el_texto():
    assert "codigo general del proceso" not in alias.terminos("artículo 391 del Código General del Proceso")


# ------------------------------------------------------------------ 6.1 directos
def test_directos_artículo_existente_y_norma_ajena():
    cat = juguete()
    filas, info = normas_pregunta.directos(
        "¿Qué dice el artículo 391 del Código General del Proceso?", cat, ranking(7, 3), n_max=4)
    assert filas == [0, 1]                       # las dos partes del artículo 391
    assert "ley_1564_2012#art_391" in info["en_corpus"]
    filas2, info2 = normas_pregunta.directos("Según la Ley 80 de 1993", cat, ranking(7))
    assert filas2 == [] and info2["sin_corpus"]  # norma fuera del corpus: nada que promover


def test_directos_norma_sin_articulo_usa_solo_lo_ya_recuperado():
    cat = juguete()
    filas, _ = normas_pregunta.directos("Conforme a la Constitución Política", cat, ranking(7, 4, 3))
    assert filas == [4]                          # el chunk de la Constitución que ya estaba en el ranking
    sin, _ = normas_pregunta.directos("Conforme a la Constitución Política", cat, ranking(7, 3))
    assert sin == []                             # no se promueve a ciegas


# ------------------------------------------------------------------ 6.3 área
def test_area_filtra_y_cae_al_corpus_general():
    cat = juguete()
    rk = ranking(5, 8, 0, 3, 7, 4)
    pen = area.areas_item({"area": "Derecho penal"})
    dentro, fb = area.filtrar(rk, cat, pen, min_en_area=1)
    assert [i for i, _ in dentro] == [5, 7, 4] and not fb     # penal + transversales (decreto 2591, constitución)
    todo, fb = area.filtrar(rk, cat, pen, min_en_area=10)
    assert todo == rk and fb                                   # muy pocos en el área: corpus general
    assert area.filtrar(rk, cat, pen, 1, modo="ninguno") == (rk, False)
    assert area.areas_item({"area": "Derecho de los mercados [competencia, consumidor]"}) == {"mercados"}


# ------------------------------------------------------------------ 6.6 cerradas
MC = {"id": 1, "formato": "multiple_choice", "area": "Derecho procesal",
      "pregunta": "¿Qué dice el artículo 5 del Código General del Proceso?",
      "opciones": {"A": "Según la Ley 80 de 1993, nada.", "B": "Opción b", "C": "Opción c", "D": "Opción d"}}
SEMI = {"id": 2, "formato": "semi_open", "area": "Derecho constitucional", "pregunta": "¿Qué es la tutela?"}


def test_consultas_cerradas():
    assert "A) Según la Ley 80" in cerradas.consulta_base(MC)
    por_op = cerradas.consultas_por_opcion(MC)
    assert [l for l, _ in por_op] == ["A", "B", "C", "D"] and "Opción b" in por_op[1][1]
    assert cerradas.consultas_por_opcion(SEMI) == [] and cerradas.consulta_base(SEMI) == SEMI["pregunta"]


# ------------------------------------------------------------------ selección
def test_candidatos_cerrada_no_promueve_normas_de_las_opciones():
    cat, cfg = juguete(), Config(k_fusion=8, extra_por_opcion=1)
    rk_base = (ranking(8, 3), ranking(3, 8))
    rk_opts = [(ranking(2), ranking(2)), (ranking(5), ranking(5)), (ranking(7), ranking(7)), (ranking(4), ranking(4))]
    cand, info = seleccion.candidatos(MC, cat, cfg, [rk_base] + rk_opts)
    assert cand[2]["via"] == "directo"                          # art. 5 del enunciado (c2)
    assert "ley_80_1993" not in " ".join(info["nombradas"])      # la Ley 80 era de la opción A
    assert {d["opcion"] for d in cand.values() if d["via"] == "opcion"} >= {"B", "C"}
    assert 9 not in cand                                         # c9 duplica el texto de c2: se colapsa


def test_elegir_garantiza_directos_y_tope_de_10():
    cat, cfg = juguete(), Config(top_final=3, n_directos=1, reranker=False)
    cand = {0: {"via": "directo", "opcion": None, "fusion": 0.0, "q": "q"},
            3: {"via": "hibrido", "opcion": None, "fusion": 0.5, "q": "q"},
            4: {"via": "hibrido", "opcion": None, "fusion": 0.4, "q": "q"},
            5: {"via": "hibrido", "opcion": None, "fusion": 0.3, "q": "q"}}
    puntaje = {0: -9.0, 3: 5.0, 4: 4.0, 5: 3.0}                  # el directo tiene el peor puntaje
    final = seleccion.elegir(cand, puntaje, cfg)
    assert len(final) == 3 and 0 in final and final[0] == 3      # entra aunque puntúe mal; orden por puntaje
    sen = seleccion.senales(final, cand, puntaje, cat,
                            {"nombradas": ["ley_1564_2012#art_391", "ley_80_1993"], "sin_corpus": ["ley_80_1993"],
                             "area_fallback": False}, reranker=True)
    assert sen["n_directos"] == 1 and sen["normas_nombradas"] == 2
    assert sen["cobertura_normas_pregunta"] == 0.5 and sen["normas_nombradas_fuera_del_corpus"] == 1


def test_seleccion_es_determinista_con_empates():
    cfg = Config(top_final=2)
    cand = {i: {"via": "hibrido", "opcion": None, "fusion": 0.1, "q": "q"} for i in (7, 3, 5)}
    puntaje = {7: 1.0, 3: 1.0, 5: 1.0}
    assert seleccion.elegir(cand, puntaje, cfg) == seleccion.elegir(dict(reversed(cand.items())), puntaje, cfg) == [3, 5]
    cat = juguete()                                              # con tope por norma también
    assert seleccion.elegir(cand, puntaje, cfg, cat) == seleccion.elegir(dict(reversed(cand.items())), puntaje, cfg, cat)


def test_elegir_reserva_una_por_opcion_dentro_del_prompt():
    cand = {i: {"via": "hibrido", "opcion": None, "fusion": 0.1, "q": "q"} for i in range(12)}
    puntaje = {i: 20.0 - i for i in range(12)}
    for i, letra, s in ((20, "A", -1.0), (21, "A", -2.0), (22, "B", -3.0)):
        cand[i] = {"via": "opcion", "opcion": letra, "fusion": 0.0, "q": f"q{letra}"}
        puntaje[i] = s
    final = seleccion.elegir(cand, puntaje, Config(top_final=10, n_directos=0))
    assert len(final) == 10 and 21 not in final                  # una sola por letra
    assert {20, 22} <= set(final[: contexto.MAX_PASAJES])        # y ambas entran al prompt
    assert final[: contexto.MAX_PASAJES - 2] == [0, 1, 2, 3, 4, 5]   # el resto conserva el orden
    sin = seleccion.elegir(cand, puntaje, Config(top_final=10, n_directos=0, garantizar_opciones=False))
    assert sin == list(range(10))


def test_elegir_tope_por_norma_y_relleno():
    cat = juguete()                                  # c0/c1: mismo artículo; c2/c9: mismo artículo
    cand = {i: {"via": "hibrido", "opcion": None, "fusion": 0.1, "q": "q"} for i in (0, 1, 2, 3, 9)}
    puntaje = {0: 5.0, 1: 4.0, 2: 3.0, 9: 2.5, 3: 2.0}
    assert seleccion.elegir(cand, puntaje, Config(top_final=3, max_por_norma=1), cat) == [0, 2, 3]
    assert seleccion.elegir(cand, puntaje, Config(top_final=3, max_por_norma=0), cat) == [0, 1, 2]
    assert seleccion.elegir(cand, puntaje, Config(top_final=3, max_por_norma=1)) == [0, 1, 2]  # sin cat
    # faltan candidatos distintos: se rellena con los repetidos antes que devolver menos
    assert seleccion.elegir(cand, puntaje, Config(top_final=5, max_por_norma=1), cat) == [0, 1, 2, 9, 3]


def test_elegir_descarta_el_mismo_articulo_desde_otro_documento():
    cat = juguete()                                  # c9 (copia_cgp) es el art. 5 del CGP, como c2
    cand = {i: {"via": "hibrido", "opcion": None, "fusion": 0.1, "q": "q"} for i in (2, 9, 3)}
    puntaje = {2: 5.0, 9: 4.0, 3: 3.0}
    assert seleccion.elegir(cand, puntaje, Config(top_final=2), cat) == [2, 3]
    assert seleccion.elegir(cand, puntaje, Config(top_final=2, sin_copias=False), cat) == [2, 9]
    assert seleccion.elegir(cand, puntaje, Config(top_final=3), cat) == [2, 9, 3]   # relleno


def test_elegir_tope_de_sentencias():
    filas = [("s0", "sentencia_c-1_2020", "jurisprudencia_C-1_2020"),
             ("s1", "sentencia_c-2_2020", "jurisprudencia_C-2_2020"),
             ("s2", "sentencia_c-3_2020", "jurisprudencia_C-3_2020"),
             ("n3", "codigo_penal", "codigo_penal#art_10")]
    cat = Catalogo.desde_columnas({
        "chunk_id": [f[0] for f in filas], "doc_id": [f[1] for f in filas],
        "norma_id_canonico": [f[2] for f in filas], "areas": [[] for _ in filas],
        "texto": ["t"] * len(filas), "inicio": [0] * len(filas), "fin": [1] * len(filas),
        "sha1_texto": [f[0] for f in filas]})
    cand = {i: {"via": "hibrido", "opcion": None, "fusion": 0.1, "q": "q"} for i in range(4)}
    puntaje = {0: 4.0, 1: 3.0, 2: 2.0, 3: 1.0}
    assert seleccion.elegir(cand, puntaje, Config(top_final=3, max_sentencias=2), cat) == [0, 1, 3]
    assert seleccion.elegir(cand, puntaje, Config(top_final=3, max_sentencias=0), cat) == [0, 1, 2]
    assert seleccion.elegir(cand, puntaje, Config(top_final=4, max_sentencias=1), cat) == [0, 1, 2, 3]


# ------------------------------------------------------------------ fusión (refactor)
def test_rrf_y_colapsar_siguen_igual():
    r = rrf([(1, 9.0), (2, 8.0)], [(2, 0.9), (3, 0.5)], k=3)
    assert [i for i, _ in r][0] == 2
    sc, ids = np.array([3.0, 2.0, 1.0]), np.array([0, 1, 2])
    assert colapsar(sc, ids, ["a", "a", "b"], 5, False) == [(0, 3.0), (2, 1.0)]   # la fila 1 repite a la 0


# ------------------------------------------------------------------ 6.7 contexto
def test_contexto_max_8_pasajes_y_presupuesto():
    pas = [{"doc_id": f"d{i}", "texto": "palabra " * 100} for i in range(10)]
    texto, usados = contexto.armar(pas)
    assert len(usados) == 8 and texto.count("[P") == 8 and "[P9]" not in texto
    texto, usados = contexto.armar(pas, max_tokens=500)
    assert 1 <= len(usados) < 8
    grande, u = contexto.armar([{"doc_id": "x", "texto": "palabra " * 5000}], max_tokens=300)
    assert len(u) == 1 and len(grande) <= 300 * 3.5 + 20


def test_contexto_etiqueta_la_opcion_y_prompts_delega():
    texto, _ = contexto.armar([{"doc_id": "d1", "texto": "t", "opcion": "B"}])
    assert "[P1] d1 (evidencia sobre la opción B)" in texto
    texto2, usados2 = formatear_pasajes([{"doc_id": "d1", "texto": "t"}] * 12)
    assert len(usados2) == 8


def test_contexto_usa_el_contador_del_decoder():
    pas = [{"doc_id": f"d{i}", "texto": "x"} for i in range(5)]
    _, usados = contexto.armar(pas, max_tokens=250, contar=lambda t: 100)    # 100 tokens por bloque
    assert len(usados) == 2


# ------------------------------------------------------------------ puente con la fase 7
def test_contexto_prueba_lee_la_salida_de_la_fase_6(tmp_path):
    ruta = tmp_path / "rec.jsonl"
    ruta.write_text(json.dumps({"id": 5, "pasajes": [{"doc_id": "d", "texto": "t"}], "senales": {}}) + "\n"
                    + json.dumps({"id": 6, "pasajes": [], "senales": {"error": "x"}}) + "\n", encoding="utf-8")
    assert contexto_prueba.desde_recuperacion(ruta) == {5: [{"doc_id": "d", "texto": "t"}], 6: []}


def test_tope_por_norma_reparte_el_top_10_entre_mas_normas():
    cat = juguete()
    base = cat.base
    # 0, 1 y 2 son el mismo codigo (CGP); 3, 4, 5, 6 son normas distintas
    cand = {i: {"via": "hibrido", "opcion": None, "fusion": 0.1, "q": "q"} for i in (0, 1, 2, 3, 4, 5, 6)}
    puntaje = {0: 9.0, 1: 8.0, 2: 7.0, 3: 6.0, 4: 5.0, 5: 4.0, 6: 3.0}
    sin_tope = seleccion.elegir(cand, puntaje, Config(top_final=4), base)
    assert sin_tope == [0, 1, 2, 3]                                   # el CGP ocupa 3 de 4 lugares
    con_tope = seleccion.elegir(cand, puntaje, Config(top_final=4, max_por_norma=1), base)
    assert con_tope == [0, 3, 4, 5] and len({base(i) for i in con_tope}) == 4
    # si no hay otras normas suficientes, el tope se relaja y se devuelven top_final pasajes
    solo_cgp = {i: cand[i] for i in (0, 1, 2)}
    assert seleccion.elegir(solo_cgp, puntaje, Config(top_final=3, max_por_norma=1), base) == [0, 1, 2]
    # sin la función que da la norma, el tope no se aplica (compatibilidad)
    assert seleccion.elegir(cand, puntaje, Config(top_final=4, max_por_norma=1)) == [0, 1, 2, 3]
