"""Genera una entrega de línea base con abstención en todos los ítems de un split.

Uso:
    uv run python scripts/baseline_abstencion.py \
        --preguntas data/sample_50.jsonl --salida submissions.jsonl
"""
import argparse
import copy
import json
from collections import Counter

# Claves obligatorias por formato, vacías porque el sistema se abstiene.
PLANTILLAS = {
    "multiple_choice": {"respuesta_correcta": "", "justificacion": "", "descarte_opciones": {}},
    "semi_open": {"respuesta": "", "palabras_clave": [], "referencia_legal": ""},
    "open_ended": {"marco_normativo": "", "analisis": "", "jurisprudencia": "", "conclusion": ""},
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preguntas", default="data/sample_50.jsonl")
    parser.add_argument("--salida", default="submissions.jsonl")
    args = parser.parse_args()

    conteo = Counter()
    with open(args.preguntas, encoding="utf-8") as fin, \
         open(args.salida, "w", encoding="utf-8") as fout:
        for num_linea, linea in enumerate(fin, start=1):
            if not linea.strip():
                continue
            item = json.loads(linea)
            formato = item.get("formato")
            if formato not in PLANTILLAS:
                raise ValueError(
                    f"Línea {num_linea}: formato desconocido {formato!r}. "
                    f"Claves del ítem: {list(item.keys())}"
                )
            fila = {
                "id": item["id"],
                "formato": formato,
                "abstencion": True,
                **copy.deepcopy(PLANTILLAS[formato]),
                "pasajes_recuperados": [],
            }
            fout.write(json.dumps(fila, ensure_ascii=False) + "\n")
            conteo[formato] += 1

    print(f"{sum(conteo.values())} ítems escritos en {args.salida}: {dict(conteo)}")


if __name__ == "__main__":
    main()