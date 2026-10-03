"""Compara dos corridas de RAGAS ítem por ítem (jobs/ragas_por_item.py guarda `ragas_items.json`).

    python -m src.analisis.comparar_ragas experimentos/claude/ragas_A/ragas_items.json \
        experimentos/claude/ragas_B/ragas_items.json [--muestra data/sample_50.jsonl] [--salida comparacion.md]

Cruza cada fila con su ítem por el texto de la pregunta. Separa los ítems cuya respuesta es IDÉNTICA en las
dos corridas: ahí la diferencia de puntaje es solo ruido del juez (el mismo texto, juzgado dos veces), lo que da
la escala para leer los ítems que sí cambiaron.
"""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path


def _cargar(ruta: Path, muestra: dict) -> dict[int, dict]:
    filas = json.loads(ruta.read_text(encoding="utf-8"))
    res = {}
    for f in filas:
        item = muestra.get(f.get("user_input") or f.get("question"))
        if item:
            res[item["id"]] = {"formato": item["formato"], "sub_tarea": item.get("sub_tarea"),
                               "texto": f.get("response") or f.get("answer") or "",
                               "puntaje": f.get("answer_correctness")}
    return res


def comparar(a: dict[int, dict], b: dict[int, dict]) -> dict:
    ids = sorted(set(a) & set(b))
    por_formato, ruido, cambiados = {}, [], []
    for i in ids:
        pa, pb = a[i]["puntaje"], b[i]["puntaje"]
        if pa is None or pb is None:
            continue
        por_formato.setdefault(a[i]["formato"], []).append((i, pa, pb))
        (ruido if a[i]["texto"] == b[i]["texto"] else cambiados).append((i, a[i]["formato"], pa, pb))
    resumen = {}
    for fmt, v in por_formato.items():
        resumen[fmt] = {"n": len(v), "A": round(sum(x[1] for x in v) / len(v), 4),
                        "B": round(sum(x[2] for x in v) / len(v), 4)}
    n = sum(len(v) for v in por_formato.values())
    todos = [x for v in por_formato.values() for x in v]
    return {"n": n, "A": round(sum(x[1] for x in todos) / n, 4), "B": round(sum(x[2] for x in todos) / n, 4),
            "por_formato": resumen,
            "ruido_del_juez": {"n_items_identicos": len(ruido),
                               "diferencia_absoluta_media": round(statistics.mean(abs(x[2] - x[3]) for x in ruido), 4) if ruido else None,
                               "diferencia_media_con_signo": round(statistics.mean(x[3] - x[2] for x in ruido), 4) if ruido else None},
            "cambiados": [{"id": i, "formato": f, "A": round(pa, 4), "B": round(pb, 4), "delta": round(pb - pa, 4)}
                          for i, f, pa, pb in cambiados]}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("A", type=Path)
    ap.add_argument("B", type=Path)
    ap.add_argument("--muestra", type=Path, default=Path("data/sample_50.jsonl"))
    ap.add_argument("--salida", type=Path)
    args = ap.parse_args()
    muestra = {}
    for l in args.muestra.read_text(encoding="utf-8").splitlines():
        if l.strip():
            r = json.loads(l)
            muestra[r["pregunta"]] = r
    r = comparar(_cargar(args.A, muestra), _cargar(args.B, muestra))
    print(json.dumps(r, ensure_ascii=False, indent=1))
    if args.salida:
        args.salida.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
