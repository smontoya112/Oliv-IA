"""Pruebas de la Fase 4: Pasos 4.1 (IDs canonicos) y 4.2 (YAML de alias)."""
import pytest

from src.procesamiento import encabezado  # noqa: F401  (añade scripts/ al path)
import citations  # noqa: E402
from scripts import normalizacion as nz


def test_alias_yaml_sincronizado_con_citations():
    """data/alias_normas.yaml debe reflejar exactamente CODES y _ALIAS_NUM."""
    codigos = nz._ALIAS_DICT["codigos"]
    assert set(codigos) == set(citations.CODES)
    for slug, variantes in citations.CODES.items():
        assert set(codigos[slug]["alias"]) == set(variantes)

    alias_numero = {
        (e["tipo"], e["numero"]): e["slug"] for e in nz._ALIAS_DICT["alias_numero"]
    }
    esperado = {(tipo, int(numero)): slug for (tipo, numero), slug in citations._ALIAS_NUM.items()}
    assert alias_numero == esperado


@pytest.mark.parametrize(
    "cita,id_esperado",
    [
        (("ley", "1563", "2012", "41"), "ley_1563_2012#art_41"),
        (("decreto", "2591", "1991", None), "decreto_2591_1991"),
        (("jurisprudencia", "C-355", "2006", None), "sentencia_C-355_2006"),
        (("jurisprudencia", "SU-214", "2016", None), "sentencia_SU-214_2016"),
        (("codigo_general_proceso", None, None, "391"), "ley_1564_2012#art_391"),
        (("codigo_general_proceso", None, None, "6"), "ley_1564_2012#art_6"),
        (("codigo_civil", None, None, "946"), "ley_84_1873#art_946"),
        (("decreto", "046", "2024", None), "decreto_46_2024"),
        (("acuerdo", "02", "2015", None), "acuerdo_2_2015"),
    ],
)
def test_to_canonical_id(cita, id_esperado):
    assert nz.to_canonical_id(cita) == id_esperado


@pytest.mark.parametrize(
    "texto_a,texto_b",
    [
        ("Decreto 046 de 2024", "Decreto 46 de 2024"),
        ("Acuerdo 02 de 2015", "Acuerdo 2 de 2015"),
    ],
)
def test_to_canonical_id_es_idempotente_ante_ceros_a_la_izquierda(texto_a, texto_b):
    """La misma norma citada con o sin ceros a la izquierda debe dar el mismo ID."""
    assert nz.extract_canonical(texto_a) == nz.extract_canonical(texto_b)


def test_extract_canonical_integra_citations_y_normalizacion():
    ids = nz.extract_canonical("articulos 90 y 91 de la Ley 1564 de 2012")
    assert ids == {"ley_1564_2012#art_90", "ley_1564_2012#art_91"}

    ids = nz.extract_canonical("T-760 de 2008")
    assert ids == {"sentencia_T-760_2008"}


@pytest.mark.parametrize(
    "texto,id_esperado",
    [
        ("el articulo 407 del C.P.C.", "decreto_1400_1970#art_407"),
        ("Código de Procedimiento Civil", "decreto_1400_1970"),
        ("Código Contencioso Administrativo", "decreto_1_1984"),
        ("Código del Menor", "decreto_2737_1989"),
        ("EOSF", "decreto_663_1993"),
        ("Estatuto Orgánico del Sistema Financiero", "decreto_663_1993"),
    ],
)
def test_extract_canonical_reconoce_codigos_derogados_fuera_de_citations(texto, id_esperado):
    """Paso 4.2 (extension): codigos presentes en el corpus
    (data/corpus_manifest.json) pero ausentes de scripts/citations.py.
    """
    assert nz.extract_canonical(texto) == {id_esperado}
    # citations.py (evaluador oficial, inmodificable) no los conoce: esto es
    # una capacidad adicional solo de extract_canonical(), no del evaluador.
    assert citations.extract(texto) == set()
