"""Toma data/descubiertos.csv y deja en un archivo los links de las normas que los documentos del
corpus enlazan y que todavía no se han intentado descargar.

Modo simple (una sola pasada, sobrescribe data/enlaces_proximidad.txt):
    uv run python -m src.descarga.proximidad                # veces_enlazada > 2
    uv run python -m src.descarga.proximidad --minimo 5     # veces_enlazada > 5

Modo por rondas (jobs/scraper_proximidad.sh), para descargar de forma recursiva:
    uv run python -m src.descarga.proximidad --ronda 1 --minimo 0
  - escribe los links NUEVOS de la ronda en data/proximidad/ronda_01.txt,
  - los agrega a data/enlaces_proximidad.txt (acumulado de todas las rondas, que también carga
    jobs/scrapper.sh, así una corrida completa del corpus los incluye),
  - omite lo que ya figura en el manifest (descargado o fallido: lo que falló se reintenta con
    --solo-fallidos dentro de la misma ronda, no en la siguiente).
Luego `run.py` descarga la ronda y recalcula descubiertos.csv con los enlaces de lo recién
bajado: eso alimenta la ronda siguiente. Como "intentado" se decide con el manifest, relanzar el
job después de una interrupción retoma lo que no alcanzó a descargarse.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from .claves import clave_url, claves_registro, prefiere
from .metadatos import leer_enlaces


def seleccionar(ruta_csv: Path, minimo: int) -> list[tuple[str, int]]:
    with ruta_csv.open(encoding="utf-8", newline="") as f:
        filas = [(r["url"].strip(), int(r["veces_enlazada"])) for r in csv.DictReader(f)]
    return sorted(((u, n) for u, n in filas if u and n > minimo), key=lambda x: -x[1])


def claves_en_manifest(ruta: Path) -> set[str]:
    """Normas que ya se intentaron (cualquier estado) según el manifest, sea cual sea la URL con
    que se bajaron."""
    if not ruta.exists():
        return set()
    claves: set[str] = set()
    for r in json.loads(ruta.read_text(encoding="utf-8")):
        claves |= claves_registro(r)
    return claves


def nueva_ronda(descubiertos: Path, manifest: Path, acumulado: Path, dir_rondas: Path, ronda: int,
                minimo: int, maximo: int | None) -> tuple[Path, list[tuple[str, int]], int]:
    """Escribe ronda_NN.txt y agrega sus links al acumulado. Devuelve (archivo, links, n_ya_intentados)."""
    intentadas = claves_en_manifest(manifest)
    candidatos = seleccionar(descubiertos, minimo)
    nuevos, vistas = [], set()
    # La misma norma puede estar listada con varias URLs (Senado, DIAN...): se queda una, la del Senado primero.
    for u, n in sorted(candidatos, key=lambda x: (prefiere(x[0])[0], -x[1])):
        k = clave_url(u)
        if k in intentadas or k in vistas:
            continue
        vistas.add(k)
        nuevos.append((u, n))
    nuevos.sort(key=lambda x: -x[1])
    ya = len(candidatos) - len(nuevos)
    if maximo:
        nuevos = nuevos[:maximo]
    dir_rondas.mkdir(parents=True, exist_ok=True)
    archivo = dir_rondas / f"ronda_{ronda:02d}.txt"
    lineas = [f"# Ronda {ronda} (src/descarga/proximidad.py): veces_enlazada > {minimo}, "
              f"{len(nuevos)} links nuevos. No editar a mano."]
    lineas += [f"{url}  # enlazada {n} veces" for url, n in nuevos]
    archivo.write_text("\n".join(lineas) + "\n", encoding="utf-8")

    previos = set()
    if acumulado.exists():
        previos = {clave_url(u) for u in leer_enlaces(acumulado)}
    agregar = [f"{u}  # ronda {ronda}, enlazada {n} veces" for u, n in nuevos if clave_url(u) not in previos]
    if agregar:
        acumulado.parent.mkdir(parents=True, exist_ok=True)
        with acumulado.open("a", encoding="utf-8") as f:
            if not acumulado.stat().st_size:
                f.write("# Acumulado de todas las rondas de src/descarga/proximidad.py.\n")
            f.write("\n".join(agregar) + "\n")
    return archivo, nuevos, ya


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--descubiertos", type=Path, default=Path("data/descubiertos.csv"))
    ap.add_argument("--salida", type=Path, default=Path("data/enlaces_proximidad.txt"),
                    help="modo simple: archivo de salida; modo rondas: el acumulado")
    ap.add_argument("--minimo", type=int, default=2,
                    help="se incluyen los links con veces_enlazada ESTRICTAMENTE mayor "
                         "(0 = todos los descubiertos)")
    ap.add_argument("--ronda", type=int, help="modo por rondas: número de la ronda (1, 2, ...)")
    ap.add_argument("--max", type=int, default=0, dest="maximo",
                    help="modo rondas: tope de links por ronda (los más enlazados primero; 0 = sin tope)")
    ap.add_argument("--manifest", type=Path, default=Path("data/corpus_manifest.json"))
    ap.add_argument("--dir-rondas", type=Path, default=Path("data/proximidad"))
    args = ap.parse_args()

    if not args.descubiertos.exists():
        raise SystemExit(f"No existe {args.descubiertos}: corran primero jobs/scrapper.sh")

    if args.ronda:
        archivo, nuevos, ya = nueva_ronda(args.descubiertos, args.manifest, args.salida,
                                          args.dir_rondas, args.ronda, args.minimo, args.maximo or None)
        print(f"ronda {args.ronda}: {len(nuevos)} links nuevos con veces_enlazada > {args.minimo} "
              f"({ya} ya intentados o repetidos se omiten) -> {archivo}")
        return

    elegidos = seleccionar(args.descubiertos, args.minimo)
    lineas = [f"# Generado por src/descarga/proximidad.py: veces_enlazada > {args.minimo}. "
              "No editar a mano."]
    lineas += [f"{url}  # enlazada {n} veces" for url, n in elegidos]
    args.salida.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    print(f"{len(elegidos)} links con veces_enlazada > {args.minimo} -> {args.salida}")


if __name__ == "__main__":
    main()
