"""Fase 4: cobertura del diccionario de alias contra data/corpus_manifest.json,
el inventario de los 499 documentos realmente descargados y segmentados
(mas amplio que data/seed_targets.json, que es solo la lista objetivo).

Se enfoca en los documentos con tipo_norma == "codigo": son los unicos que no
traen un (tipo, numero, anio) explicito en su campo "canonico", por lo que
dependen enteramente de que el diccionario de alias los reconozca por nombre.
"""
import json
from pathlib import Path

import pytest

from src.procesamiento import encabezado  # noqa: F401  (añade scripts/ al path)
import citations  # noqa: E402
from scripts import normalizacion as nz

MANIFEST_PATH = Path("data/corpus_manifest.json")

# doc_id -> ID canonico esperado. codigo_procedimental_laboral no es un codigo
# nuevo: es el Decreto-Ley 2158 de 1948, el mismo que codigo_procesal_trabajo
# (ver comentario en data/alias_normas.yaml), asi que resuelve igual que ese.
CODIGOS_ESPERADOS = {
    "codigo_procedimiento_civil": "decreto_1400_1970",
    "codigo_contencioso_administrativo": "decreto_1_1984",
    "codigo_menor": "decreto_2737_1989",
    "codigo_procedimental_laboral": "decreto_2158_1948",
}


def _cargar_manifest() -> list[dict]:
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        return json.load(f)


MANIFEST = _cargar_manifest()
# tipo_norma == "codigo" agrupa tanto los codigos ya cubiertos por CODES (con
# canonico resuelto, p. ej. codigo_civil) como los 4 que llegaron sin
# canonico porque citations.py no los conoce (los que nos interesan aqui).
DOCS_CODIGO_OK = {
    d["doc_id"]: d
    for d in MANIFEST
    if d.get("tipo_norma") == "codigo" and d.get("estado") == "ok" and d.get("canonico") is None
}


def test_manifest_tiene_los_4_codigos_sin_canonico_conocidos():
    """Guardia de regresion: si aparecen mas 'codigo' sin canonico, revisar."""
    assert set(DOCS_CODIGO_OK) == set(CODIGOS_ESPERADOS)


@pytest.mark.parametrize("doc_id,id_esperado", sorted(CODIGOS_ESPERADOS.items()))
def test_codigo_sin_canonico_se_resuelve_via_extensiones(doc_id, id_esperado):
    titulo = DOCS_CODIGO_OK[doc_id]["titulo"]
    assert doc_id in DOCS_CODIGO_OK, f"{doc_id!r} ya no esta en el manifiesto ({titulo!r})"

    alias = nz.slug_to_norma(doc_id.replace("codigo_procedimental_laboral", "codigo_procesal_trabajo"))
    # El propio diccionario (codigos o extensiones) debe resolver al numero real.
    assert alias is not None
    tipo, numero, anio = alias
    assert f"{tipo}_{numero}_{anio}" == id_esperado
