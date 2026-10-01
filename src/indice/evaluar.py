"""Paso 5.5: métricas de recuperación aisladas sobre data/sample_50.jsonl.

    python -m src.indice.evaluar                      # BM25, denso y RRF sobre data/index
    python -m src.indice.evaluar --solo lexico        # sin GPU ni modelo
    python -m src.indice.evaluar --indice data/index_prueba

La relevancia sale del parser oficial (scripts/citations.py), no de juicios manuales:
  * ranx a nivel artículo (recall@k, mrr@10, hit_rate@10): un chunk es relevante si su
    CABECERA (primera línea del texto, que identifica la norma y el artículo del chunk)
    contiene una cita a nivel de artículo del legal_basis.
  * ranx a nivel documento: el ranking se colapsa por doc_id y un documento es relevante si
    la cabecera de sus chunks nombra un cuerpo normativo del legal_basis. Cubre las
    sentencias y las citas sin artículo ("Código Civil").
  * cobertura@k: fracción de las citas del legal_basis que aparecen en el TEXTO de los k
    primeros pasajes. Es lo que usa evaluate.citas_respaldadas (k=10) para dar respaldo.
Los pasajes con el mismo sha1_texto se colapsan antes de cortar el top-k.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

import citations
from src.indice import denso, lexico
from src.indice.build import CONFIG, leer_chunks

log = logging.getLogger("indice")
CITAS = "citas_chunks.parquet"
RRF_K = 60
METRICAS = ["recall@10", "recall@50", "mrr@10", "hit_rate@10"]


# ------------------------------------------------------------------ citas
def _clave(c: tuple) -> str:
    return "|".join("" if x is None else str(x) for x in c)


def _tupla(s: str) -> tuple:
    return tuple(x or None for x in s.split("|"))


def _citas_chunk(texto: str) -> tuple[list[str], list[str]]:
    cabecera = texto.split("\n", 1)[0]
    return (sorted(map(_clave, citations.extract(cabecera))),
            sorted(map(_clave, citations.extract(texto))))


def citas_chunks(textos: list[str], cache: Path, firma: str) -> tuple[list[set], list[set]]:
    """citations.extract de la cabecera y del texto de cada chunk (con caché en parquet)."""
    if cache.exists():
        t = pq.read_table(cache)
        if t.schema.metadata and t.schema.metadata.get(b"firma") == firma.encode():
            d = t.to_pydict()
            return ([set(map(_tupla, x)) for x in d["cabecera"]],
                    [set(map(_tupla, x)) for x in d["texto"]])
    log.info("extrayendo citas de %d chunks (se guarda en %s)", len(textos), cache)
    with ProcessPoolExecutor() as ex:
        res = list(ex.map(_citas_chunk, textos, chunksize=500))
    tabla = pa.table({"cabecera": [r[0] for r in res], "texto": [r[1] for r in res]})
    pq.write_table(tabla.replace_schema_metadata({"firma": firma}), cache)
    return [set(map(_tupla, r[0])) for r in res], [set(map(_tupla, r[1])) for r in res]


# ------------------------------------------------------------------ muestras
def consulta(item: dict) -> str:
    texto = item.get("pregunta") or ""
    if item.get("formato") == "multiple_choice" and item.get("opciones"):
        texto += "\n" + "\n".join(f"{k}) {v}" for k, v in item["opciones"].items())
    return texto


def leer_muestras(ruta: Path) -> list[dict]:
    with open(ruta, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


# ------------------------------------------------------------------ runs
def colapsar(scores: np.ndarray, ids: np.ndarray, sha1: list[str], k: int,
             descartar_cero: bool) -> list[tuple[int, float]]:
    """Ranking de filas sin textos repetidos (se queda la primera aparición)."""
    vistos, salida = set(), []
    for s, i in zip(scores, ids):
        if i < 0 or (descartar_cero and s <= 0) or sha1[i] in vistos:
            continue
        vistos.add(sha1[i])
        salida.append((int(i), float(s)))
        if len(salida) == k:
            break
    return salida


def rrf(*rankings: list[tuple[int, float]], k: int) -> list[tuple[int, float]]:
    acum: dict[int, float] = defaultdict(float)
    for ranking in rankings:
        for pos, (i, _) in enumerate(ranking, start=1):
            acum[i] += 1.0 / (RRF_K + pos)
    return sorted(acum.items(), key=lambda x: -x[1])[:k]


# ------------------------------------------------------------------ métricas
def por_documento(ranking: list[tuple[int, float]], doc_id: list[str]) -> list[tuple[str, float]]:
    """Ranking de documentos: cada doc_id en la posición de su primer chunk."""
    vistos, salida = set(), []
    for i, s in ranking:
        if doc_id[i] not in vistos:
            vistos.add(doc_id[i])
            salida.append((doc_id[i], s))
    return salida


def ranx_por_consulta(qrels: dict, run: dict[str, list]) -> dict[str, dict[str, float]]:
    """Métricas de ranx por consulta: {qid: {métrica: valor}}, solo para qids con qrels.

    run: qid -> [(id, score), ...] ya ordenado. Se evalúa una sola vez por run (ranx compila
    con numba y cada llamada es cara); los subconjuntos se promedian después.
    """
    from ranx import Qrels, Run, evaluate
    qids = [q for q in run if qrels.get(q)]
    if not qids:
        return {}
    # ranx ordena por score: se usa el rango (no el score crudo) para que RRF y BM25 empaten igual.
    r = Run({q: ({str(i): float(len(run[q]) - p) for p, (i, _) in enumerate(run[q])}
                 or {"-1": 0.0}) for q in qids})
    evaluate(Qrels({q: qrels[q] for q in qids}), r, METRICAS)
    return {q: {m: float(r.scores[m][q]) for m in METRICAS} for q in qids}


def promedio_ranx(por_consulta: dict[str, dict[str, float]], qids: list[str]) -> dict | None:
    qids = [q for q in qids if q in por_consulta]
    if not qids:
        return None
    return {"n": len(qids), **{m: round(float(np.mean([por_consulta[q][m] for q in qids])), 4)
                               for m in METRICAS}}


def cobertura(ranking: list[tuple[int, float]], citas_texto: list[set], ref: set, k: int,
              nivel_articulo: bool) -> float | None:
    if not ref:
        return None
    respaldo = set().union(*(citas_texto[i] for i, _ in ranking[:k])) if ranking else set()
    if not nivel_articulo:
        respaldo = citations.bodies(respaldo)
    return len(ref & respaldo) / len(ref)


def _media(xs: list) -> float | None:
    xs = [x for x in xs if x is not None]
    return round(float(np.mean(xs)), 4) if xs else None


# ------------------------------------------------------------------ main
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--indice", type=Path, default=Path("data/index"))
    ap.add_argument("--muestras", type=Path, default=Path("data/sample_50.jsonl"))
    ap.add_argument("--k", type=int, nargs="+", default=[10, 50])
    ap.add_argument("--solo", choices=["lexico", "denso"])
    ap.add_argument("--salida", type=Path, help="por defecto <indice>/eval_recuperacion.json")
    args = ap.parse_args()
    salida_std = logging.StreamHandler(sys.stdout)
    salida_std.addFilter(lambda r: r.levelno < logging.ERROR)
    salida_err = logging.StreamHandler(sys.stderr)
    salida_err.setLevel(logging.ERROR)
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[salida_std, salida_err])

    cfg = json.loads((args.indice / CONFIG).read_text(encoding="utf-8"))
    chunks = leer_chunks(Path(cfg["chunks"]), cfg.get("limite"))
    sha1, chunk_ids = chunks["sha1_texto"], chunks["chunk_id"]
    denso.verificar_orden(args.indice, chunk_ids)
    k_max = max(args.k)
    k_busqueda = min(len(sha1), 3 * k_max)          # margen para el colapso de duplicados

    cit_cab, cit_txt = citas_chunks(chunks["texto"], args.indice / CITAS,
                                    f"{cfg['sha256_chunks']}:{cfg.get('limite')}")
    cuerpos_corpus = set().union(*(citations.bodies(c) for c in cit_cab))
    cuerpos_doc: dict[str, set] = defaultdict(set)
    for d, cs in zip(chunks["doc_id"], cit_cab):
        cuerpos_doc[d] |= citations.bodies(cs)
    por_articulo: dict[tuple, set[int]] = defaultdict(set)
    for i, cs in enumerate(cit_cab):
        for c in citations.article_level(cs):
            por_articulo[c].add(i)

    items = leer_muestras(args.muestras)
    consultas = [consulta(it) for it in items]
    qids = [str(it["id"]) for it in items]
    runs: dict[str, dict[str, list]] = {}
    hay_lexico = cfg.get("lexico") and args.solo != "denso"
    hay_denso = cfg.get("denso") and args.solo != "lexico"
    if hay_lexico:
        bm25 = lexico.cargar(args.indice)
        stemmer = lexico.crear_stemmer(bool(cfg["lexico"].get("stemmer")))
        sc, ids = lexico.buscar(bm25, consultas, k_busqueda, stemmer)
        runs["bm25"] = {q: colapsar(sc[j], ids[j], sha1, k_max, True) for j, q in enumerate(qids)}
    if hay_denso:
        from src.indice.encoder import Encoder
        enc = Encoder(modelo=cfg["denso"]["modelo"], revision=cfg["denso"]["revision"])
        sc, ids = denso.buscar(denso.cargar(args.indice), enc.consultas(consultas), k_busqueda)
        runs["denso"] = {q: colapsar(sc[j], ids[j], sha1, k_max, False) for j, q in enumerate(qids)}
    if "bm25" in runs and "denso" in runs:
        runs["rrf"] = {q: rrf(runs["bm25"][q], runs["denso"][q], k=k_max) for q in qids}
    if not runs:
        log.error("no hay índices para evaluar en %s (¿falta correr src.indice.build?)", args.indice)
        sys.exit(1)

    # Grupos de ítems y qrels (ranx usa la fila representativa de cada texto como doc id).
    representante = {}
    for i, h in enumerate(sha1):
        representante.setdefault(h, i)
    qrels, qrels_doc, detalle, grupos = {}, {}, [], defaultdict(list)
    for it, qid in zip(items, qids):
        ref = citations.extract(it.get("legal_basis") or "")
        ref_cuerpos = citations.bodies(ref) & cuerpos_corpus
        ref_art = {c for c in citations.article_level(ref) if (c[0], c[1], c[2]) in ref_cuerpos}
        if not ref:
            grupo = "sin_citas"
        elif not ref_cuerpos:
            grupo = "fuera_del_corpus"
        else:
            grupo = "evaluable"
        grupos[grupo].append(qid)
        relevantes = {representante[sha1[i]] for c in ref_art for i in por_articulo.get(c, ())}
        if grupo == "evaluable" and relevantes:
            qrels[qid] = {str(i): 1 for i in relevantes}
        docs_rel = {d for d, cs in cuerpos_doc.items() if cs & ref_cuerpos}
        if grupo == "evaluable":
            qrels_doc[qid] = {d: 1 for d in docs_rel}
        fila = {"id": it["id"], "formato": it.get("formato"), "area": it.get("area"),
                "grupo": grupo, "legal_basis": it.get("legal_basis"),
                "ref": sorted(map(_clave, ref)), "ref_en_corpus": sorted(map(_clave, ref_cuerpos)),
                "n_chunks_relevantes": len(relevantes), "docs_relevantes": sorted(docs_rel),
                "runs": {}}
        for nombre, run in runs.items():
            rk = run[qid]
            primero = next((p for p, (i, _) in enumerate(rk, start=1) if i in relevantes), None)
            docs = [d for d, _ in por_documento(rk, chunks["doc_id"])]
            fila["runs"][nombre] = {
                "rank_primer_relevante": primero,
                "rank_primer_doc_relevante": next((p for p, d in enumerate(docs, start=1)
                                                   if d in docs_rel), None),
                **{f"cobertura_cuerpo@{k}": cobertura(rk, cit_txt, ref_cuerpos, k, False)
                   for k in args.k},
                **{f"cobertura_articulo@{k}": cobertura(rk, cit_txt, ref_art, k, True)
                   for k in args.k},
                "top10": [chunk_ids[i] for i, _ in rk[:10]],
            }
        detalle.append(fila)

    # Agregados: total, por formato y por área.
    subconjuntos = {"todos": qids}
    for campo in ("formato", "area"):
        for it, qid in zip(items, qids):
            subconjuntos.setdefault(f"{campo}={it.get(campo)}", []).append(qid)
    filas_por_qid = {str(f["id"]): f for f in detalle}
    resultados = {}
    for nombre, run in runs.items():
        resultados[nombre] = {}
        m_art = ranx_por_consulta(qrels, run)
        m_doc = ranx_por_consulta(qrels_doc, {q: por_documento(run[q], chunks["doc_id"])
                                              for q in qids})
        for q, f in filas_por_qid.items():
            f["runs"][nombre]["ranx"] = m_art.get(q)
            f["runs"][nombre]["ranx_documento"] = m_doc.get(q)
        for sub, ids_sub in subconjuntos.items():
            ev = [q for q in ids_sub if filas_por_qid[q]["grupo"] == "evaluable"]
            res = {"ranx": promedio_ranx(m_art, ev), "ranx_documento": promedio_ranx(m_doc, ev)}
            for k in args.k:
                for nivel in ("cuerpo", "articulo"):
                    clave = f"cobertura_{nivel}@{k}"
                    res[clave] = _media([filas_por_qid[q]["runs"][nombre][clave] for q in ev])
            resultados[nombre][sub] = res

    log.info("ítems: %d | evaluables %d | fuera del corpus %d | sin citas extraíbles %d | "
             "con chunk relevante a nivel artículo %d", len(items), len(grupos["evaluable"]),
             len(grupos["fuera_del_corpus"]), len(grupos["sin_citas"]), len(qrels))
    for nombre in runs:
        r = resultados[nombre]["todos"]
        m, md = r["ranx"] or {}, r["ranx_documento"] or {}
        log.info("RESULTADO %-6s artículo (n=%s): Recall@10 %s  Recall@50 %s  MRR@10 %s  Hit@10 %s",
                 nombre, m.get("n"), m.get("recall@10"), m.get("recall@50"), m.get("mrr@10"),
                 m.get("hit_rate@10"))
        log.info("RESULTADO %-6s documento (n=%s): Recall@10 %s  Recall@50 %s  MRR@10 %s  Hit@10 %s",
                 nombre, md.get("n"), md.get("recall@10"), md.get("recall@50"), md.get("mrr@10"),
                 md.get("hit_rate@10"))
        log.info("RESULTADO %-6s cobertura de citas en el texto: cuerpo@10 %s  artículo@10 %s  "
                 "cuerpo@50 %s", nombre, r.get("cobertura_cuerpo@10"),
                 r.get("cobertura_articulo@10"), r.get("cobertura_cuerpo@50"))

    salida = args.salida or args.indice / "eval_recuperacion.json"
    salida.write_text(json.dumps({
        "indice": str(args.indice).replace("\\", "/"), "muestras": str(args.muestras).replace("\\", "/"),
        "sha256_chunks": cfg["sha256_chunks"], "n_chunks": cfg["n_chunks"], "k": args.k,
        "grupos": {g: len(v) for g, v in grupos.items()},
        "fuera_del_corpus": sorted({c for f in detalle for c in f["ref"]
                                    if _tupla(c)[:3] not in cuerpos_corpus}),
        "resultados": resultados, "items": detalle,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("detalle por ítem en %s", salida)


if __name__ == "__main__":
    main()
