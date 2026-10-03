"""Prueba de determinismo de la verificación en vivo: regenera ítems con `Responder` (el camino de
`python -m src.responder --id N` y de la interfaz) y los compara con lo que la corrida por lote
(`src.lote`) ya entregó. Una sola carga de modelos para todos los ids.

    python -m src.analisis.determinismo --entrega data/lote/sample_50/sub_1.jsonl \
        --preguntas data/sample_50.jsonl --ids 51 79 442 865 --salida experimentos/claude/X/determinismo.json

El jurado exige que coincidan las normas citadas y los pasajes recuperados (y casi literal el texto).
Aquí se reporta cada criterio por separado y si la línea completa es idéntica (salvo `latencia_ms`).
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from src import responder


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--entrega", type=Path, required=True)
    ap.add_argument("--preguntas", type=Path, default=Path("data/sample_50.jsonl"))
    ap.add_argument("--ids", type=int, nargs="+")
    ap.add_argument("--n", type=int, default=12, help="si no hay --ids, los primeros n de la entrega")
    ap.add_argument("--salida", type=Path)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S",
                        stream=sys.stdout)
    entregadas = {}
    for linea in args.entrega.read_text(encoding="utf-8").splitlines():
        if linea.strip():
            d = json.loads(linea)
            entregadas[d["id"]] = d
    ids = args.ids or sorted(entregadas)[: args.n]
    cfg = responder.cargar_config()
    resp = responder.Responder(cfg).cargar(con_motor=True)
    filas = []
    for i in ids:
        item = responder.buscar_por_id(i, [args.preguntas])
        vivo = resp.responder(item)
        c = responder.comparar(vivo, entregadas[i])
        sub, ent = vivo["submission"], entregadas[i]
        difieren = sorted(k for k in set(sub) | set(ent) if k != "latencia_ms" and sub.get(k) != ent.get(k))
        filas.append({"id": i, "formato": ent["formato"], "normas_coinciden": c["normas_coinciden"],
                      "pasajes_coinciden": c["pasajes_coinciden"], "mismo_orden": c["mismo_orden"],
                      "identica": c["respuesta_identica"], "campos_distintos": difieren})
        print(f"id {i} [{ent['formato']}]: normas {'=' if c['normas_coinciden'] else '≠'} · pasajes "
              f"{'=' if c['pasajes_coinciden'] else '≠'} · idéntica {c['respuesta_identica']} {difieren}",
              flush=True)
    n = len(filas)
    res = {"n": n, "normas_coinciden": sum(f["normas_coinciden"] for f in filas),
           "pasajes_coinciden": sum(f["pasajes_coinciden"] for f in filas),
           "identicas": sum(f["identica"] for f in filas), "config": cfg, "filas": filas}
    print("RESULTADO determinismo", json.dumps({k: v for k, v in res.items() if k not in ("filas", "config")}))
    if args.salida:
        args.salida.parent.mkdir(parents=True, exist_ok=True)
        args.salida.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0 if res["normas_coinciden"] == n and res["pasajes_coinciden"] == n else 1


if __name__ == "__main__":
    sys.exit(main())
