"""Punto de entrada de la fase 2.

Ejemplos:
    uv run python -m src.descarga.run --fuentes data/fuentes.yaml
    uv run python -m src.descarga.run --fuentes data/fuentes.yaml --solo ley_1564_2012
    uv run python -m src.descarga.run --fuentes data/fuentes.yaml --solo-convertir
    uv run python -m src.descarga.run --fuentes data/fuentes.yaml --forzar
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

from .config import Config
from .fuentes import base_senado, procesar, validar_objetivo
from .http import Cliente, ErrorDescarga
from .manifest import Manifest

log = logging.getLogger("descarga")

# Solo interesan enlaces a fuentes normativas primarias.
_DOMINIOS_NORMATIVOS = ("secretariasenado.gov.co/senado/basedoc", "corteconstitucional.gov.co/relatoria",
                        "suin-juriscol.gov.co", "normograma", "funcionpublica.gov.co/eva/gestornormativo")


def cargar_objetivos(ruta: Path) -> list[dict]:
    texto = ruta.read_text(encoding="utf-8")
    datos = json.loads(texto) if ruta.suffix == ".json" else yaml.safe_load(texto)
    if isinstance(datos, dict):
        datos = datos.get("fuentes") or datos.get("documentos") or list(datos.values())
    if not isinstance(datos, list):
        sys.exit(f"{ruta}: se esperaba una lista de documentos")
    errores, vistos = [], set()
    for i, obj in enumerate(datos):
        for e in validar_objetivo(obj):
            errores.append(f"  entrada {i} ({obj.get('doc_id', '?')}): {e}")
        if obj.get("doc_id") in vistos:
            errores.append(f"  doc_id repetido: {obj['doc_id']}")
        vistos.add(obj.get("doc_id"))
    if errores:
        sys.exit("Errores en el archivo de fuentes:\n" + "\n".join(errores))
    return datos


def registrar_evento(cfg: Config, evento: dict) -> None:
    cfg.ruta_log.parent.mkdir(parents=True, exist_ok=True)
    with cfg.ruta_log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(evento, ensure_ascii=False) + "\n")


def actualizar_descubiertos(cfg: Config, objetivos: list[dict]) -> int:
    """Cuenta qué normas enlazan los documentos descargados y todavía no están en el corpus.
    Sirve para priorizar qué descargar después."""
    ya_incluidas = {base_senado(o["url"]).lower() for o in objetivos}
    veces, citado_por = Counter(), defaultdict(set)
    for ruta in cfg.dir_raw.glob("*/enlaces.json"):
        doc_id = ruta.parent.name
        for url in json.loads(ruta.read_text(encoding="utf-8")):
            if not any(d in url.lower() for d in _DOMINIOS_NORMATIVOS):
                continue
            base = base_senado(url)
            if base.lower() in ya_incluidas:
                continue
            veces[base] += 1
            citado_por[base].add(doc_id)
    with cfg.ruta_descubiertos.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["url", "veces_enlazada", "n_documentos", "enlazada_desde"])
        for url, n in veces.most_common():
            docs = sorted(citado_por[url])
            w.writerow([url, n, len(docs), " ".join(docs[:10])])
    return len(veces)


def main() -> None:
    ap = argparse.ArgumentParser(description="Fase 2: descarga y conversión a Markdown")
    ap.add_argument("--fuentes", type=Path, default=Path("data/fuentes.yaml"))
    ap.add_argument("--raiz", type=Path, default=Path("data"))
    ap.add_argument("--solo", nargs="*", help="procesar solo estos doc_id")
    ap.add_argument("--forzar", action="store_true", help="volver a descargar aunque haya caché")
    ap.add_argument("--solo-convertir", action="store_true",
                    help="no descargar; regenerar el Markdown desde data/raw")
    ap.add_argument("--sin-robots", action="store_true", help="no consultar robots.txt")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    cfg = Config(raiz=args.raiz, respetar_robots=not args.sin_robots)
    objetivos = cargar_objetivos(args.fuentes)
    if args.solo:
        faltan = set(args.solo) - {o["doc_id"] for o in objetivos}
        if faltan:
            sys.exit(f"doc_id no encontrados en {args.fuentes}: {sorted(faltan)}")
        seleccion = [o for o in objetivos if o["doc_id"] in args.solo]
    else:
        seleccion = objetivos

    manifest = Manifest(cfg.ruta_manifest)
    cliente = Cliente(cfg)
    ok, fallos = [], []
    try:
        for obj in seleccion:
            try:
                reg = procesar(obj, cliente, cfg, forzar=args.forzar,
                               solo_convertir=args.solo_convertir)
                manifest.actualizar(reg)
                ok.append(reg)
                log.info("%s: OK · %d partes · %d artículos detectados · %d caracteres",
                         reg["doc_id"], reg["n_partes"], reg["n_articulos_detectados"],
                         reg["n_caracteres"])
                registrar_evento(cfg, {"doc_id": obj["doc_id"], "estado": "ok",
                                       "n_partes": reg["n_partes"]})
            except (ErrorDescarga, OSError, ValueError) as e:
                log.error("%s: %s", obj["doc_id"], e)
                fallos.append((obj["doc_id"], str(e)))
                previo = manifest.get(obj["doc_id"])
                if not previo or previo.get("estado") != "ok":   # no pisar una versión buena
                    manifest.actualizar({**{k: obj.get(k) for k in
                                            ("doc_id", "titulo", "fuente", "url", "areas")},
                                         "estado": "error", "error": str(e)})
                registrar_evento(cfg, {"doc_id": obj["doc_id"], "estado": "error",
                                       "error": str(e)})
    finally:
        cliente.cerrar()

    n_desc = actualizar_descubiertos(cfg, objetivos)
    print(f"\nListos: {len(ok)} · Con error: {len(fallos)} · "
          f"Normas enlazadas aún fuera del corpus: {n_desc} (ver {cfg.ruta_descubiertos})")
    for doc_id, err in fallos:
        print(f"  ✗ {doc_id}: {err}")
    sin_articulos = [r["doc_id"] for r in ok
                     if r["n_articulos_detectados"] == 0 and r.get("tipo_norma") != "sentencia"]
    if sin_articulos:
        print("  ⚠ Sin artículos detectados (revisen el Markdown o el tipo de fuente): "
              + ", ".join(sin_articulos))


if __name__ == "__main__":
    main()
