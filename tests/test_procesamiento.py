"""Pruebas de la fase 3: limpieza, segmentación por artículo, encabezados y partición."""
from pathlib import Path

import pytest

from src.procesamiento import encabezado, oraciones   # añade scripts/ al path
import citations  # noqa: E402
from src.procesamiento.leer import leer, limpiar, reunir_parrafos
from src.procesamiento.normas import bloques, normalizar_num, ruta_jerarquia, segmentar
from src.procesamiento.partir import LIMITE_PALABRAS, palabras, partir, vigente

CGP = Path("data/md/ley_1564_2012.md")
META_CGP = {"doc_id": "ley_1564_2012", "tipo_norma": "ley", "numero": "1564", "anio": 2012}


# ------------------------------------------------------------------ limpieza
def test_limpiar_es_idempotente_y_conserva_simbolos():
    crudo = "|\n| |\n\n**ARTÍCULO 12.** Texto § 3°​ con\xa0guion-medio.\n\n#\n\n### SENTENCIA"
    una = limpiar(crudo)
    assert una == limpiar(una)
    assert "ARTÍCULO 12. Texto § 3° con guion-medio." in una
    assert "|" not in una and "**" not in una and "​" not in una
    assert "SENTENCIA" in una and "#" not in una


def test_limpiar_convierte_notas_angulares_y_tablas():
    t = limpiar("PARÁGRAFO 2o. <Parágrafo eliminado por el artículo 2 de la Ley 2541 de 2025>\n\n"
                "| País | Año |\n| --- | --- |\n| Canadá | 1988 |")
    assert "{{Parágrafo eliminado por el artículo 2 de la Ley 2541 de 2025}}" in t
    assert "---" not in t and "Canadá | 1988" in t


def test_reunir_parrafos_no_fusiona_numerales():
    t = "la Corte considera que\nno procede la nulidad.\n1. Primer numeral\n2. Segundo"
    assert reunir_parrafos(t) == ("la Corte considera que no procede la nulidad.\n"
                                  "1. Primer numeral\n2. Segundo")


# ------------------------------------------------------------ artículos
@pytest.mark.parametrize("linea,num", [
    ("ARTÍCULO 42o. OBJETO. Texto.", "42"),
    ("ARTICULO 1o. OBJETO. Texto.", "1"),
    ("ARTÍCULO 42-1. TÍTULO. Texto.", "42-1"),
    ("ARTÍCULO 42 bis. TÍTULO. Texto.", "42bis"),
    ("ARTÍCULO 397A. TÍTULO. Texto.", "397A"),
    ("ARTÍCULO 217-A. TÍTULO. Texto.", "217-A"),
    ("ARTÍCULO 38-Ñ. TÍTULO. Texto.", "38-Ñ"),
    ("ARTÍCULO TRANSITORIO 5. Texto.", "T5"),
])
def test_variantes_de_articulo(linea, num):
    seg = segmentar(linea)
    assert [a.num for a in seg.articulos] == [num]


def test_normalizar_num():
    assert normalizar_num("397 A") == ("397A", 397, "A")
    assert normalizar_num("42 bis") == ("42bis", 42, "bis")


def test_cita_en_minuscula_no_abre_articulo_y_paragrafo_no_se_separa():
    texto = ("ARTÍCULO 612. NOTIFICACIONES. Modifíquese el artículo 199 de la Ley 1437:\n\n"
             "Artículo 199. Notificación personal del auto admisorio.\n\n"
             "PARÁGRAFO. El parágrafo queda dentro.\n\n"
             "ARTÍCULO 613. AUDIENCIA. Texto.")
    seg = segmentar(texto)
    assert [a.num for a in seg.articulos] == ["612", "613"]
    assert len(seg.articulos[0].bloques) == 3
    assert len(seg.rechazados) == 1


def test_minuscula_en_secuencia_si_abre_articulo():
    seg = segmentar("Artículo 1.- Primero.\n\nArtículo 2.- Segundo.\nArtículo 3.- Tercero.")
    assert [a.num for a in seg.articulos] == ["1", "2", "3"]


def test_reinicio_de_numeracion_es_norma_transcrita():
    arts = "\n\n".join(f"ARTÍCULO {i}. T. Texto." for i in range(1, 40))
    seg = segmentar(arts + "\n\nARTÍCULO 1o. Otra ley.\n\nARTÍCULO 40. T. Texto.")
    assert [a.num for a in seg.articulos][-1] == "40"
    assert len(seg.rechazados) == 1


def test_jerarquia_y_subtitulos_numerados():
    # Los dos casos del CGP: subtítulo justo tras un CAPÍTULO, y "2. …" al final de un
    # artículo sin numerales (no continúa ninguna secuencia).
    texto = ("LIBRO PRIMERO.\n\nSUJETOS DEL PROCESO.\n\nSECCIÓN PRIMERA.\n\nÓRGANOS JUDICIALES.\n\n"
             "TÍTULO I.\n\nJURISDICCIÓN Y COMPETENCIA.\n\nCAPÍTULO I.\n\nCOMPETENCIA.\n\n"
             "1. Disposiciones Generales\n\n"
             "ARTÍCULO 15. CLÁUSULA GENERAL. Texto.\n\n2. Documentos Públicos.\n\n"
             "ARTÍCULO 16. OTRO. Texto.")
    a15, a16 = segmentar(texto).articulos
    assert ruta_jerarquia(a15.jerarquia, con_nombres=False) == \
        "Libro Primero > Sección Primera > Título I > Capítulo I > 1. Disposiciones Generales"
    assert a15.titulo == "CLÁUSULA GENERAL"
    assert ruta_jerarquia(a16.jerarquia, con_nombres=False).endswith("> 2. Documentos Públicos")
    assert all("Documentos" not in b.texto for b in a15.bloques)


def test_numeral_que_continua_la_secuencia_no_es_subtitulo():
    texto = ("ARTÍCULO 20. COMPETENCIA. Conocen:\n\n1. De los contenciosos.\n\n"
             "2. De la expropiación.\n\nARTÍCULO 21. OTRO. Texto.")
    a20, _ = segmentar(texto).articulos
    assert a20.bloques[-1].texto == "2. De la expropiación."


def test_bloques_de_pdf_cortan_en_cada_articulo():
    bls = bloques("Artículo 1.- Uno\nsigue.\nArtículo 2.- Dos.")
    assert [b.texto for b in bls] == ["Artículo 1.- Uno\nsigue.", "Artículo 2.- Dos."]


# ------------------------------------------------------------ oraciones
def test_oraciones_respeta_abreviaturas_y_notas():
    t = ("Según el art. 42 del C.G.P. y la Ley 1564 de 2012 procede. "
         "{{Inciso modificado por la Ley 2445 de 2025. El nuevo texto es el siguiente:}} Otra.")
    partes = [t[a:b] for a, b in oraciones.dividir(t)]
    assert len(partes) == 2
    assert partes[0].endswith("procede.")


# ------------------------------------------------------------ partición
def test_ningun_fragmento_supera_el_limite_ni_corta_oraciones():
    oracion = "El juez deberá decretar la prueba solicitada por la parte interesada. "
    texto = "ARTÍCULO 1. LARGO. " + "\n\n".join(oracion * 6 for _ in range(12))
    seg = segmentar(texto)
    grupos = partir(texto, seg.articulos[0].bloques, palabras_encabezado=20)
    assert len(grupos) > 1
    for g in grupos:
        cuerpo = vigente(texto[g.inicio:g.fin])
        assert palabras(cuerpo) + 20 <= LIMITE_PALABRAS
        assert cuerpo.endswith(".")


def test_vigente_quita_tachado():
    assert vigente("Será nula ~~de pleno derecho~~ la actuación.") == "Será nula la actuación."


# ------------------------------------------------------------ encabezado
@pytest.mark.parametrize("doc_id", sorted(encabezado.NOMBRES))
def test_encabezado_reconocido_por_el_evaluador(doc_id):
    meta = {"doc_id": doc_id}
    cab = encabezado.encabezado_articulo(meta, "5", "OBJETO", "Libro Primero")
    esperado = encabezado.cuerpo_canonico(meta)
    assert esperado in citations.bodies(citations.extract(cab))


def test_encabezado_cgp_incluye_articulo():
    cab = encabezado.encabezado_articulo(META_CGP, "391", "DEMANDA Y CONTESTACIÓN", "Libro Tercero")
    assert ("codigo_general_proceso", None, None, "391") in citations.extract(cab)
    assert encabezado.norma_id(META_CGP, "391") == "codigo_general_proceso#art_391"


# ------------------------------------------------------------ corpus real
@pytest.mark.skipif(not CGP.exists(), reason="requiere data/md/ley_1564_2012.md")
def test_cgp_completo():
    seg = segmentar(leer(CGP).texto)
    bases = {a.num_base for a in seg.articulos}
    assert set(range(1, 628)) <= bases
    assert sorted(a.num for a in seg.articulos if a.sufijo) == \
        ["397A", "539A", "569A", "570A", "571A", "572A", "576A"]
    a15 = next(a for a in seg.articulos if a.num == "15")
    assert ruta_jerarquia(a15.jerarquia, con_nombres=False) == \
        "Libro Primero > Sección Primera > Título I > Capítulo I"
    assert not any(a.num == "199" and a.inicio > seg.articulos[600].inicio for a in seg.articulos)
