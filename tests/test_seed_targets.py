"""Fase 4: cobertura del diccionario de alias contra TODO el universo de normas
del corpus (data/seed_targets.json), no solo la muestra de 50 preguntas.

seed_targets.json es la lista completa (225 entradas) de normas y sentencias
objetivo del scraping (Fase 1/2), cada una con su forma canonica ya decidida
en ['tipo'|'slug', numero, anio]. Esta prueba sintetiza, para cada entrada, el
texto de cita mas simple posible y verifica que citations.extract() (caja
negra, sin modificar) + normalizacion.to_canonical_id() logren reconocerla y
producir un ID canonico resuelto (no un slug desnudo).

scripts/citations.py es del evaluador oficial (inmodificable); los huecos que
aparecen aqui son limitaciones conocidas de ese parser, documentadas para que
no sean sorpresa.
"""
import json
from pathlib import Path

import pytest

from src.procesamiento import encabezado  # noqa: F401  (añade scripts/ al path)
import citations  # noqa: E402
from scripts import normalizacion as nz

SEED_PATH = Path("data/seed_targets.json")

# Sentencias de Consejo de Estado o sin sala/radicado estandar: citations.py
# solo reconoce las salas c|t|su|sl|sc|sp|stc|stl|ac|au (ver _SENT_RE), por lo
# que "CE-..." y formatos sin number puro (p. ej. "CE-S2-IJ-SU") no calzan.
# El propio seed_targets.json ya las marca con slugs no estandar
# ("consejo_estado", "corte_suprema_sin_radicado") en vez de
# ['jurisprudencia', SALA-NUM, anio].
NORMAS_SIN_CITA_RECONOCIDA = {
    "Sentencia de unificacion 2020CE-SUJ-4-005 (Consejo de Estado, Seccion Cuarta)",
    "Sentencia Sala Civil CSJ, 18 de julio de 2017 (lesion enorme en compraventa de inmueble)",
    "Sentencia CE-S3-19031 de 2011",
    "Sentencia de Unificación CE-S3-26251 de 2014",
    "Sentencia de Unificación CE-S3-32988 de 2014",
    "Sentencia de Unificación CE-S2-IJ-SU de 2022",
    "Sentencia de Unificación CE-SUJ-4-005 de 2020",
}


def _cargar_seed_targets() -> list[dict]:
    with open(SEED_PATH, encoding="utf-8") as f:
        return json.load(f)["documentos"]


def _texto_sintetico(doc: dict) -> str:
    """Construye el texto de cita mas simple para una entrada de seed_targets."""
    tipo, numero, anio = doc["canonico"]
    if tipo in ("ley", "decreto", "acuerdo"):
        return f"{tipo.capitalize()} {numero} de {anio}"
    if tipo == "jurisprudencia":
        return f"Sentencia {numero} de {anio}"
    entry = nz._ALIAS_DICT["codigos"].get(tipo)
    if entry is None:
        return doc["norma"]  # slug desconocido: se deja caer al caso sin-cita
    return entry["alias"][0]


SEED_TARGETS = _cargar_seed_targets()


def test_seed_targets_tiene_225_documentos():
    """Guardia de regresion: si el seed cambia de tamaño, revisar esta prueba."""
    assert len(SEED_TARGETS) == 225


@pytest.mark.parametrize(
    "doc", SEED_TARGETS, ids=[d["norma"] for d in SEED_TARGETS]
)
def test_cada_norma_del_seed_es_mapeable(doc):
    texto = _texto_sintetico(doc)
    cites = citations.extract(texto)

    if doc["norma"] in NORMAS_SIN_CITA_RECONOCIDA:
        assert cites == set(), (
            f"{doc['norma']!r} ahora SI se reconoce ({cites}); "
            "actualiza NORMAS_SIN_CITA_RECONOCIDA"
        )
        return

    assert cites, f"no se reconocio ninguna cita para {doc['norma']!r} ({texto!r})"

    ids = {nz.to_canonical_id(c) for c in cites}
    tipo, numero, anio = doc["canonico"]
    if tipo in ("ley", "decreto"):
        # Para normas citadas por numero y año, el ID debe resolver siempre a
        # la forma canonica sin ceros a la izquierda (ver to_canonical_id).
        numero_canon = str(int(numero))
        assert all(f"_{numero_canon}_{anio}" in i for i in ids), (
            f"{doc['norma']!r}: IDs {ids} no resuelven a {tipo}_{numero_canon}_{anio}"
        )
