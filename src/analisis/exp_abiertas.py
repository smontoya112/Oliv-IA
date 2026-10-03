"""Experimento sobre las abiertas de `sample_50`: compara variantes de las piezas de src.generacion.abiertas
(plantilla, expansión de la recuperación, revisión) con UNA carga de modelos y el MISMO camino de la corrida
(`Responder.responder`: recuperación + generación + fase 8).

    python -m src.analisis.exp_abiertas --salida experimentos/claude/abiertas_1/metricas.json

Por variante informa, sobre los ítems abiertos: proxy de RAGAS (0,25·coseno e5 + 0,75·F1 léxico, ver
src.analisis.proxy_texto) y su detalle por ítem, longitud, si el cuerpo normativo del `legal_basis` queda
entre los 10 primeros pasajes (SOLO para evaluar, nunca dentro del sistema), recall de citas del evaluador y
segundos por ítem. Guarda las líneas generadas en `data/exp/bench/ab_<variante>.jsonl`.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from src import responder  # agrega scripts/ al path
from src.analisis import proxy_texto

import citations  # noqa: E402  (scripts/citations.py)
import evaluate  # noqa: E402  (scripts/evaluate.py)

VARIANTES = {
    "A0_actual": [],
    "A1_plantilla": ["plantilla"],
    "A2_plantilla_expansion": ["plantilla", "expansion"],
    "A3_completa": ["plantilla", "expansion", "revision"],
    "A4_expansion": ["expansion"],
    # con la plantilla acortada (analisis <= 200 palabras): A1_plantilla/A2/A3 de abiertas_1 usaban la larga
    "B1_plantilla_corta": ["plantilla"],
    "B2_corta_expansion": ["plantilla", "expansion"],
    "B3_corta_expansion_revision": ["plantilla", "expansion", "revision"],
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--muestra", type=Path, default=Path("data/sample_50.jsonl"))
    ap.add_argument("--variantes", nargs="+", default=list(VARIANTES))
    ap.add_argument("--salida", type=Path, required=True)
    ap.add_argument("--sin-embeddings", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S", stream=sys.stdout)

    muestra = [json.loads(l) for l in args.muestra.read_text(encoding="utf-8").splitlines() if l.strip()]
    abiertas_ref = [r for r in muestra if r["formato"] == "open_ended"]
    cfg = responder.cargar_config()
    resp = responder.Responder(cfg).cargar(con_motor=True)
    res = {}
    for nombre in args.variantes:
        resp.cfg["abiertas"] = VARIANTES[nombre]
        lineas, t0, detalle = [], time.perf_counter(), []
        for r in abiertas_ref:
            item = responder.buscar_por_id(r["id"], [args.muestra])
            t1 = time.perf_counter()
            vivo = resp.responder(item)
            seg = time.perf_counter() - t1
            sub = vivo["submission"]
            lineas.append(sub)
            ref = citations.extract(r.get("legal_basis") or "")
            cuerpos_ref = citations.bodies(ref)
            respaldadas = {c for c in evaluate.citas_respaldadas(sub)}
            en_top10 = cuerpos_ref & citations.bodies(respaldadas) if cuerpos_ref else set()
            sc = citations.score(evaluate.answer_text(sub), r.get("legal_basis") or "", respaldadas) if ref else None
            texto = evaluate.ragas_text(sub)
            detalle.append({"id": r["id"], "segundos": round(seg, 1), "palabras": len(texto.split()),
                            "cuerpos_ref": len(cuerpos_ref), "cuerpos_ref_en_top10": len(en_top10),
                            "aciertos_citas": (sc or {}).get("aciertos"), "n_ref": (sc or {}).get("n_ref"),
                            "lexico": round(proxy_texto.f1_contenido(texto, r["respuesta_esperada"]), 4),
                            "expansion": ((vivo.get("senales") or {}).get("expansion") or {}).get("consultas")})
            logging.info("%s id %s: %.0f s · %d palabras · léxico %.3f · cuerpos ref en top10 %d/%d",
                         nombre, r["id"], seg, detalle[-1]["palabras"], detalle[-1]["lexico"],
                         detalle[-1]["cuerpos_ref_en_top10"], detalle[-1]["cuerpos_ref"])
        if not args.sin_embeddings:
            sem = proxy_texto.similitud_semantica(
                [(evaluate.ragas_text(s), r["respuesta_esperada"]) for s, r in zip(lineas, abiertas_ref)])
            for d, c in zip(detalle, sem):
                d["semantico"] = round(max(c, 0.0), 4)
                d["proxy"] = round(0.75 * d["lexico"] + 0.25 * d["semantico"], 4)
        n = len(detalle)
        medio = lambda k: round(sum(d[k] for d in detalle if k in d) / max(sum(1 for d in detalle if k in d), 1), 4)
        res[nombre] = {"piezas": VARIANTES[nombre], "n": n, "proxy": medio("proxy") if not args.sin_embeddings else None,
                       "lexico": medio("lexico"), "palabras_medias": medio("palabras"), "segundos_medios": medio("segundos"),
                       "cuerpos_ref_en_top10": sum(d["cuerpos_ref_en_top10"] for d in detalle),
                       "cuerpos_ref": sum(d["cuerpos_ref"] for d in detalle),
                       "aciertos_citas": sum(d["aciertos_citas"] or 0 for d in detalle),
                       "n_ref": sum(d["n_ref"] or 0 for d in detalle), "detalle": detalle}
        out = Path("data/exp/bench") / f"ab_{nombre}.jsonl"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("".join(json.dumps(s, ensure_ascii=False) + "\n" for s in lineas), encoding="utf-8")
        print("RESULTADO abiertas", nombre, json.dumps({k: v for k, v in res[nombre].items() if k != "detalle"}), flush=True)
        args.salida.parent.mkdir(parents=True, exist_ok=True)
        args.salida.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
