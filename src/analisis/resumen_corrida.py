"""Resume UNA corrida sobre `sample_50` en un JSON: evaluador oficial (sin RAGAS), proxy de texto
libre, exactitud de cerradas por política de decisión y tiempos. Es lo que se guarda en
`experimentos/claude/<corrida>/metricas.json`.

    python -m src.analisis.resumen_corrida --submission data/processed/bench_generacion/E1.jsonl \
        --salida experimentos/claude/E1/metricas.json [--sin-embeddings] [--csv bench_generacion.csv]

Las políticas (letra_razonada, letra_resolver, letra_ens, letra_evidencia y su voto) salen de
`decision_cerrada`, que la estrategia "razonada" guarda por ítem: una sola corrida permite
comparar todas sin volver a generar. No usa RAGAS ni red.
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path

from src.generacion.cerradas_razonar import UMBRAL_RAZONADA, UMBRAL_VOTO

RAIZ = Path(__file__).resolve().parents[2]


def _jsonl(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def politicas_cerradas(entrega: list[dict], muestra: list[dict]) -> dict:
    clave = {r["id"]: r["respuesta_correcta"] for r in muestra if r["formato"] == "multiple_choice"}
    sub = {s["id"]: s for s in entrega}
    cuentas: dict[str, list[int]] = {k: [] for k in
                                     ("final", "razonada", "resolver", "ens", "evidencia", "voto")}
    detalle = {}
    for i, k in sorted(clave.items()):
        d = (sub.get(i) or {}).get("decision_cerrada") or {}
        final = (sub.get(i) or {}).get("respuesta_correcta")
        razonada, ens, evid = d.get("letra_razonada") or d.get("letra_modelo"), d.get("letra_ens"), d.get("letra_evidencia")
        p = d.get("p_ens") or {}
        voto = ens if (ens and ens != razonada and p.get(ens, 0) >= UMBRAL_VOTO
                       and p.get(razonada, 0) <= UMBRAL_RAZONADA) else razonada
        letras = {"final": final, "razonada": razonada, "resolver": d.get("letra_resolver"),
                  "ens": ens, "evidencia": evid, "voto": voto}
        for nombre, letra in letras.items():
            if letra == k:
                cuentas[nombre].append(i)
        detalle[i] = {"esperada": k, **letras, "regla": d.get("regla"),
                      "tokens_pensar": d.get("tokens_pensar"), "cortado": d.get("pensamiento_cortado")}
    n = len(clave)
    return {"n": n, "aciertos": {k: len(v) for k, v in cuentas.items()},
            "exactitud": {k: round(len(v) / n, 4) if n else None for k, v in cuentas.items()},
            "ids_acertados_final": cuentas["final"], "detalle": detalle}


def oficial(entrega: Path) -> dict:
    """scripts/evaluate.py --split sample (sin --ragas) como subproceso: el reporte oficial."""
    sal = entrega.with_suffix(".oficial.json")
    r = subprocess.run([sys.executable, str(RAIZ / "scripts" / "evaluate.py"), "--submission",
                        str(entrega), "--split", "sample", "--out", str(sal)],
                       capture_output=True, text=True, cwd=RAIZ)
    if not sal.exists():
        return {"error": (r.stderr or r.stdout)[-400:]}
    rep = json.loads(sal.read_text(encoding="utf-8"))
    sal.unlink()
    return rep


def tiempos_de_entrega(entrega: list[dict]) -> dict:
    """Segundos por pregunta a partir de `latencia_ms` de cada línea (solo generación)."""
    por = {}
    for s in entrega:
        if s.get("latencia_ms") is not None:
            por.setdefault(s["formato"], []).append(s["latencia_ms"] / 1000)
    res = {f: {"n": len(v), "s_por_pregunta": round(sum(v) / len(v), 2)} for f, v in por.items()}
    if len(res) == 3:
        pesos = {"multiple_choice": 289, "semi_open": 633, "open_ended": 70}
        res["s_medio_mezcla_test"] = round(sum(res[k]["s_por_pregunta"] * w for k, w in pesos.items()) / 992, 2)
    return res


def tiempos(csv_ruta: Path | None, etiqueta: str) -> dict:
    if not csv_ruta or not csv_ruta.exists():
        return {}
    filas = [f for f in csv.DictReader(csv_ruta.open(encoding="utf-8")) if f["modelo"] == etiqueta]
    ult = {}
    for f in filas:                                    # la última fila de cada formato
        ult[f["formato"]] = {"n": int(f["n"]), "s_por_pregunta": float(f["s_por_pregunta"])}
    if len(ult) == 3:
        # mezcla esperada en el test (aprox. 289 cerradas, 633 semiabiertas, 70 abiertas de 992)
        pesos = {"multiple_choice": 289, "semi_open": 633, "open_ended": 70}
        ult["s_medio_mezcla_test"] = round(sum(ult[k]["s_por_pregunta"] * w for k, w in pesos.items()) / 992, 2)
    return ult


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--submission", type=Path, required=True)
    ap.add_argument("--muestra", type=Path, default=Path("data/sample_50.jsonl"))
    ap.add_argument("--salida", type=Path, required=True)
    ap.add_argument("--sin-embeddings", action="store_true")
    ap.add_argument("--csv", type=Path, default=Path("data/processed/bench_generacion.csv"))
    ap.add_argument("--etiqueta", help="nombre en el CSV de tiempos (por defecto, el del archivo)")
    args = ap.parse_args()

    entrega, muestra = _jsonl(args.submission), _jsonl(args.muestra)
    from src.analisis import proxy_texto
    rep = oficial(args.submission)
    res = {"submission": args.submission.as_posix(), "oficial": rep,
           "cerradas_politicas": politicas_cerradas(entrega, muestra),
           "texto_libre_proxy": {k: v for k, v in proxy_texto.evaluar(
               entrega, muestra, not args.sin_embeddings).items() if k != "filas"},
           "tiempos": tiempos(args.csv, args.etiqueta or args.submission.stem)
           or tiempos_de_entrega(entrega),
           "abstenciones": sum(1 for s in entrega if s.get("abstencion"))}
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    args.salida.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    c = res["cerradas_politicas"]
    print("RESULTADO cerradas", json.dumps(c["aciertos"]), "de", c["n"],
          "| proxy", res["texto_libre_proxy"]["proxy"],
          "| citas", (rep.get("citas") or {}).get("indice"),
          "| tiempos", json.dumps(res["tiempos"]))


if __name__ == "__main__":
    main()
