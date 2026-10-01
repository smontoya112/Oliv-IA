"""Orquesta la fase 6: 6.2 alias → 6.4 híbrido → 6.3 área → 6.1 directos / 6.6 cerradas →
6.5 reranker. Interfaz que usa la fase 7/8:

    r = Recuperador()                      # carga índices, encoder y reranker (GPU)
    r.recuperar(item) -> {"pasajes": [...≤10], "senales": {...}}

CLI (lo que corre jobs/recuperar.sh):
    python -m src.recuperacion.pipeline --preguntas data/sample_50.jsonl \\
        --salida data/recuperacion/sample_50.jsonl [--sin-reranker --sin-directos --sin-alias
        --area ninguno]
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from collections import defaultdict
from pathlib import Path

from . import alias, cerradas, seleccion
from .catalogo import cargar
from .config import Config

log = logging.getLogger("recuperacion")


class Recuperador:
    def __init__(self, indice: Path = Path("data/index"), cfg: Config | None = None,
                 device: str | None = None):
        from .hibrido import Hibrido
        self.cfg = cfg or Config()
        self.indice = indice
        self.cat = cargar(indice)
        self.hibrido = Hibrido(self.cat, indice, device)
        self.reranker = None
        if self.cfg.reranker:
            from .reranker import Reranker
            self.reranker = Reranker(device=device, lote=self.cfg.lote_reranker,
                                     max_tokens=self.cfg.max_tokens_reranker)

    def _puntajes(self, cand: dict[int, dict]) -> dict[int, float]:
        if self.reranker is None:             # ablación: orden de la fusión, directos primero
            return {i: d["fusion"] + (seleccion.PREMIO_DIRECTO if d["via"] == "directo" else 0.0)
                    for i, d in cand.items()}
        por_consulta: dict[str, list[int]] = defaultdict(list)
        for i, d in cand.items():
            por_consulta[d["q"]].append(i)
        puntaje = {}
        for q, filas in por_consulta.items():
            for i, s in zip(filas, self.reranker.puntuar(q, [self.cat.cols["texto"][i]
                                                             for i in filas])):
                puntaje[i] = s
        return puntaje

    def recuperar(self, item: dict) -> dict:
        cfg = self.cfg
        consultas = [cerradas.consulta_base(item)] + [t for _, t in cerradas.consultas_por_opcion(item)]
        pares = [(alias.expandir(t) if cfg.alias else t, t) for t in consultas]
        rankings = self.hibrido.buscar_varias(pares, cfg)
        cand, info = seleccion.candidatos(item, self.cat, cfg, rankings)
        puntaje = self._puntajes(cand)
        final = seleccion.elegir(cand, puntaje, cfg)
        return {
            "pasajes": [self.cat.pasaje(i, puntaje[i], via=cand[i]["via"], opcion=cand[i]["opcion"])
                        for i in final],
            "senales": seleccion.senales(final, cand, puntaje, self.cat, info,
                                         self.reranker is not None),
        }

    def config_corrida(self) -> dict:
        """Todo lo necesario para reproducir la corrida (paso 12.2)."""
        ic = self.hibrido.cfg_indice
        return {"config": self.cfg.dict(), "sha256_chunks": ic["sha256_chunks"],
                "n_chunks": ic["n_chunks"], "encoder": ic["denso"]["modelo"],
                "encoder_revision": ic["denso"]["revision"],
                "reranker": getattr(self.reranker, "modelo", None),
                "reranker_commit": getattr(self.reranker, "commit", None)}


def _logs() -> None:
    """Avance -> stdout (.out del job); solo los ERROR -> stderr (.err del job)."""
    salida = logging.StreamHandler(sys.stdout)
    salida.addFilter(lambda r: r.levelno < logging.ERROR)
    errores = logging.StreamHandler(sys.stderr)
    errores.setLevel(logging.ERROR)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S",
                        handlers=[salida, errores])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--preguntas", type=Path, default=Path("data/sample_50.jsonl"))
    ap.add_argument("--salida", type=Path, required=True)
    ap.add_argument("--indice", type=Path, default=Path("data/index"))
    ap.add_argument("--sin-reranker", action="store_true")
    ap.add_argument("--sin-directos", action="store_true")
    ap.add_argument("--sin-alias", action="store_true")
    ap.add_argument("--area", choices=["filtro", "ninguno"], default="filtro")
    ap.add_argument("--min-en-area", type=int, default=Config.min_en_area)
    ap.add_argument("--limite", type=int, help="solo los primeros N ítems (pruebas)")
    args = ap.parse_args()
    _logs()

    cfg = Config(reranker=not args.sin_reranker, directos=not args.sin_directos,
                 alias=not args.sin_alias, area_modo=args.area, min_en_area=args.min_en_area)
    items = [json.loads(l) for l in args.preguntas.read_text(encoding="utf-8").splitlines() if l.strip()]
    if args.limite:
        items = items[: args.limite]
    rec = Recuperador(args.indice, cfg)
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    t0, errores = time.perf_counter(), 0
    with args.salida.open("w", encoding="utf-8") as f:
        for n, it in enumerate(items, start=1):
            t1 = time.perf_counter()
            try:
                r = rec.recuperar(it)
            except Exception as e:                  # un ítem roto no detiene la corrida
                log.error("ítem %s: %s: %s", it.get("id"), type(e).__name__, e)
                r, errores = {"pasajes": [], "senales": {"error": f"{type(e).__name__}: {e}"}}, errores + 1
            f.write(json.dumps({"id": it["id"], "formato": it["formato"], **r,
                                "latencia_ms": int((time.perf_counter() - t1) * 1000)},
                               ensure_ascii=False) + "\n")
            f.flush()
            if n % 25 == 0 or n == len(items):
                log.info("%d/%d ítems (%.2f s/ítem)", n, len(items), (time.perf_counter() - t0) / n)
    salida_cfg = args.salida.with_suffix(".config.json")
    salida_cfg.write_text(json.dumps(rec.config_corrida(), ensure_ascii=False, indent=2),
                          encoding="utf-8")
    log.info("recuperación de %d ítems (%d con error) en %.0f s -> %s", len(items), errores,
             time.perf_counter() - t0, args.salida)


if __name__ == "__main__":
    main()
