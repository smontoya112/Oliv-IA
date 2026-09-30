"""Toma data/descubiertos.csv y deja en data/enlaces_proximidad.txt los links de las normas
que los documentos del corpus enlazan más de N veces (por defecto, más de 2).

    uv run python -m src.descarga.proximidad                # veces_enlazada > 2
    uv run python -m src.descarga.proximidad --minimo 5     # veces_enlazada > 5

Luego se descargan con:
    uv run python -m src.descarga.run --solo-enlaces --enlaces data/enlaces_proximidad.txt
(el job jobs/scraper_proximidad.sh hace las dos cosas). Como run.py recalcula
descubiertos.csv al terminar, volver a correr el job avanza al siguiente "anillo" de normas.
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path


def seleccionar(ruta_csv: Path, minimo: int) -> list[tuple[str, int]]:
    with ruta_csv.open(encoding="utf-8", newline="") as f:
        filas = [(r["url"].strip(), int(r["veces_enlazada"])) for r in csv.DictReader(f)]
    return sorted(((u, n) for u, n in filas if u and n > minimo), key=lambda x: -x[1])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--descubiertos", type=Path, default=Path("data/descubiertos.csv"))
    ap.add_argument("--salida", type=Path, default=Path("data/enlaces_proximidad.txt"))
    ap.add_argument("--minimo", type=int, default=2,
                    help="se incluyen los links con veces_enlazada ESTRICTAMENTE mayor (2)")
    args = ap.parse_args()

    if not args.descubiertos.exists():
        raise SystemExit(f"No existe {args.descubiertos}: corran primero jobs/scrapper.sh")
    elegidos = seleccionar(args.descubiertos, args.minimo)
    lineas = [f"# Generado por src/descarga/proximidad.py: veces_enlazada > {args.minimo}. "
              "No editar a mano."]
    lineas += [f"{url}  # enlazada {n} veces" for url, n in elegidos]
    args.salida.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    print(f"{len(elegidos)} links con veces_enlazada > {args.minimo} -> {args.salida}")


if __name__ == "__main__":
    main()
