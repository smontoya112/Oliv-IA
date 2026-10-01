"""Pruebas de la Fase 4 (Paso 4.3) para el parser de citas del evaluador oficial.

scripts/citations.py es inmodificable (parte del evaluador oficial de la
hackathon): estas pruebas solo lo ejercitan como caja negra, importandolo tal
cual, para documentar su comportamiento y detectar regresiones si cambia de
version.
"""
import json
from pathlib import Path

import pytest

from src.procesamiento import encabezado  # noqa: F401  (añade scripts/ al path)
import citations  # noqa: E402

SAMPLE_PATH = Path("data/sample_50.jsonl")


def _sample_legal_basis() -> list[str]:
    bases = []
    with open(SAMPLE_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            bases.append(obj.get("legal_basis") or "")
    return bases


# Casos de las muestras (data/sample_50.jsonl) donde extract() no reconoce
# ninguna cita, ya sea porque no hay una norma citada (doctrina, un enlace web)
# o porque el texto usa una forma que citations.py aun no cubre (p. ej. un
# numero de ley sin alias conocido y sin año, o una sentencia sin sala/numero
# en el formato esperado). Se documentan aqui para que un cambio de
# comportamiento en citations.py sea visible en los tests en vez de pasar
# desapercibido.
CASOS_SIN_CITA_RECONOCIDA = {
    "Art 44 ley 1150 ",
    "Doctrina. ",
    "https://www.wipo.int/edocs/mdocs/mdocs/en/wipo_ip_bog_12/wipo_ip_bog_12_ref_u14b_aleman.pdf ",
    "",
    "Sentencia de unificación 2020CE-SUJ-4-005 del 26 de noviembre de 2020 con expediente 21329.",
    "Sentencia del 18 de julio de 2017, de la Sala Civil de la Corte Suprema de Justicia",
    "sentencia t-256",
    "caso francés de Dow Chemical",
}


@pytest.mark.parametrize("legal_basis", _sample_legal_basis())
def test_extract_sobre_muestras_reales(legal_basis):
    cites = citations.extract(legal_basis)
    if legal_basis.strip() in {s.strip() for s in CASOS_SIN_CITA_RECONOCIDA}:
        assert cites == set()
    else:
        assert cites, f"no se reconocio ninguna cita en: {legal_basis!r}"


@pytest.mark.parametrize(
    "texto,esperado",
    [
        (
            "articulos 90 y 91 de la Ley 1564 de 2012",
            {("codigo_general_proceso", None, None, "90"),
             ("codigo_general_proceso", None, None, "91")},
        ),
        ("art. 42 del CGP", {("codigo_general_proceso", None, None, "42")}),
        ("Decreto 2591 de 1991", {("decreto", "2591", "1991", None)}),
        ("T-760 de 2008", {("jurisprudencia", "T-760", "2008", None)}),
        ("SU-214/16", {("jurisprudencia", "SU-214", "2016", None)}),
    ],
)
def test_extract_casos_tipicos(texto, esperado):
    assert citations.extract(texto) == esperado


def test_extract_cadena_vacia():
    assert citations.extract("") == set()
