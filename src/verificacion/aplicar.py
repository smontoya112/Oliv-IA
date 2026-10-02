"""Aplica la fase 8 a predicciones ya generadas (p.ej. las de src.generacion.bench), sin GPU.

Toma los campos que produjo el decoder y los vuelve a ensamblar con los pasajes COMPLETOS y
las señales de la recuperación (fase 6): verifica citas, reordena el top 10, decide la
abstención y valida el schema. Sirve para medir la fase 8 sin regenerar y para calibrar el
umbral de abstención.

    python -m src.verificacion.aplicar \
        --generacion data/processed/bench_generacion/qwen3-8b.jsonl \
        --recuperacion data/recuperacion/sample_50.jsonl \
        --salida data/processed/verificacion/qwen3-8b.jsonl [--catalogo data/index] [--umbral 0]
    python scripts/evaluate.py --submission data/processed/verificacion/qwen3-8b.jsonl
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from src.generacion.postproceso import ensamblar

from .citas import CAMPOS_CITABLES
from .esquema import validar

_CAMPOS = {"multiple_choice": ("respuesta_correcta", "justificacion", "descarte_opciones"),
           "semi_open": ("respuesta", "palabras_clave", "referencia_legal"),
           "open_ended": CAMPOS_CITABLES["open_ended"]}


def _jsonl(ruta: Path) -> list[dict]:
    return [json.loads(l) for l in ruta.read_text(encoding="utf-8").splitlines() if l.strip()]


def salida_de(linea: dict | None) -> dict | None:
    """Campos del decoder de una línea ya ensamblada (None si se abstuvo o no existe)."""
    if not linea or linea.get("abstencion"):
        return None
    return {k: linea.get(k) for k in _CAMPOS[linea["formato"]]}


def aplicar(items: list[dict], generadas: dict[int, dict], recuperadas: dict[int, dict],
            catalogo=None, umbral: float | None = None) -> list[dict]:
    res = []
    for it in items:
        g, r = generadas.get(it["id"]), recuperadas.get(it["id"]) or {}
        pasajes = r.get("pasajes") or (g or {}).get("pasajes_recuperados") or []
        res.append(ensamblar(it, salida_de(g), pasajes, (g or {}).get("latencia_ms"),
                             r.get("senales"), catalogo, umbral))
    return res


def resumen(lineas: list[dict], problemas: list[str]) -> dict:
    v = [l.get("verificacion") or {} for l in lineas]
    return {
        "n": len(lineas),
        "abstenciones": dict(Counter(x["motivo_abstencion"] for x in v if "motivo_abstencion" in x)),
        "citas_insertadas": sum(len(x.get("insertadas", [])) for x in v),
        "oraciones_eliminadas": sum(len(x.get("eliminadas", [])) for x in v),
        "campos_rellenados": sum(len(x.get("rellenados", [])) for x in v),
        "items_con_cita_sin_respaldo": sum(1 for x in v if x.get("sin_respaldo")),
        "items_sin_cita_respaldada": sum(1 for x in v if "respaldadas" in x and not x["respaldadas"]),
        "errores_validacion": len(problemas),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--generacion", type=Path, required=True, help="JSONL de predicciones")
    ap.add_argument("--recuperacion", type=Path, required=True,
                    help="data/recuperacion/<split>.jsonl (pasajes y señales de la fase 6)")
    ap.add_argument("--preguntas", type=Path, default=Path("data/sample_50.jsonl"))
    ap.add_argument("--salida", type=Path, required=True)
    ap.add_argument("--catalogo", type=Path, default=None,
                    help="directorio del índice (data/index) para respaldar citas con el corpus")
    ap.add_argument("--umbral", type=float, default=None,
                    help="score_top1 bajo el cual se abstiene una respuesta libre sin citas respaldadas")
    args = ap.parse_args()

    items = _jsonl(args.preguntas)
    generadas = {l["id"]: l for l in _jsonl(args.generacion)}
    recuperadas = {l["id"]: l for l in _jsonl(args.recuperacion)}
    catalogo = None
    if args.catalogo:
        from src.recuperacion.catalogo import cargar
        catalogo = cargar(args.catalogo)
    lineas = aplicar(items, generadas, recuperadas, catalogo, args.umbral)
    problemas = validar(lineas, {it["id"] for it in items})
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    with args.salida.open("w", encoding="utf-8") as f:
        for l in lineas:
            f.write(json.dumps(l, ensure_ascii=False) + "\n")
    for p in problemas[:20]:
        print("ERROR", p)
    print(json.dumps(resumen(lineas, problemas), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
