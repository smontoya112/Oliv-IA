"""Corrida ciega por partes: divide las preguntas, responde una parte y une las entregas.

Mañana se reparten las 992 preguntas en 3 partes que corren en paralelo en máquinas distintas
(dos en hypatia y una en un computador con GPU). Cada parte usa EXACTAMENTE el camino de
src.responder (preparar_item -> Recuperador.recuperar -> responder_item), así lo que se
regenera en vivo con `python -m src.responder --id N` coincide con lo entregado.

    python -m src.lote dividir --preguntas data/test_992.jsonl          # -> data/lote/parte_{1,2,3}.jsonl
    python -m src.lote correr --parte 2                                 # -> data/lote/sub_2.jsonl (reanudable)
    python -m src.lote unir --salida submissions.jsonl                  # junta sub_*.jsonl y valida

La división es determinista (misma entrada -> mismas partes en cualquier máquina) y queda
registrada en data/lote/division.json con el sha256 de la entrada.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import platform
import sys
import time
from collections import Counter
from pathlib import Path

from src.generacion import abiertas
from src.responder import FORMATOS, cargar_config, preparar_item, recuperar_item, responder_item

log = logging.getLogger("lote")
DIR = Path("data/lote")
PREGUNTAS = Path("data/test_992.jsonl")
CADA = 10                       # cada cuántos ítems se imprime el avance


# ------------------------------------------------------------------ utilidades
def _jsonl(ruta: Path) -> list[dict]:
    return [json.loads(l) for l in ruta.read_text(encoding="utf-8").splitlines() if l.strip()]


def _escribir(ruta: Path, lineas: list[dict]) -> None:
    """Escritura atómica (temporal + rename): una parte nunca queda a medias."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_suffix(ruta.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for l in lineas:
            f.write(json.dumps(l, ensure_ascii=False) + "\n")
    os.replace(tmp, ruta)


def sha256(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def _logs() -> None:
    """Avance -> stdout (.out del job); solo los ERROR -> stderr (.err del job)."""
    salida = logging.StreamHandler(sys.stdout)
    salida.addFilter(lambda r: r.levelno < logging.ERROR)
    errores = logging.StreamHandler(sys.stderr)
    errores.setLevel(logging.ERROR)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S",
                        handlers=[salida, errores])


# ------------------------------------------------------------------ dividir
def revisar(items: list[dict], palabras_caso_largo: int = 120) -> list[str]:
    """Problemas de estructura de la entrada (no detienen la corrida: un ítem malo se abstiene)."""
    problemas, vistos = [], set()
    for k, it in enumerate(items, start=1):
        ident = it.get("id")
        if not isinstance(ident, int) or isinstance(ident, bool):
            problemas.append(f"línea {k}: 'id' ausente o no entero")
            continue
        if ident in vistos:
            problemas.append(f"id {ident}: duplicado")
        vistos.add(ident)
        if it.get("formato") not in FORMATOS:
            problemas.append(f"id {ident}: formato {it.get('formato')!r} (se deduce del texto)")
        try:
            preparar_item(it, palabras_caso_largo=palabras_caso_largo)
        except ValueError as e:
            problemas.append(f"id {ident}: {e}")
    return problemas


def dividir(items: list[dict], partes: int) -> list[list[dict]]:
    """Reparto estratificado por formato: se ordena por (formato, id) y se reparte en ronda.
    Así cada parte lleva la misma mezcla de cerradas, semiabiertas y abiertas (las abiertas
    tardan ~3 veces más) y termina en un tiempo parecido."""
    orden = {f: k for k, f in enumerate(FORMATOS)}
    validos = [it for it in items if isinstance(it.get("id"), int)]
    validos.sort(key=lambda it: (orden.get(it.get("formato"), len(FORMATOS)), it["id"]))
    res = [[] for _ in range(partes)]
    for k, it in enumerate(validos):
        res[k % partes].append(it)
    return [sorted(p, key=lambda it: it["id"]) for p in res]


def cmd_dividir(args) -> int:
    items = _jsonl(args.preguntas)
    huella = sha256(args.preguntas)
    reg = args.dir / "division.json"
    if reg.exists() and not args.forzar:
        prev = json.loads(reg.read_text(encoding="utf-8"))
        if prev["sha256"] == huella and prev["partes"] == args.partes \
                and all((args.dir / f"parte_{n}.jsonl").exists() for n in range(1, args.partes + 1)):
            log.info("ya dividida (%s, sha256 %s…): no se toca", prev["preguntas"], huella[:12])
            return 0
        log.error("data/lote ya tiene otra división (sha256 %s…, %d partes) y la entrada es "
                  "%s… con %d partes: usen --forzar si de verdad cambió el archivo",
                  prev["sha256"][:12], prev["partes"], huella[:12], args.partes)
        return 2
    cfg = cargar_config()
    problemas = revisar(items, cfg["palabras_caso_largo"])
    for p in problemas:
        log.error("entrada: %s", p)
    log.info("%d preguntas en %s (sha256 %s…) · %s", len(items), args.preguntas, huella[:12],
             dict(Counter(it.get("formato") for it in items)))
    trozos = dividir(items, args.partes)
    for n, trozo in enumerate(trozos, start=1):
        _escribir(args.dir / f"parte_{n}.jsonl", trozo)
        log.info("RESULTADO parte %d: %d preguntas %s", n, len(trozo),
                 dict(Counter(it.get("formato") for it in trozo)))
    reg.write_text(json.dumps({
        "preguntas": str(args.preguntas), "sha256": huella, "partes": args.partes,
        "n": len(items), "ids": {str(n): [it["id"] for it in t] for n, t in enumerate(trozos, 1)},
    }, ensure_ascii=False), encoding="utf-8")
    return 0


# ------------------------------------------------------------------ correr
def hechos(ruta: Path) -> dict[int, dict]:
    """Líneas ya escritas (checkpoint). Si el proceso murió escribiendo, la última línea queda
    cortada: se descarta y el archivo se reescribe limpio para poder seguir agregando."""
    if not ruta.exists():
        return {}
    res, rotas = {}, 0
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        if not linea.strip():
            continue
        try:
            l = json.loads(linea)
            res[l["id"]] = l
        except (json.JSONDecodeError, KeyError, TypeError):
            rotas += 1
    if rotas:
        log.warning("%s: %d líneas cortadas descartadas (se regeneran)", ruta, rotas)
        _escribir(ruta, list(res.values()))
    return res


def _abstencion(item: dict, pasajes: list[dict], senales: dict | None, catalogo) -> dict:
    """Línea válida de abstención para un ítem que falló (mejor que dejarlo sin respuesta)."""
    from src.generacion.postproceso import ensamblar
    it = dict(item)
    if it.get("formato") not in FORMATOS:
        it["formato"] = "semi_open"
    return ensamblar(it, None, pasajes, 0, senales, catalogo)


def correr(items: list[dict], recuperador, motor, salida: Path, recuperacion: Path | None = None,
           palabras_caso_largo: int = 120, estrategia: str | None = None,
           cfg: dict | None = None) -> dict:
    """Responde `items` uno a uno con checkpoint en `salida` (append + flush por ítem)."""
    catalogo = getattr(recuperador, "cat", None)
    ya = hechos(salida)
    pendientes = [it for it in items if it.get("id") not in ya]
    log.info("%d preguntas: %d ya hechas, %d pendientes", len(items), len(ya), len(pendientes))
    salida.parent.mkdir(parents=True, exist_ok=True)
    fallidos, t0 = [], time.perf_counter()
    with salida.open("a", encoding="utf-8") as f, \
            (recuperacion.open("a", encoding="utf-8") if recuperacion else open(os.devnull, "w")) as fr:
        for k, crudo in enumerate(pendientes, start=1):
            rec = {"pasajes": [], "senales": None}
            try:
                item = preparar_item(crudo, palabras_caso_largo=palabras_caso_largo)
                rec = recuperar_item(item, recuperador, motor, cfg or {"estrategia": estrategia})
                sub = responder_item(item, rec, motor, catalogo, estrategia, abiertas.activas(cfg))
            except Exception as e:                       # un ítem roto no detiene la parte
                log.error("id %s: %s: %s", crudo.get("id"), type(e).__name__, e)
                fallidos.append(crudo.get("id"))
                sub = _abstencion(crudo, rec.get("pasajes") or [], rec.get("senales"), catalogo)
            f.write(json.dumps(sub, ensure_ascii=False) + "\n")
            f.flush()
            fr.write(json.dumps({"id": sub["id"], **rec}, ensure_ascii=False) + "\n")
            fr.flush()
            if k % CADA == 0 or k == len(pendientes):
                seg = time.perf_counter() - t0
                eta = seg / k * (len(pendientes) - k)
                log.info("avance %d/%d (total %d/%d) · %.1f s/pregunta · faltan ~%.0f min",
                         k, len(pendientes), len(ya) + k, len(items), seg / k, eta / 60)
    seg = time.perf_counter() - t0
    return {"n": len(items), "nuevas": len(pendientes), "fallidos": fallidos,
            "segundos": round(seg, 1),
            "s_por_pregunta": round(seg / len(pendientes), 2) if pendientes else None}


def cmd_correr(args) -> int:
    parte = args.dir / f"parte_{args.parte}.jsonl"
    if not parte.exists():
        log.error("no existe %s: corran antes `python -m src.lote dividir`", parte)
        return 2
    items = _jsonl(parte)
    if args.limite:
        items = items[: args.limite]
    cfg = cargar_config()
    if args.modelo:
        cfg["modelo"] = args.modelo
    t0 = time.perf_counter()
    from src.generacion.motor import Motor
    from src.recuperacion.pipeline import Recuperador
    recuperador = Recuperador(Path(cfg["indice"]))
    motor = Motor(cfg["modelo"], n_ctx=cfg["n_ctx"])
    log.info("modelos cargados en %.0f s (decoder %s)", time.perf_counter() - t0, cfg["modelo"])
    (args.dir / f"config_{args.parte}.json").write_text(json.dumps({
        "parte": args.parte, "host": platform.node(), "modelo": cfg["modelo"],
        "n_ctx": cfg["n_ctx"], "estrategia": cfg.get("estrategia"), "abiertas": sorted(abiertas.activas(cfg)),
        "recuperacion": recuperador.config_corrida(),
        "inicio": time.strftime("%F %T"),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    r = correr(items, recuperador, motor, args.dir / f"sub_{args.parte}.jsonl",
               args.dir / f"recuperacion_{args.parte}.jsonl", cfg["palabras_caso_largo"],
               cfg.get("estrategia"), cfg)
    subs = hechos(args.dir / f"sub_{args.parte}.jsonl")
    faltan = sorted({it["id"] for it in items} - set(subs))
    log.info("RESULTADO parte %d: %d/%d respondidas · %d abstenciones · %d fallidas · "
             "%s s/pregunta · %.1f min", args.parte, len(subs), len(items),
             sum(1 for s in subs.values() if s.get("abstencion")), len(r["fallidos"]),
             r["s_por_pregunta"], r["segundos"] / 60)
    if r["fallidos"]:
        log.error("ids que fallaron (quedaron como abstención): %s", r["fallidos"])
    if faltan:
        log.error("faltan %d ids: %s", len(faltan), faltan[:50])
        return 1
    return 0


# ------------------------------------------------------------------ unir
def unir(items: list[dict], subs_por_archivo: dict[str, list[dict]]) -> tuple[list[dict], list[str]]:
    """(líneas ordenadas por id, avisos). Un id repetido entre archivos conserva la primera
    aparición; ids que no están en la entrada se descartan."""
    esperados = {it["id"] for it in items}
    lineas, avisos = {}, []
    for nombre, subs in subs_por_archivo.items():
        for s in subs:
            ident = s.get("id")
            if ident not in esperados:
                avisos.append(f"{nombre}: id {ident} no está en las preguntas (se descarta)")
            elif ident in lineas:
                avisos.append(f"{nombre}: id {ident} repetido (se conserva la primera)")
            else:
                lineas[ident] = s
    return [lineas[i] for i in sorted(lineas)], avisos


def cmd_unir(args) -> int:
    from src.verificacion.esquema import validar
    items = _jsonl(args.preguntas)
    rutas = args.subs or sorted(args.dir.glob("sub_*.jsonl"))
    if not rutas:
        log.error("no hay archivos sub_*.jsonl en %s", args.dir)
        return 2
    subs = {str(r): list(hechos(Path(r)).values()) for r in rutas}
    for r, s in subs.items():
        log.info("%s: %d líneas", r, len(s))
    lineas, avisos = unir(items, subs)
    for a in avisos:
        log.warning(a)
    esperados = {it["id"] for it in items}
    faltan = sorted(esperados - {l["id"] for l in lineas})
    reg = args.dir / "division.json"
    if faltan and reg.exists():
        ids = json.loads(reg.read_text(encoding="utf-8"))["ids"]
        for n, del_n in ids.items():
            f = sorted(set(del_n) & set(faltan))
            if f:
                log.error("parte %s: faltan %d ids (relanzar esa parte): %s", n, len(f), f[:30])
    problemas = validar(lineas, esperados)
    for p in problemas[:30]:
        log.error("validación: %s", p)
    _escribir(args.salida, lineas)
    log.info("RESULTADO %s: %d/%d líneas · %d abstenciones · %d problemas de validación · %s",
             args.salida, len(lineas), len(esperados), sum(1 for l in lineas if l.get("abstencion")),
             len(problemas), dict(Counter(l["formato"] for l in lineas)))
    return 1 if faltan or problemas else 0


# ------------------------------------------------------------------ CLI
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dividir", help="parte la entrada en N archivos")
    d.add_argument("--preguntas", type=Path, default=PREGUNTAS)
    d.add_argument("--partes", type=int, default=3)
    d.add_argument("--dir", type=Path, default=DIR)
    d.add_argument("--forzar", action="store_true", help="rehacer aunque ya exista otra división")
    c = sub.add_parser("correr", help="responde una parte (con checkpoint)")
    c.add_argument("--parte", type=int, required=True)
    c.add_argument("--dir", type=Path, default=DIR)
    c.add_argument("--modelo", help="alias del decoder (por defecto config/responder.json)")
    c.add_argument("--limite", type=int, help="solo los primeros N ítems (pruebas)")
    u = sub.add_parser("unir", help="junta las partes en un solo submissions.jsonl y valida")
    u.add_argument("--preguntas", type=Path, default=PREGUNTAS)
    u.add_argument("--dir", type=Path, default=DIR)
    u.add_argument("--subs", type=Path, nargs="+", help="archivos a unir (por defecto <dir>/sub_*.jsonl)")
    u.add_argument("--salida", type=Path, default=Path("submissions.jsonl"))
    args = ap.parse_args()
    _logs()
    return {"dividir": cmd_dividir, "correr": cmd_correr, "unir": cmd_unir}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
