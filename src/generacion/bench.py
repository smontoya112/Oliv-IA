"""Compara decoders sobre las muestras: tiempo por formato, validez del JSON y exactitud en
cerradas. Escribe las predicciones (submission) y una fila por (modelo, formato) en un CSV.

    python -m src.generacion.bench --modelo qwen3-8b --contexto data/processed/contexto_oraculo.json
    python -m src.generacion.bench --modelo qwen3-8b llama-3.1-8b salamandra-7b --contexto …

Luego, para la corrección en texto libre (juez RAGAS):
    python scripts/evaluate.py --submission <salida>/<modelo>.jsonl --split sample --ragas
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
import time
from pathlib import Path

from .pipeline import generar_lote

log = logging.getLogger("generacion")
CAMPOS_CSV = ["fecha", "modelo", "contexto", "formato", "n", "segundos", "s_por_pregunta",
              "proyeccion_992_horas", "validos", "abstenciones", "exactitud_cerradas"]


def _configurar_logs() -> None:
    """Avance -> stdout (.out del job); solo los ERROR -> stderr (.err del job)."""
    salida = logging.StreamHandler(sys.stdout)
    salida.addFilter(lambda r: r.levelno < logging.ERROR)
    errores = logging.StreamHandler(sys.stderr)
    errores.setLevel(logging.ERROR)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S",
                        handlers=[salida, errores])


def _validar(subs: list[dict], esperados: set[int]) -> list[str]:
    import evaluate  # scripts/evaluate.py
    return evaluate.validate(subs, esperados)


def correr(modelo: str, items: list[dict], pasajes: dict, salida: Path, contexto: str,
           n_ctx: int, catalogo=None) -> list[dict]:
    from .motor import Motor
    motor = Motor(modelo, n_ctx=n_ctx)
    todas, filas = [], []
    for formato in ("multiple_choice", "semi_open", "open_ended"):
        lote = [it for it in items if it["formato"] == formato]
        if not lote:
            continue
        t0 = time.perf_counter()
        subs = generar_lote(lote, pasajes, motor, catalogo=catalogo)
        seg = time.perf_counter() - t0
        problemas = _validar(subs, {it["id"] for it in lote})
        validos = len(lote) - len({int(p.split()[1].rstrip(':')) for p in problemas
                                   if p.startswith("item ")})
        exact = None
        if formato == "multiple_choice":
            clave = {it["id"]: it["respuesta_correcta"] for it in lote}
            exact = round(sum(s.get("respuesta_correcta") == clave[s["id"]] for s in subs)
                          / len(subs), 3)
        filas.append({"fecha": time.strftime("%F %T"), "modelo": modelo, "contexto": contexto,
                      "formato": formato, "n": len(lote), "segundos": round(seg, 1),
                      "s_por_pregunta": round(seg / len(lote), 2),
                      "proyeccion_992_horas": round(seg / len(lote) * 992 / 3600, 2),
                      "validos": validos, "abstenciones": sum(s["abstencion"] for s in subs),
                      "exactitud_cerradas": exact})
        log.info("%s/%s: %d ítems en %.1f s (%.2f s/pregunta), válidos %d, exactitud %s",
                 modelo, formato, len(lote), seg, seg / len(lote), validos, exact)
        for p in problemas:
            log.error("%s: %s", modelo, p)
        todas += subs
    salida.mkdir(parents=True, exist_ok=True)
    with (salida / f"{modelo}.jsonl").open("w", encoding="utf-8") as f:
        for s in sorted(todas, key=lambda s: s["id"]):
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    return filas


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--modelo", nargs="+", required=True, help="alias de motor.MODELOS o un id de HF")
    ap.add_argument("--contexto", type=Path, required=True,
                    help="JSON {id: [pasajes]} de src.generacion.contexto_prueba")
    ap.add_argument("--muestra", type=Path, default=Path("data/sample_50.jsonl"))
    ap.add_argument("--salida", type=Path, default=Path("data/processed/bench_generacion"))
    ap.add_argument("--csv", type=Path, default=Path("data/processed/bench_generacion.csv"))
    ap.add_argument("--n-ctx", type=int, default=8192)
    ap.add_argument("--catalogo", type=Path, default=None,
                    help="data/index: la fase 8 respalda las citas con el corpus en vez de borrarlas")
    args = ap.parse_args()
    _configurar_logs()

    items = [json.loads(l) for l in args.muestra.read_text(encoding="utf-8").splitlines() if l.strip()]
    pasajes = {int(k): v for k, v in json.loads(args.contexto.read_text(encoding="utf-8")).items()}
    catalogo = None
    if args.catalogo:
        from src.recuperacion.catalogo import cargar
        catalogo = cargar(args.catalogo)
    nuevo = not args.csv.exists()
    args.csv.parent.mkdir(parents=True, exist_ok=True)
    for modelo in args.modelo:
        try:
            filas = correr(modelo, items, pasajes, args.salida, args.contexto.stem,
                           args.n_ctx, catalogo)
        except Exception as e:                      # un modelo roto no detiene a los demás
            log.error("%s: %s: %s", modelo, type(e).__name__, e)
            continue
        with args.csv.open("a", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, CAMPOS_CSV)
            if nuevo:
                w.writeheader()
                nuevo = False
            w.writerows(filas)


if __name__ == "__main__":
    main()
