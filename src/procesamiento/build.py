"""Fase 3 completa: data/md/*.md -> data/processed/{chunks,articulos}.parquet.

    python -m src.procesamiento.build                 # todo el corpus
    python -m src.procesamiento.build --doc ley_1564_2012 --salida data/processed/parcial

Las filas de chunks.parquet quedan ordenadas por (doc_id, posicion): la fila i es el
id i del índice FAISS de la fase 5.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from src.procesamiento import encabezado, sentencias, validar, vigencia
from src.procesamiento.leer import Documento, leer, retirar_texto_obsoleto
from src.procesamiento.normas import segmentar, ruta_jerarquia
from src.procesamiento.partir import palabras, partir, vigente

log = logging.getLogger("procesamiento")


def _sha1(texto: str) -> str:
    return hashlib.sha1(texto.encode("utf-8")).hexdigest()


def _contador_tokens():
    """Tokenizer de bge-m3 si ya está en caché local; solo se usa para el reporte."""
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    try:
        from transformers import AutoTokenizer
        tok = AutoTokenizer.from_pretrained("BAAI/bge-m3", local_files_only=True)
        return lambda t: len(tok(t, add_special_tokens=False)["input_ids"])
    except Exception:          # sin caché o sin red: num_tokens queda vacío
        return None


def _fila(doc: Documento, *, chunk_id: str, articulo: str | None, cabecera: str,
          inicio: int, fin: int, jerarquia: str, seccion: str | None,
          parte: tuple[int, int], forzado: bool, contar) -> dict:
    meta = doc.meta
    completo = doc.texto[inicio:fin]
    cuerpo = vigente(completo)
    texto = f"{cabecera}\n{cuerpo}"
    vig = vigencia.analizar(completo)
    return {
        "chunk_id": chunk_id,
        "doc_id": doc.doc_id,
        "posicion": -1,
        "norma_id_canonico": encabezado.norma_id(meta, articulo),
        "tipo_norma": meta.get("tipo_norma"),
        "numero": str(meta["numero"]) if meta.get("numero") is not None else None,
        "anio": meta.get("anio"),
        "articulo": articulo,
        "titulo_norma": encabezado.nombre_norma(meta)[1],
        "jerarquia": jerarquia,
        "seccion": seccion,
        "organo_emisor": meta.get("organo_emisor"),
        "vigente": vig["vigente"],
        "vigencia_parcial": vig["vigencia_parcial"],
        "modificado_por": vig["modificado_por"],
        "notas": vig["notas"],
        "areas": list(meta.get("areas") or []),
        "texto": texto,
        "texto_completo": f"{cabecera}\n{completo}",
        "inicio": inicio,
        "fin": fin,
        "url": meta.get("url"),
        "fuente": doc.url_en(inicio),
        "formato": doc.formato,
        "parte_k": parte[0],
        "parte_n": parte[1],
        "corte_forzado": forzado,
        "num_palabras": palabras(texto),
        "num_palabras_cuerpo": palabras(cuerpo),
        "num_tokens": contar(texto) if contar else None,
        "sha1_texto": _sha1(texto),
        "sha1_cuerpo": _sha1(" ".join(cuerpo.lower().split())),
    }


def procesar_norma(doc: Documento, contar) -> tuple[list[dict], list[dict], dict]:
    seg = segmentar(doc.texto, pdf=doc.formato == "pdf")
    sigla = encabezado.nombre_norma(doc.meta)[2]
    chunks, articulos = [], []

    if seg.preambulo:
        cab = encabezado.encabezado_documento(doc.meta, "Encabezado y epígrafe")
        grupos = partir(doc.texto, seg.preambulo, palabras(cab))
        for k, g in enumerate(grupos, start=1):
            cab_k = encabezado.encabezado_documento(doc.meta, "Encabezado y epígrafe",
                                                    (k, len(grupos)))
            chunks.append(_fila(doc, chunk_id=f"{doc.doc_id}#preambulo#p{k}", articulo=None,
                                cabecera=cab_k, inicio=g.inicio, fin=g.fin, jerarquia="",
                                seccion="preambulo", parte=(k, len(grupos)),
                                forzado=g.forzado, contar=contar))

    for art in seg.articulos:
        jer_corta = ruta_jerarquia(art.jerarquia, con_nombres=False)
        jer_larga = " > ".join(filter(None, [sigla, ruta_jerarquia(art.jerarquia)]))
        cab = encabezado.encabezado_articulo(doc.meta, art.num, art.titulo, jer_corta)
        grupos = partir(doc.texto, art.bloques, palabras(cab))
        for k, g in enumerate(grupos, start=1):
            cab_k = encabezado.encabezado_articulo(doc.meta, art.num, art.titulo, jer_corta,
                                                   (k, len(grupos)))
            chunks.append(_fila(doc, chunk_id=f"{doc.doc_id}#art_{art.num}#p{k}",
                                articulo=art.num, cabecera=cab_k, inicio=g.inicio, fin=g.fin,
                                jerarquia=jer_larga, seccion=None, parte=(k, len(grupos)),
                                forzado=g.forzado, contar=contar))
        completo = doc.texto[art.inicio:art.fin]
        articulos.append({
            "doc_id": doc.doc_id,
            "articulo": art.num,
            "num_base": art.num_base,
            "sufijo": art.sufijo,
            "norma_id_canonico": encabezado.norma_id(doc.meta, art.num),
            "titulo_articulo": art.titulo,
            "jerarquia": jer_larga,
            "texto": f"{cab}\n{vigente(completo)}",
            "texto_completo": f"{cab}\n{completo}",
            "inicio": art.inicio,
            "fin": art.fin,
            "n_chunks": len(grupos),
            **{k: v for k, v in vigencia.analizar(completo).items() if k != "notas"},
        })

    reporte = validar.validar_articulos(doc.doc_id, seg.articulos)
    reporte["huerfanos"] = [b.texto[:120] for b in seg.huerfanos]
    reporte["rechazados"] = [b.texto[:120] for b in seg.rechazados]
    reporte["n_concordancias_descartadas"] = len(seg.concordancias)
    return chunks, articulos, reporte


def procesar_sentencia(doc: Documento, contar) -> tuple[list[dict], list[dict], dict]:
    meta = sentencias.metadatos(doc.texto)
    ponentes = ", ".join(meta["magistrado_ponente"])
    chunks = []
    for sec in sentencias.secciones(doc.texto):
        etiqueta = {"cuerpo": "Consideraciones y antecedentes", "resuelve": "Resuelve",
                    "salvamentos": "Salvamentos y aclaraciones de voto"}[sec.nombre]
        contexto = "Corte Constitucional" + (f", M.P. {ponentes}" if ponentes else "")
        cab = encabezado.encabezado_documento(doc.meta, f"{contexto}. {etiqueta}")
        grupos = partir(doc.texto, sec.bloques, palabras(cab))
        for k, g in enumerate(grupos, start=1):
            cab_k = encabezado.encabezado_documento(doc.meta, f"{contexto}. {etiqueta}",
                                                    (k, len(grupos)))
            chunks.append(_fila(doc, chunk_id=f"{doc.doc_id}#{sec.nombre}#p{k}", articulo=None,
                                cabecera=cab_k, inicio=g.inicio, fin=g.fin, jerarquia="",
                                seccion=sec.nombre, parte=(k, len(grupos)),
                                forzado=g.forzado, contar=contar))
    return chunks, [], {"secciones": {s.nombre: len(s.bloques)
                                      for s in sentencias.secciones(doc.texto)}, **meta}


def _escribir(filas: list[dict], ruta: Path) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(filas), ruta)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--md", type=Path, default=Path("data/md"))
    ap.add_argument("--salida", type=Path, default=Path("data/processed"))
    ap.add_argument("--doc", nargs="*", help="procesar solo estos doc_id")
    args = ap.parse_args()
    # Avance -> stdout (.out del job); solo los ERROR -> stderr (.err del job).
    salida_std = logging.StreamHandler(sys.stdout)
    salida_std.addFilter(lambda r: r.levelno < logging.ERROR)
    salida_err = logging.StreamHandler(sys.stderr)
    salida_err.setLevel(logging.ERROR)
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[salida_std, salida_err])

    # Los *.notas.md son contenido oculto del HTML, no documentos: no se segmentan.
    rutas = sorted(r for r in args.md.glob("*.md") if not r.name.endswith(".notas.md"))
    if args.doc:
        rutas = [r for r in rutas if r.stem in set(args.doc)]
    contar = _contador_tokens()
    todos_chunks, todos_arts, reporte = [], [], {"documentos": {}}
    escritos: set[str] = set()

    for ruta in rutas:
        doc = leer(ruta)
        (args.salida / "texto").mkdir(parents=True, exist_ok=True)
        (args.salida / "texto" / f"{doc.doc_id}.txt").write_text(doc.texto, encoding="utf-8")
        escritos.add(doc.doc_id)
        if doc.meta.get("tipo_norma") == "sentencia":
            chunks, arts, rep = procesar_sentencia(doc, contar)
        else:
            chunks, arts, rep = procesar_norma(doc, contar)
        for i, c in enumerate(chunks):
            c["posicion"] = i
        rep.update(validar.validar_chunks(chunks))
        reporte["documentos"][doc.doc_id] = rep
        todos_chunks += chunks
        todos_arts += arts
        log.info("%-28s %5d artículos  %6d chunks  %3d forzados  %3d sin fin de oración",
                 doc.doc_id, len(arts), len(chunks), len(rep["forzados"]),
                 len(rep["alerta_sin_fin_de_oracion"]))

    if not args.doc:                    # corrida completa: el directorio refleja SOLO los documentos actuales
        retirados = retirar_texto_obsoleto(args.salida / "texto", escritos)
        if retirados:
            log.info("texto/: retirados %d .txt de documentos que ya no están en data/md (p. ej. %s)",
                     len(retirados), ", ".join(retirados[:5]))

    todos_chunks.sort(key=lambda c: (c["doc_id"], c["posicion"]))
    reporte["total"] = validar.validar_chunks(todos_chunks)
    reporte["total"].pop("forzados")
    _escribir(todos_chunks, args.salida / "chunks.parquet")
    _escribir(todos_arts, args.salida / "articulos.parquet")
    (args.salida / "reporte_segmentacion.json").write_text(
        json.dumps(reporte, ensure_ascii=False, indent=2), encoding="utf-8")
    t = reporte["total"]
    log.info("TOTAL %d chunks | %d sobre el límite | %d duplicados exactos | %d con residuos",
             t["n_chunks"], len(t["sobre_limite"]), len(t["duplicados_exactos"]),
             len(t["alerta_residuos"]))


if __name__ == "__main__":
    main()
