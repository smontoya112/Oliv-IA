"""Punto de entrada de la fase 2.

Por defecto carga data/fuentes_seed.json, data/fuentes_propias.json y, al final,
data/enlaces.txt: un link por línea, sin nada más. Del link se deduce el doc_id, y al
descargar se completa el resto de la metadata (título, tipo, número, año, áreas...).

Ejemplos:
    uv run python -m src.descarga.run                           # todo
    uv run python -m src.descarga.run --solo codigo_general_proceso
    uv run python -m src.descarga.run --solo-fallidos           # reintentar lo que falló
    uv run python -m src.descarga.run --solo-convertir          # regenerar Markdown sin red
    uv run python -m src.descarga.run --fuentes data/mi_lista.json   # solo una lista
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from collections import Counter, defaultdict
from pathlib import Path

from .claves import clave_url, claves_objetivo, claves_registro, prefiere
from .config import Config
from .fuentes import base_senado, procesar, validar_objetivo
from .http import Cliente, ErrorDescarga
from .metadatos import hacer_ids_unicos, leer_enlaces, objetivo_desde_url
from .manifest import Manifest

log = logging.getLogger("descarga")

# Solo interesan enlaces a fuentes normativas primarias.
_DOMINIOS_NORMATIVOS = ("secretariasenado.gov.co/senado/basedoc", "corteconstitucional.gov.co/relatoria",
                        "suin-juriscol.gov.co", "normograma", "funcionpublica.gov.co/eva/gestornormativo")


def cargar_objetivos(rutas: list[Path]) -> list[dict]:
    """Carga uno o varios archivos. Si un doc_id aparece en varios, gana el último archivo:
    así una lista propia puede corregir o reemplazar entradas generadas desde el seed."""
    combinados: dict[str, dict] = {}
    for ruta in rutas:
        for obj in _cargar_archivo(ruta):
            if obj["doc_id"] in combinados:
                log.info("%s: %s reemplaza la entrada anterior", obj["doc_id"], ruta.name)
            combinados[obj["doc_id"]] = obj
    # Primero lo que más pesa en el banco.
    return sorted(combinados.values(), key=lambda o: -(o.get("items_del_banco") or 0))


def _cargar_archivo(ruta: Path) -> list[dict]:
    texto = ruta.read_text(encoding="utf-8")
    try:
        datos = json.loads(texto)
    except json.JSONDecodeError as e:
        sys.exit(f"{ruta}: JSON inválido ({e})")
    if isinstance(datos, dict):
        datos = datos.get("fuentes") or datos.get("documentos") or list(datos.values())
    if not isinstance(datos, list):
        sys.exit(f"{ruta}: se esperaba una lista de documentos")
    errores, vistos = [], set()
    for i, obj in enumerate(datos):
        for e in validar_objetivo(obj):
            errores.append(f"  entrada {i} ({obj.get('doc_id', '?')}): {e}")
        if obj.get("doc_id") in vistos:
            errores.append(f"  doc_id repetido dentro de {ruta.name}: {obj['doc_id']}")
        vistos.add(obj.get("doc_id"))
    if errores:
        sys.exit(f"Errores en {ruta}:\n" + "\n".join(errores))
    return datos or []


def objetivos_desde_enlaces(ruta: Path, existentes: list[dict],
                            registros: list[dict] | tuple = ()) -> list[dict]:
    """Un objetivo por cada link de la lista que no sea ya una norma conocida.

    Identidad: dos links son el mismo documento si comparten clave (src.descarga.claves), sea cual
    sea el host, la ruta o el ceros a la izquierda. Un link repetido, o que ya está en las demás
    fuentes (`existentes`), se omite.
    `registros` son las entradas del manifest de corridas anteriores: si el link ya fue descargado,
    el objetivo REUTILIZA su doc_id (misma norma = mismo documento: se sirve del caché y no se baja
    otra vez). Un sufijo -2, -3... solo se usa cuando un doc_id igual pertenece a OTRA norma.
    Cada objetivo guarda en `origen` el nombre del archivo del que salió (p. ej. ronda_02)."""
    vistas: set[str] = set()
    for o in existentes:
        vistas |= claves_objetivo(o)
    id_por_clave: dict[str, str] = {}
    for r in registros:
        for k in claves_registro(r):
            id_por_clave.setdefault(k, r["doc_id"])

    nuevos, fijos = [], set()
    for url in leer_enlaces(ruta):
        obj = {**objetivo_desde_url(url), "origen": ruta.stem}
        claves = claves_objetivo(obj)
        if claves & vistas:
            log.info("%s: la misma norma ya está en el corpus o en la lista, se omite", url)
            continue
        vistas |= claves
        previo = next((id_por_clave[k] for k in sorted(claves) if k in id_por_clave), None)
        if previo:
            obj["doc_id"] = previo
            fijos.add(previo)
        nuevos.append(obj)
    ocupados = {o["doc_id"] for o in existentes} | {r["doc_id"] for r in registros} | fijos
    hacer_ids_unicos([o for o in nuevos if o["doc_id"] not in fijos], ocupados)
    return nuevos


class _SoloMenosQue(logging.Filter):
    def __init__(self, nivel: int):
        super().__init__()
        self.nivel = nivel

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno < self.nivel


def configurar_logs(verbose: bool) -> None:
    """Avance normal -> stdout (.out del job). Solo los ERROR -> stderr (.err del job)."""
    for flujo in (sys.stdout, sys.stderr):      # la consola de Windows usa cp1252 y rompe con ✗ o ⚠
        flujo.reconfigure(encoding="utf-8", errors="replace")
    formato = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S")
    salida = logging.StreamHandler(sys.stdout)
    salida.addFilter(_SoloMenosQue(logging.ERROR))
    errores = logging.StreamHandler(sys.stderr)
    errores.setLevel(logging.ERROR)
    for h in (salida, errores):
        h.setFormatter(formato)
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, handlers=[salida, errores])
    logging.getLogger("httpx").setLevel(logging.WARNING)


def registrar_evento(cfg: Config, evento: dict) -> None:
    cfg.ruta_log.parent.mkdir(parents=True, exist_ok=True)
    with cfg.ruta_log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(evento, ensure_ascii=False) + "\n")


def actualizar_descubiertos(cfg: Config, objetivos: list[dict], manifest: Manifest) -> int:
    """Cuenta qué normas enlazan los documentos descargados y todavía no están en el corpus.
    Sirve para priorizar qué descargar después. Las distintas URLs de una misma norma cuentan como
    una sola (src.descarga.claves) y lo ya descargado, bajo cualquier URL, no se vuelve a listar."""
    ya_incluidas: set[str] = set()
    for o in objetivos:
        ya_incluidas |= claves_objetivo(o)
    for r in manifest.docs.values():            # lo ya descargado en corridas anteriores
        if r.get("estado") == "ok":
            ya_incluidas |= claves_registro(r)
    veces, citado_por, mejor_url = Counter(), defaultdict(set), {}
    for ruta in cfg.dir_raw.glob("*/enlaces.json"):
        doc_id = ruta.parent.name
        for url in json.loads(ruta.read_text(encoding="utf-8")):
            if not any(d in url.lower() for d in _DOMINIOS_NORMATIVOS):
                continue
            clave = clave_url(url)
            if clave in ya_incluidas:
                continue
            base = base_senado(url)
            veces[clave] += 1
            citado_por[clave].add(doc_id)
            if clave not in mejor_url or prefiere(base) < prefiere(mejor_url[clave]):
                mejor_url[clave] = base
    with cfg.ruta_descubiertos.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["url", "veces_enlazada", "n_documentos", "enlazada_desde"])
        for clave, n in veces.most_common():
            docs = sorted(citado_por[clave])
            w.writerow([mejor_url[clave], n, len(docs), " ".join(docs[:10])])
    return len(veces)


def main() -> None:
    ap = argparse.ArgumentParser(description="Fase 2: descarga y conversión a Markdown")
    ap.add_argument("--fuentes", type=Path, nargs="+",
                    default=[Path("data/fuentes_seed.json"), Path("data/fuentes_propias.json")],
                    help="uno o varios .json; en doc_id repetidos gana el último "
                         "(los predeterminados que no existan se omiten)")
    ap.add_argument("--enlaces", type=Path, nargs="+",
                    default=[Path("data/enlaces.txt"), Path("data/enlaces_proximidad.txt")],
                    help="archivos con un link por línea; la metadata se completa sola "
                         "(los predeterminados que no existan se omiten)")
    ap.add_argument("--solo-enlaces", action="store_true",
                    help="procesar solo los links de --enlaces (las demás fuentes solo se "
                         "cargan para no duplicar)")
    ap.add_argument("--raiz", type=Path, default=Path("data"))
    ap.add_argument("--solo", nargs="*", help="procesar solo estos doc_id")
    ap.add_argument("--forzar", action="store_true", help="volver a descargar aunque haya caché")
    ap.add_argument("--solo-convertir", action="store_true",
                    help="no descargar; regenerar el Markdown desde data/raw")
    ap.add_argument("--solo-fallidos", action="store_true",
                    help="procesar solo lo que no está 'ok' en el manifest")
    ap.add_argument("--sin-robots", action="store_true", help="no consultar robots.txt")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    configurar_logs(args.verbose)

    cfg = Config(raiz=args.raiz, respetar_robots=not args.sin_robots)
    rutas = [r for r in args.fuentes if r.exists() or args.fuentes != ap.get_default("fuentes")]
    objetivos = cargar_objetivos(rutas)
    manifest = Manifest(cfg.ruta_manifest)
    nuevos: list[dict] = []
    for ruta in args.enlaces:
        if not ruta.exists():
            if args.enlaces != ap.get_default("enlaces"):
                sys.exit(f"No existe {ruta}")
            continue
        extra = objetivos_desde_enlaces(ruta, objetivos + nuevos, list(manifest.docs.values()))
        log.info("%s: %d links nuevos", ruta, len(extra))
        nuevos.extend(extra)
    objetivos.extend(nuevos)
    if not objetivos:
        sys.exit("No hay nada que descargar: agreguen links a data/enlaces.txt")
    if args.solo:
        faltan = set(args.solo) - {o["doc_id"] for o in objetivos}
        if faltan:
            sys.exit(f"doc_id no encontrados en los archivos de fuentes: {sorted(faltan)}")
        seleccion = [o for o in objetivos if o["doc_id"] in args.solo]
    else:
        seleccion = nuevos if args.solo_enlaces else objetivos

    if args.solo_fallidos:
        seleccion = [o for o in seleccion
                     if (manifest.get(o["doc_id"]) or {}).get("estado") != "ok"]
    log.info("Documentos a procesar: %d", len(seleccion))
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

    n_desc = actualizar_descubiertos(cfg, objetivos, manifest)
    print(f"\nListos: {len(ok)} · Con error: {len(fallos)} · "
          f"Normas enlazadas aún fuera del corpus: {n_desc} (ver {cfg.ruta_descubiertos})")
    for doc_id, err in fallos:
        print(f"  ✗ {doc_id}: {err}")
    if fallos:                                   # el resumen de errores también va al .err
        print(f"{len(fallos)} documento(s) con error: " + ", ".join(d for d, _ in fallos),
              file=sys.stderr)
    huerfanos = sorted(set(manifest.docs) - {o["doc_id"] for o in objetivos})
    if huerfanos and not args.solo_enlaces:   # con --solo-enlaces el resto del corpus no se carga
        print("  ⚠ En el manifest pero ya no en las fuentes (bórrenlos de data/raw, data/md y del "
              "manifest si no los quieren): " + ", ".join(huerfanos))
    sin_texto = [r["doc_id"] for r in ok if r.get("advertencias")]
    if sin_texto:
        print("  ⚠ Sin texto legible: PDF escaneados: falta docling para el OCR (uv add docling). "
              "Instálenlo y corran con --solo-convertir --solo " + " ".join(sin_texto))
    sin_articulos = [r["doc_id"] for r in ok
                     if r["n_articulos_detectados"] == 0 and r.get("tipo_norma") != "sentencia"]
    if sin_articulos:
        print("  ⚠ Sin artículos detectados (revisen el Markdown o el tipo de fuente): "
              + ", ".join(sin_articulos))


if __name__ == "__main__":
    main()
