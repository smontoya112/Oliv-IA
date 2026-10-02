"""Paso 8.5: validación de la entrega contra schema/submission.schema.json.

Usa `jsonschema` si está instalado. Si no (en Windows el Control de aplicaciones bloquea la
DLL de rpds-py), aplica un validador mínimo que cubre exactamente las palabras clave que usa
el schema oficial (type, required, properties, items, enum, const, minLength, minimum,
allOf, if/then). Además corre evaluate.validate, que revisa reglas que el schema no expresa
(campos no vacíos y pasajes no vacíos cuando no hay abstención, ids duplicados o faltantes).
"""
from __future__ import annotations

import json
from pathlib import Path

RUTA_SCHEMA = Path(__file__).resolve().parents[2] / "schema" / "submission.schema.json"
_TIPOS = {"object": dict, "array": list, "string": str, "boolean": bool, "number": (int, float),
          "integer": int}


def cargar_schema(ruta: Path = RUTA_SCHEMA) -> dict:
    return json.loads(ruta.read_text(encoding="utf-8"))


def _tipo_ok(valor, tipo: str) -> bool:
    if tipo in ("integer", "number") and isinstance(valor, bool):
        return False
    return isinstance(valor, _TIPOS[tipo])


def _errores_minimos(valor, esq: dict, ruta: str = "") -> list[str]:
    errores: list[str] = []
    if "type" in esq and not _tipo_ok(valor, esq["type"]):
        return [f"{ruta or '/'}: se esperaba {esq['type']}"]
    if "enum" in esq and valor not in esq["enum"]:
        errores.append(f"{ruta}: {valor!r} no está en {esq['enum']}")
    if "const" in esq and valor != esq["const"]:
        errores.append(f"{ruta}: {valor!r} != {esq['const']!r}")
    if "minLength" in esq and isinstance(valor, str) and len(valor) < esq["minLength"]:
        errores.append(f"{ruta}: más corto que {esq['minLength']}")
    if "minimum" in esq and isinstance(valor, (int, float)) and valor < esq["minimum"]:
        errores.append(f"{ruta}: menor que {esq['minimum']}")
    if isinstance(valor, dict):
        errores += [f"{ruta}: falta '{k}'" for k in esq.get("required", []) if k not in valor]
        for k, sub in esq.get("properties", {}).items():
            if k in valor:
                errores += _errores_minimos(valor[k], sub, f"{ruta}/{k}")
    if isinstance(valor, list) and "items" in esq:
        for i, v in enumerate(valor):
            errores += _errores_minimos(v, esq["items"], f"{ruta}/{i}")
    for sub in esq.get("allOf", []):
        if "if" in sub:
            if not _errores_minimos(valor, sub["if"], ruta) and "then" in sub:
                errores += _errores_minimos(valor, sub["then"], ruta)
        else:
            errores += _errores_minimos(valor, sub, ruta)
    return errores


def errores_schema(linea: dict, schema: dict | None = None) -> list[str]:
    schema = schema or cargar_schema()
    try:
        import jsonschema
    except ImportError:
        return _errores_minimos(linea, schema)
    validador = jsonschema.validators.validator_for(schema)(schema)
    return [f"/{'/'.join(map(str, e.absolute_path))}: {e.message}"
            for e in validador.iter_errors(linea)]


def validar(lineas: list[dict], ids_esperados: set[int] | None = None) -> list[str]:
    """Todos los problemas de la entrega: schema por línea + evaluate.validate."""
    import evaluate  # scripts/evaluate.py (el __init__ del paquete agrega scripts/ al path)

    schema = cargar_schema()
    problemas = [f"item {l.get('id')}: {e}" for l in lineas for e in errores_schema(l, schema)]
    esperados = ids_esperados if ids_esperados is not None else {
        l["id"] for l in lineas if isinstance(l.get("id"), int)}
    return problemas + evaluate.validate(lineas, esperados)
