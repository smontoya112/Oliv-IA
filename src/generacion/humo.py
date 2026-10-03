"""Prueba de humo del motor razonado en la GPU: carga el decoder, responde UNA cerrada con la
estrategia "razonada" y verifica que las dos fases (razonar y comprometer) y los logits funcionan.
También mide que el mismo ítem, dos veces seguidas, da exactamente la misma salida.

    python -m src.generacion.humo --id 528 [--modelo qwen3-8b] [--contexto data/recuperacion/sample_50.jsonl]
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from . import cerradas_razonar
from .motor import Motor


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--id", type=int, default=528)
    ap.add_argument("--modelo", default="qwen3-8b")
    ap.add_argument("--muestra", type=Path, default=Path("data/sample_50.jsonl"))
    ap.add_argument("--contexto", type=Path, default=Path("data/recuperacion/sample_50.jsonl"))
    ap.add_argument("--n-ctx", type=int, default=8192)
    args = ap.parse_args()
    item = next(json.loads(l) for l in args.muestra.read_text(encoding="utf-8").splitlines()
                if l.strip() and json.loads(l)["id"] == args.id)
    if isinstance(item["opciones"], str):                 # algunas filas traen el dict como texto
        import ast
        item["opciones"] = ast.literal_eval(item["opciones"])
    pasajes = next(json.loads(l)["pasajes"] for l in args.contexto.read_text(encoding="utf-8").splitlines()
                   if l.strip() and json.loads(l)["id"] == args.id)
    t0 = time.perf_counter()
    motor = Motor(args.modelo, n_ctx=args.n_ctx)
    print(f"carga {time.perf_counter() - t0:.1f} s · admite_pensar={motor.admite_pensar}")
    salidas = []
    for k in range(2):
        t0 = time.perf_counter()
        s = cerradas_razonar.responder(item, pasajes, motor, politica="razonada")
        d = s["decision_cerrada"]
        print(f"[{k}] {time.perf_counter() - t0:.1f} s · final={s['respuesta_correcta']} "
              f"(esperada {item.get('respuesta_correcta')}) razonada={d['letra_razonada']} "
              f"ens={d['letra_ens']} p_ens={d['p_ens']} tokens_pensar={d['tokens_pensar']} "
              f"cortado={d['pensamiento_cortado']}")
        salidas.append(json.dumps(s, sort_keys=True, ensure_ascii=False))
    print("JUSTIFICACION:", s["justificacion"][:300])
    print("RESULTADO humo: dos corridas seguidas", "IGUALES" if salidas[0] == salidas[1] else "DISTINTAS")


if __name__ == "__main__":
    main()
