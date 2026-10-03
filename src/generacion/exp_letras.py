"""Experimento rápido de cerradas: probabilidad de cada letra (sin razonar), promediada sobre
permutaciones cíclicas de las opciones, para varias VARIANTES del contexto/prompt en una sola carga
del decoder. Cuesta ~4 s por pregunta y variante (el razonamiento libre, ~45 s).

Con 15 cerradas la exactitud es un número muy ruidoso (un ítem = 0,067). Por eso cada variante
reporta también la log-verosimilitud media de la letra correcta (NLL, más baja es mejor) sobre todas
las permutaciones: es continua y mueve mucho menos con un solo ítem. Las respuestas esperadas se usan
SOLO para medir, nunca dentro del prompt.

    python -m src.generacion.exp_letras --contextos actual=data/exp/contexto_actual.json \
        base=data/exp/contexto_base.json --salida experimentos/claude/letras_1/metricas.json
"""
from __future__ import annotations

import argparse
import ast
import json
import math
import time
from pathlib import Path

from . import cerradas_razonar as cr

# nombre -> (contexto, kwargs de mensajes_letra, k permutaciones)
VARIANTES = {
    "control":        ("actual", {"sistema": None}, 4),
    "sistema_letra":  ("actual", {}, 4),
    "base":           ("base", {}, 4),
    "base_5":         ("base", {"max_pasajes": 5}, 4),
    "base_3":         ("base", {"max_pasajes": 3}, 4),
    "base_invertido": ("base", {"invertir": True}, 4),
    "base_k2":        ("base", {}, 2),
    "base_10":        ("base", {"presupuesto": 6000, "max_pasajes": 10}, 4),
    "base_6":         ("base", {"max_pasajes": 6}, 4),
    "base_repite":    ("base", {}, 4),            # determinismo: debe dar EXACTO lo mismo que "base"
    "base14":         ("base14", {"presupuesto": 6500, "max_pasajes": 14}, 4),
    "base12":         ("base14", {"presupuesto": 5500, "max_pasajes": 12}, 4),
    "mixto":          (("base", "actual"), {}, 4),  # promedio de las probabilidades con los dos contextos
    "solo_opciones":  ("base", {"solo_opcion": True}, 4),
}


def cargar(muestra: Path) -> list[dict]:
    items = []
    for l in muestra.read_text(encoding="utf-8").splitlines():
        if not l.strip():
            continue
        r = json.loads(l)
        if r["formato"] != "multiple_choice":
            continue
        if isinstance(r["opciones"], str):
            r["opciones"] = ast.literal_eval(r["opciones"])
        items.append(r)
    return items


def _pasajes(ctx: dict, it: dict, kw: dict) -> list[dict]:
    ps = ctx.get(str(it["id"])) or ctx.get(it["id"]) or []
    if kw.get("solo_opcion"):                  # variante: solo los pasajes por opción y los directos
        ps = [p for p in ps if p.get("opcion") or p.get("via") == "directo"] or ps
    return ps


def evaluar(motor, items: list[dict], ctx, kw: dict, k: int) -> dict:
    """`ctx` es un contexto ({id: pasajes}) o una lista de ellos: con varios se promedian las
    probabilidades de cada permutación (bagging de evidencias)."""
    filas, t0 = [], time.perf_counter()
    kw = dict(kw)
    presupuesto = kw.pop("presupuesto", 4500)
    ctxs = ctx if isinstance(ctx, list) else [ctx]
    for it in items:
        medias, todas = [], []
        for c in ctxs:
            kwp = {x: v for x, v in kw.items() if x != "solo_opcion"}
            m_, p_ = cr.promedio_permutaciones(motor, it, _pasajes(c, it, kw), presupuesto, k,
                                               getattr(motor, "contar", None), **kwp)
            medias.append(m_)
            todas.append(p_)
        letras_it = sorted(medias[0])
        media = {l: sum(m[l] for m in medias) / len(medias) for l in letras_it}
        perms = [{l: sum(pp[j][l] for pp in todas) / len(todas) for l in letras_it}
                 for j in range(len(todas[0]))]
        gold = it["respuesta_correcta"]
        letra = max(sorted(media), key=lambda l: media[l])
        perms = [{l: max(v, 1e-6) for l, v in p.items()} for p in perms]
        nll = -sum(math.log(max(p[gold], 1e-6)) for p in perms) / len(perms)
        filas.append({"id": it["id"], "esperada": gold, "ens": letra, "ok": letra == gold,
                      "p_gold": round(media[gold], 4), "nll": round(nll, 4),
                      "ok_por_permutacion": [max(p, key=p.get) == gold for p in perms]})
    n = len(filas)
    return {"n": n, "aciertos": sum(f["ok"] for f in filas), "exactitud": round(sum(f["ok"] for f in filas) / n, 4),
            "exactitud_por_permutacion": round(sum(sum(f["ok_por_permutacion"]) for f in filas)
                                               / sum(len(f["ok_por_permutacion"]) for f in filas), 4),
            "nll_medio": round(sum(f["nll"] for f in filas) / n, 4),
            "p_gold_medio": round(sum(f["p_gold"] for f in filas) / n, 4),
            "segundos_por_pregunta": round((time.perf_counter() - t0) / n, 2),
            "ids_acertados": [f["id"] for f in filas if f["ok"]], "filas": filas}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--muestra", type=Path, default=Path("data/sample_50.jsonl"))
    ap.add_argument("--contextos", nargs="+", required=True, help="nombre=ruta.json (pasajes por id)")
    ap.add_argument("--variantes", nargs="+", default=list(VARIANTES))
    ap.add_argument("--modelo", default="qwen3-8b")
    ap.add_argument("--n-ctx", type=int, default=8192)
    ap.add_argument("--salida", type=Path, required=True)
    args = ap.parse_args()
    ctxs = {n: json.loads(Path(r).read_text(encoding="utf-8")) for n, r in (c.split("=", 1) for c in args.contextos)}
    items = cargar(args.muestra)
    from .motor import Motor
    motor = Motor(args.modelo, n_ctx=args.n_ctx)
    res = {}
    for nombre in args.variantes:
        ctx_nombre, kw, k = VARIANTES[nombre]
        nombres = ctx_nombre if isinstance(ctx_nombre, tuple) else (ctx_nombre,)
        if not all(n in ctxs for n in nombres):
            continue
        res[nombre] = evaluar(motor, items, [ctxs[n] for n in nombres] if isinstance(ctx_nombre, tuple)
                              else ctxs[ctx_nombre], kw, k)
        r = res[nombre]
        print(f"RESULTADO letras {nombre}: {r['aciertos']}/{r['n']} · por permutación {r['exactitud_por_permutacion']} "
              f"· NLL {r['nll_medio']} · p_gold {r['p_gold_medio']} · {r['segundos_por_pregunta']} s/preg", flush=True)
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    args.salida.write_text(json.dumps({"modelo": args.modelo, "variantes": res}, ensure_ascii=False, indent=1),
                           encoding="utf-8")


if __name__ == "__main__":
    main()
