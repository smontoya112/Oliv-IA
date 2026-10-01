"""Fase 4: cobertura del diccionario de alias contra data/corpus_manifest.json,
el inventario de los 499 documentos realmente descargados y segmentados
(mas amplio que data/seed_targets.json, que es solo la lista objetivo).

Se enfoca en los documentos descargados con exito (estado == "ok") cuyo campo
"canonico" no esta resuelto: son los que dependen de que el diccionario de
alias los reconozca por nombre, en vez de por numero de ley/decreto.
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
NORMAS_SIN_ALIAS_ESPERADAS = {
    "codigo_procedimiento_civil": ("codigo_procedimiento_civil", "decreto_1400_1970"),
    "codigo_contencioso_administrativo": ("codigo_contencioso_administrativo", "decreto_1_1984"),
    "codigo_menor": ("codigo_menor", "decreto_2737_1989"),
    "codigo_procedimental_laboral": ("codigo_procesal_trabajo", "decreto_2158_1948"),
    "estatuto_organico_sistema_financiero": ("estatuto_organico_sistema_financiero", "decreto_663_1993"),
}

# doc_id cuyo "canonico" viene vacio/ausente pero que NO son un hueco de
# alias: ya traen tipo_norma/numero/anio completos (ej. ley_1564_2012 ->
# tipo_norma="ley", numero="1564", anio=2012), asi que citations.py los
# reconoce de forma generica con solo escribir "Ley 1564 de 2012", sin
# necesitar ningun alias. Es una inconsistencia del propio manifiesto
# (le falta la clave "canonico"), no del diccionario.
NORMAS_SIN_CANONICO_PERO_SIN_HUECO = {"ley_1564_2012"}


def _cargar_manifest() -> list[dict]:
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        return json.load(f)


MANIFEST = _cargar_manifest()
DOCS_SIN_CANONICO = {
    d["doc_id"]: d
    for d in MANIFEST
    if d.get("estado") == "ok" and not d.get("canonico")
}


def test_manifest_no_trae_normas_sin_canonico_nuevas_sin_revisar():
    """Guardia de regresion: si el scraping trae normas 'ok' sin canonico que
    no estan en ninguna de las dos listas de arriba, hay que revisarlas.
    """
    sin_explicar = set(DOCS_SIN_CANONICO) - set(NORMAS_SIN_ALIAS_ESPERADAS) - NORMAS_SIN_CANONICO_PERO_SIN_HUECO
    assert sin_explicar == set(), f"normas 'ok' sin canonico y sin revisar: {sin_explicar}"
    assert set(NORMAS_SIN_ALIAS_ESPERADAS) <= set(DOCS_SIN_CANONICO)


@pytest.mark.parametrize("doc_id,esperado", sorted(NORMAS_SIN_ALIAS_ESPERADAS.items()))
def test_norma_sin_canonico_se_resuelve_via_diccionario(doc_id, esperado):
    slug, id_esperado = esperado
    alias = nz.slug_to_norma(slug)
    assert alias is not None, f"{doc_id!r} (slug {slug!r}) no esta en codigos/extensiones del YAML"
    tipo, numero, anio = alias
    assert f"{tipo}_{numero}_{anio}" == id_esperado


def test_ley_1564_2012_no_depende_del_diccionario_de_alias():
    doc = DOCS_SIN_CANONICO["ley_1564_2012"]
    assert doc["tipo_norma"] == "ley" and doc["numero"] == "1564" and doc["anio"] == 2012
    assert citations.extract("Ley 1564 de 2012") == {("codigo_general_proceso", None, None, None)}
