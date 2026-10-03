"""Paso 9.4: consolida en un CSV (formato largo) los parámetros, tiempos y métricas de los
experimentos ya corridos, leyendo los resultados que dejaron los jobs.

    python -m src.analisis.registro_experimentos            # -> data/processed/experimentos.csv

Fuentes: data/recuperacion/ablaciones.json (fase 6), data/processed/bench_generacion.csv (fase 7),
data/processed/ragas_*.json (fase 7, evaluate.py --ragas) y data/processed/verificacion/eval_*.json
(fase 8). Se regenera completo cada vez: los resultados de origen son el historial.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

CAMPOS = ["fase", "experimento", "parametros", "metrica", "valor", "fuente"]


def _filas(fase: str, exp: str, params: str, metricas: dict, fuente: Path) -> list[dict]:
    return [{"fase": fase, "experimento": exp, "parametros": params, "metrica": m, "valor": v,
             "fuente": fuente.as_posix()} for m, v in metricas.items() if v is not None]


def recuperacion(ruta: Path) -> list[dict]:
    if not ruta.exists():
        return []
    filas = []
    for corrida, res in json.loads(ruta.read_text(encoding="utf-8")).items():
        if not isinstance(res, dict) or "todos" not in res:
            continue
        cfg = ruta.with_name(f"{corrida}.config.json")
        params = cfg.read_text(encoding="utf-8").replace("\n", " ") if cfg.exists() else corrida
        filas += _filas("6", corrida, " ".join(params.split()), res["todos"], ruta)
    return filas


def generacion(ruta: Path) -> list[dict]:
    if not ruta.exists():
        return []
    filas = []
    with ruta.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            exp = f"{r['modelo']}/{r['contexto']}/{r['formato']}@{r['fecha']}"
            m = {k: float(r[k]) if r[k] else None for k in
                 ("n", "segundos", "s_por_pregunta", "proyeccion_992_horas", "validos",
                  "abstenciones", "exactitud_cerradas")}
            filas += _filas("7", exp, f"modelo={r['modelo']} contexto={r['contexto']}", m, ruta)
    return filas


def evaluaciones(ruta: Path, fase: str) -> list[dict]:
    r = json.loads(ruta.read_text(encoding="utf-8"))
    ragas = r.get("correccion_ragas") or {}
    m = {"cerradas_accuracy": r["cerradas"]["accuracy"], "citas_indice": r["citas"]["indice"],
         "citas_incorrectas": r["citas"]["incorrectas"],
         "tasa_sin_respaldo": r["citas"]["tasa_sin_respaldo"],
         "abstencion_calibracion": r["abstencion"]["calibracion"],
         "ragas_correctness": ragas.get("correctness"), "ragas_fallidos": ragas.get("n_fallidos"),
         "total_automatico": r["total_automatico"]["obtenidos"]}
    return _filas(fase, ruta.stem, f"split={r.get('split')} equipo={r.get('equipo')}", m, ruta)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--procesados", type=Path, default=Path("data/processed"))
    ap.add_argument("--recuperacion", type=Path, default=Path("data/recuperacion/ablaciones.json"))
    ap.add_argument("--salida", type=Path, default=Path("data/processed/experimentos.csv"))
    args = ap.parse_args()

    filas = recuperacion(args.recuperacion) + generacion(args.procesados / "bench_generacion.csv")
    for ruta in sorted(args.procesados.glob("ragas_*.json")):
        filas += evaluaciones(ruta, "7")
    for ruta in sorted((args.procesados / "verificacion").glob("eval_*.json")):
        filas += evaluaciones(ruta, "8")
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    with args.salida.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, CAMPOS)
        w.writeheader()
        w.writerows(filas)
    print(f"{len(filas)} filas -> {args.salida}")


if __name__ == "__main__":
    main()
