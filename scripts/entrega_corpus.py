"""Material de entrega del corpus: corpus_manifest.json y CORPUS.md oficiales, y el comprimido corpus_<equipo>.zip.

Se corre donde estén los datos (hypatia: data/processed_base, data/index_base, data/md). El corpus entregado es el corpus base
(config/responder.json: `indice` data/index_base) con las normas que nombran las preguntas.

    python scripts/entrega_corpus.py manifiesto --equipo Oliv-IA --licencia CC-BY-4.0 --enlace <URL>
        -> corpus_manifest.json y CORPUS.md en la raíz del repo
    python scripts/entrega_corpus.py empaquetar --equipo Oliv-IA --licencia-archivo LICENSE
        -> entrega/corpus_<equipo>.zip  (LICENSE, corpus_manifest.json, corpus/<doc_id>.txt, indice/)
    python scripts/entrega_corpus.py instalar --zip corpus_Oliv-IA.zip
        -> deja el índice en data/index_base/ y los fragmentos y textos en data/processed_base/ (lo que lee config/responder.json)

Estructura del comprimido (la del enunciado, con el formato nativo del motor en indice/):

    LICENSE · corpus_manifest.json · CORPUS.md · LEEME.txt
    corpus/<doc_id>.txt          texto procesado de cada norma (el documento de referencia de los offsets inicio/fin)
    indice/faiss.index           FAISS IndexFlatIP, bge-m3, 1024 d
    indice/bm25/                 índice léxico (bm25s)
    indice/chunk_ids.json        orden de los fragmentos en ambos índices
    indice/index_config.json     versiones, hashes (sha256 de los fragmentos y del índice FAISS) y parámetros
    indice/chunks.parquet        fragmentos (la tabla que lee el motor; su sha256 está en index_config.json)
    indice/chunks.jsonl          la misma tabla en JSON Lines, con doc_id, offsets y metadatos
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
import zipfile
from pathlib import Path

AREAS = {
    "constitucional": "Derecho constitucional", "administrativo": "Derecho administrativo", "penal": "Derecho penal",
    "procesal": "Derecho procesal", "comercial": "Derecho comercial y sociedades", "civil": "Derecho civil",
    "familia": "Derecho de familia", "tributario": "Derecho tributario", "laboral": "Derecho laboral",
    "mercados": "Derecho de los mercados", "sin_clasificar": "Sin clasificar",
}
# Ítems del banco por área (enunciado, sección 4.2; son las cifras de la plantilla oficial de CORPUS.md).
BANCO = {"Derecho constitucional": 134, "Derecho administrativo": 124, "Derecho penal": 123, "Derecho procesal": 111,
         "Derecho comercial y sociedades": 104, "Derecho civil": 102, "Derecho de familia": 93, "Derecho tributario": 92,
         "Derecho laboral": 87, "Derecho de los mercados": 72}
ENCODER = "BAAI/bge-m3"


def sha256(ruta: Path) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def miles(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def mb(n: int) -> str:
    return f"{n / 1e6:,.1f}".replace(",", "_").replace(".", ",").replace("_", ".") + " MB"


def cargar(raiz: Path):
    import pandas as pd
    proc = raiz / "data" / "processed_base"
    chunks = pd.read_parquet(proc / "chunks.parquet", columns=["doc_id", "titulo_norma"])
    titulos = {d: t for d, t in chunks.dropna(subset=["titulo_norma"]).groupby("doc_id")["titulo_norma"].first().items() if str(t).strip()}
    arts = pd.read_parquet(proc / "articulos.parquet", columns=["doc_id"])
    manifest = {r["doc_id"]: r for r in json.loads((raiz / "data" / "corpus_manifest.json").read_text(encoding="utf-8"))
                if r.get("estado") == "ok"}
    n_frag, n_art = chunks["doc_id"].value_counts().to_dict(), arts["doc_id"].value_counts().to_dict()
    docs = []
    for doc_id in sorted(n_frag):
        m = manifest.get(doc_id, {})
        txt = proc / "texto" / f"{doc_id}.txt"
        formato = "/".join(m.get("formato_origen") or ["html"])
        seg = "segmentación por artículo" if n_art.get(doc_id) else "segmentación por secciones y párrafos (sentencia)"
        docs.append({
            "doc_id": doc_id, "titulo": titulos.get(doc_id) or m.get("titulo") or doc_id, "fuente": m.get("fuente"), "url": m.get("url"),
            "fecha_consulta": m.get("fecha_consulta"),
            "areas": [AREAS.get(a, a) for a in (m.get("areas") or [])],
            "n_articulos": int(n_art[doc_id]) if n_art.get(doc_id) else None, "n_fragmentos": int(n_frag[doc_id]),
            "metodo_ingesta": f"{'OCR de ' if m.get('ocr') else ''}{formato} a Markdown + {seg}",
            "sha256": sha256(txt) if txt.exists() else None, "origen": m.get("origen") or "lista objetivo",
            "_bytes": txt.stat().st_size if txt.exists() else 0,
        })
    return docs, manifest


def cmd_manifiesto(args) -> int:
    raiz = Path(args.raiz)
    docs, manifest = cargar(raiz)
    cfg = json.loads((raiz / "data" / "index_base" / "index_config.json").read_text(encoding="utf-8"))
    salida = {
        "equipo": args.equipo, "licencia": args.licencia, "fecha_generacion": args.fecha, "enlace_nube": args.enlace,
        "encoder": ENCODER, "dimension": cfg["denso"]["dim"], "indice": "FAISS IndexFlatIP (denso) + BM25 (bm25s)",
        "n_documentos": len(docs), "n_fragmentos": cfg["n_chunks"],
        "documentos": [{k: v for k, v in d.items() if not k.startswith("_")} for d in docs],
    }
    (raiz / "corpus_manifest.json").write_text(json.dumps(salida, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    (raiz / "CORPUS.md").write_text(bitacora(args, docs, manifest, cfg, raiz), encoding="utf-8", newline="\n")
    print(f"RESULTADO corpus_manifest.json y CORPUS.md: {len(docs)} documentos, {cfg['n_chunks']} fragmentos")
    return 0


def cobertura_por_area(raiz: Path) -> dict[str, tuple[int, float | None]]:
    """(ítems evaluables de la muestra, cuerpo@10 medio) por área, con la recuperación del índice entregado."""
    ruta = raiz / "experimentos" / "claude" / "corpus_enriquecido" / "recuperacion_enriquecido_eval.json"
    muestra = {}
    for linea in (raiz / "data" / "sample_50.jsonl").read_text(encoding="utf-8").splitlines():
        if linea.strip():
            it = json.loads(linea)
            muestra[it["id"]] = next((v for v in AREAS.values() if it["area"].startswith(v)), it["area"])
    res: dict[str, list[float]] = {}
    if ruta.exists():
        items = next(iter(json.loads(ruta.read_text(encoding="utf-8")).values()))["items"]
        for x in items:
            res.setdefault(muestra.get(x["id"], "?"), []).append(x["cuerpo@10"])
    return {a: (len(v), sum(v) / len(v)) for a, v in res.items()}


def bitacora(args, docs, manifest, cfg, raiz: Path) -> str:
    n_art = sum(d["n_articulos"] or 0 for d in docs)
    n_frag = sum(d["n_fragmentos"] for d in docs)
    tam_texto = sum(d["_bytes"] for d in docs)
    tam_indice = sum(f.stat().st_size for f in (raiz / "data" / "index_base").rglob("*") if f.is_file())
    por_origen: dict[str, int] = {}
    for d in docs:
        por_origen[d["origen"]] = por_origen.get(d["origen"], 0) + 1
    por_fuente: dict[str, int] = {}
    for d in docs:
        por_fuente[d["fuente"] or "?"] = por_fuente.get(d["fuente"] or "?", 0) + 1
    ocr = sum(1 for d in docs if "OCR" in d["metodo_ingesta"])
    pdf = sum(1 for d in docs if "pdf" in d["metodo_ingesta"])
    cobertura = cobertura_por_area(raiz)
    n_seed = len(json.loads((raiz / "data" / "seed_targets.json").read_text(encoding="utf-8"))["documentos"])
    n_error = sum(1 for r in json.loads((raiz / "data" / "corpus_manifest.json").read_text(encoding="utf-8")) if r.get("estado") != "ok")

    filas = []
    for d in docs:
        url = f"[enlace]({d['url']})" if d["url"] else "—"
        filas.append(f"| `{d['doc_id']}` | {d['titulo']} | {d['fuente'] or '—'} | {url} | {d['fecha_consulta'] or '—'} | "
                     f"{d['n_articulos'] if d['n_articulos'] else '—'} | {d['n_fragmentos']} | {', '.join(a.replace('Derecho ', '') for a in d['areas']) or '—'} |")
    areas_docs = {a: sum(1 for d in docs if a in d["areas"]) for a in BANCO}
    filas_area = []
    for a, items in BANCO.items():
        n, media = cobertura.get(a, (0, None))
        cob = (f"{media:.2f}".replace(".", ",") + f" de cuerpo@10 en {n} ítems evaluables de la muestra" if media is not None else "sin ítems evaluables en la muestra")
        filas_area.append(f"| {a} | {items} | {areas_docs[a]} | {cob} |")
    origen_txt = "; ".join(f"{k}: {v}" for k, v in sorted(por_origen.items(), key=lambda kv: -kv[1]))
    fuente_txt = "; ".join(f"{k}: {v}" for k, v in sorted(por_fuente.items(), key=lambda kv: -kv[1])[:6])
    return f"""# Bitácora del corpus — {args.equipo}

Corpus entregado: **{len(docs)} documentos y {miles(cfg['n_chunks'])} fragmentos** (índice `data/index_base`). Generado el {args.fecha} con `scripts/entrega_corpus.py`
a partir de `data/corpus_manifest.json` y de los archivos procesados; el inventario coincide con `corpus_manifest.json`.

---

## 1. Inventario

| doc_id | Título | Fuente | URL | Fecha de consulta | Artículos | Fragmentos | Áreas |
|---|---|---|---|---|---:|---:|---|
{chr(10).join(filas)}

**Totales**

| Métrica | Valor |
|---|---:|
| Documentos incorporados | {len(docs)} |
| Artículos indexados | {miles(n_art)} |
| Fragmentos en el índice | {miles(n_frag)} |
| Tamaño del corpus procesado | {mb(tam_texto)} |
| Tamaño del índice vectorial (directorio `data/index_base`, con BM25 y vectores) | {mb(tam_indice)} |

Documentos por origen en el manifiesto: {origen_txt}. «lista objetivo» son los documentos de la lista inicial (`data/seed_targets.json`, `data/fuentes_propias.json` y `data/enlaces.txt`), que no llevan `origen` en el manifiesto;
`preguntas_test_992` son las normas que nombran de forma explícita los enunciados de las 992 preguntas del test y que no estaban. Fuentes más frecuentes: {fuente_txt}.

## 2. Criterio de selección

La selección parte de la lista objetivo `data/seed_targets.json`: {n_seed} normas, cada una con el número de ítems del banco que la citan y sus áreas (la Constitución, por ejemplo, aparece en 90 ítems de nueve áreas), ordenadas por esa frecuencia.
Esa lista se contrastó con las normas que cita la muestra (`scripts/extraer_normas_muestra.py`: 24 de los 29 cuerpos normativos distintos de la muestra estaban cubiertos cuando se hizo el análisis, el 29 de septiembre) y después se añadieron las normas que nombran
los enunciados del test. La cobertura se midió con la recuperación sobre la muestra (`cobertura_cuerpo@10`: fracción de los cuerpos normativos de referencia que aparecen entre los 10 pasajes recuperados).

| Área | Ítems en el banco | Documentos incorporados | Cobertura estimada |
|---|---:|---:|---|
{chr(10).join(filas_area)}

Un documento puede contar en varias áreas. La muestra tiene entre 4 y 7 ítems por área, así que la cobertura por área es orientativa; en conjunto: cuerpo@10 0,9625 sobre 40 ítems evaluables.

**Documentos descartados.**

* **Rondas de proximidad (3.014 documentos, `ronda_01` a `ronda_04`, que incluyen la compilación jurídica de la DIAN):** se descargaron (el corpus ampliado llegó a 3.480 documentos y 220.903 fragmentos) y se excluyeron del corpus entregado.
  En la muestra eran distractores: con ellos la recuperación bajó de cuerpo@10 0,9625 a 0,8875 y de `hit_doc@10` 0,90 a 0,80, y la calidad de citación de 0,857 a 0,796. La pérdida de cobertura que implica (≈ 4 % del banco según la lista objetivo) no se pudo medir con la muestra.
* **Duplicados:** la misma norma descargada por varias URL se conserva una sola vez (`src/descarga/deduplicar.py`; de ~7.000 entradas quedaron ~3.600); las copias están en `data/descartados/`.
* **Sin texto, no incorporados:** `sentencia_su-279_2019` (la Corte la sirve como página dinámica sin el contenido), `ley_2568_2021`, `decreto_3030_2022` y `decreto_4302_2008` (404 en el Senado, sin copia pública encontrada),
  la Sentencia SL-3871 de 2021 (Corte Suprema) y la Resolución 368 de 2014 del Ministerio de Ambiente (a buscar a mano). Los {n_error} documentos del manifiesto con error de descarga tampoco están.

## 3. Método de ingesta y limpieza

1. **Descarga.** `src/descarga/run.py` sobre fuentes declaradas (`data/fuentes_seed.json`, `data/fuentes_propias.json`, `data/enriquecimiento/test_992/fuentes*.json`): cliente HTTP con respeto de `robots.txt`, límite de velocidad por host,
   reintentos con espera exponencial; guarda los bytes originales y su SHA-256 en `data/raw/<doc_id>/` y registra `fecha_consulta`, estado y errores en el manifiesto. Los documentos de la Secretaría del Senado se bajan por sus páginas; las sentencias, de la relatoría de la Corte Constitucional.
2. **Extracción de texto.** HTML con BeautifulSoup/lxml y markdownify a Markdown con front matter; PDF con PyMuPDF (OCR con docling solo si el PDF es escaneado). En este corpus: {pdf} documentos de origen PDF y {ocr} con OCR.
3. **Normalización.** Detección de codificación (`charset-normalizer`, p. ej. cp1252 en la DIAN) y corrección con `ftfy`; se conserva el texto normativo intacto (tildes, números, mayúsculas); el contenido oculto (notas de vigencia) va aparte en `*.notas.md`.
4. **Segmentación.** Normas: por artículo (`ARTÍCULO N.` abre un artículo; las variantes solo si N sigue la secuencia), con la jerarquía (Libro, Título, Capítulo). Sentencias: por secciones (cuerpo, resuelve, salvamentos) y párrafos.
   Los artículos largos se parten en fragmentos de ≤ 300 palabras por párrafo, oración y `;`/`:`, sin cortar oraciones; cada fragmento lleva un encabezado con la norma y el artículo escrito para que el parser de citas lo reconozca.
5. **Extracción de metadatos.** Por fragmento: `doc_id`, tipo de norma, número, año, artículo, órgano emisor, jerarquía, vigencia (apartes tachados = derogados o inexequibles, que no se indexan), áreas, URL, fuente y offsets `inicio`/`fin` en el texto procesado de `corpus/<doc_id>.txt`.
6. **Indexación.** `{ENCODER}` (revisión `5617a9f6`), vector denso de {cfg['denso']['dim']} dimensiones de [CLS] normalizado, `faiss.IndexFlatIP`, más BM25 (`bm25s`, k1 = 1,2, b = 0,75); textos idénticos se codifican una vez ({miles(cfg['n_textos_unicos'])} textos únicos de {miles(cfg['n_chunks'])} fragmentos).
   Los hashes quedan en `indice/index_config.json`.

Problemas encontrados y cómo se resolvieron:

* **Corpus ampliado con distractores:** ver la sección 2; se resolvió con el corpus base.
* **Citas en el texto de los fragmentos:** el evaluador solo da por respaldada una cita si su parser la encuentra en el pasaje; por eso cada fragmento se antepone con el nombre de la norma en la forma que reconoce el parser.
* **Falsos artículos:** una cita a otro artículo al inicio de un párrafo (p. ej. «Artículo 199.» dentro del artículo 612 del CGP) abría un artículo falso; ahora solo abre uno si el número sigue la secuencia.
* **Sitio nuevo de la Corte Constitucional:** es una aplicación dinámica que devuelve una página genérica ante rutas inexistentes; `scripts/verificar_sentencias_cconst.py` comprueba cuáles URL son reales, y `sentencia_su-279_2019` sigue sin texto.
* **Errores 404 del Senado:** para cuatro normas se buscó una copia en gestores normativos públicos con la misma estructura (`data/enriquecimiento/test_992/fuentes_alternativas.json`).
* **Estado del manifiesto:** una norma descargada con éxito pero vacía figura como `ok` (`sentencia_su-279_2019`: 101 caracteres, 0 fragmentos).

## 4. Evolución del puntaje

Puntaje sobre las 50 preguntas de muestra con el evaluador oficial (`scripts/evaluate.py`, sin RAGAS), medido con el mismo arnés en cada fila.

| Fecha | Documentos | Fragmentos | Cerradas /20 | Citación /20 | Abstención /10 | Total /50 | Qué cambió |
|---|---:|---:|---:|---:|---:|---:|---|
| 2 oct | 3.480 | 220.903 | 10,67 | 15,92 | 7,44 | 34,03 | Corpus ampliado completo (con rondas de proximidad) y la estrategia de generación anterior |
| 3 oct | 467 | 57.346 | 9,33 | 17,14 | 7,67 | 34,14 | Corpus base: se quitan las rondas de proximidad; misma generación |
| 3 oct | 467 | 57.346 | 14,67 | 17,14 | 8,60 | 40,41 | Nueva generación de las respuestas (letra por probabilidades, plantillas por sub-tarea) |
| 3 oct | 467 | 57.346 | 14,67 | 17,96 | 8,84 | 41,47 | Recuperación expandida en las abiertas |
| 3 oct | {len(docs)} | {miles(cfg['n_chunks'])} | — | — | — | no medido | + {por_origen.get('preguntas_test_992', 0)} normas de las 992 preguntas; recuperación de la muestra sin cambios |

Lectura de la curva: ampliar el corpus a 3.480 documentos subió el recall a nivel de artículo (artículo@10 de 0,605 a 0,71) pero bajó el de cuerpo normativo, que es lo que puntúa (cuerpo@10 de 0,925 a 0,8875); recortarlo a los documentos
objetivo recuperó cuerpo@10 0,9625 y la citación (+1,2 puntos), pero no ayudó a las cerradas (de 10,67 a 9,33, un ítem de diferencia): su mejora posterior (+5,3 puntos) viene de la forma de decidir la letra, no del corpus. La incorporación de las normas nombradas en el test no se puede medir con la muestra:
la recuperación de las 50 preguntas queda idéntica (cuerpo@10 0,9625) y de las 44 preguntas del test que nombran una de esas normas, 43 la traen entre los 10 pasajes recuperados.

## 5. Licencia

El corpus se publica bajo `{args.licencia}`. Los textos normativos colombianos son de dominio público; la licencia cubre el trabajo de procesamiento, segmentación y extracción de metadatos realizado por el equipo.
"""


def cmd_empaquetar(args) -> int:
    raiz = Path(args.raiz)
    docs, _ = cargar(raiz)
    proc, idx = raiz / "data" / "processed_base", raiz / "data" / "index_base"
    licencia = Path(args.licencia_archivo) if args.licencia_archivo else None
    if licencia is None or not licencia.exists():
        if not args.sin_licencia:
            print("ERROR: falta el archivo de licencia (--licencia-archivo LICENSE); el comprimido debe incluir LICENSE. "
                  "Con --sin-licencia se genera sin ella (solo para pruebas).", file=sys.stderr)
            return 2
    for f in (raiz / "corpus_manifest.json",):
        if not f.exists():
            print(f"ERROR: falta {f} (corra antes: manifiesto)", file=sys.stderr)
            return 2
    salida = Path(args.salida) / f"corpus_{args.equipo}.zip"
    salida.parent.mkdir(parents=True, exist_ok=True)
    import pandas as pd
    with zipfile.ZipFile(salida, "w", zipfile.ZIP_DEFLATED, compresslevel=args.nivel) as z:
        if licencia is not None and licencia.exists():
            z.write(licencia, "LICENSE")
        z.write(raiz / "corpus_manifest.json", "corpus_manifest.json")
        if (raiz / "CORPUS.md").exists():            # la bitácora viaja también dentro del comprimido
            z.write(raiz / "CORPUS.md", "CORPUS.md")
        z.writestr("LEEME.txt", LEEME.format(equipo=args.equipo))
        for d in docs:
            txt = proc / "texto" / f"{d['doc_id']}.txt"
            if txt.exists():
                z.write(txt, f"corpus/{d['doc_id']}.txt")
        for nombre in ("faiss.index", "chunk_ids.json", "index_config.json"):
            z.write(idx / nombre, f"indice/{nombre}")
        for f in sorted((idx / "bm25").rglob("*")):
            if f.is_file():
                z.write(f, f"indice/bm25/{f.relative_to(idx / 'bm25').as_posix()}")
        z.write(proc / "chunks.parquet", "indice/chunks.parquet")
        chunks = pd.read_parquet(proc / "chunks.parquet")
        with z.open("indice/chunks.jsonl", "w") as f:
            for fila in chunks.to_dict(orient="records"):
                fila = {k: (v.tolist() if hasattr(v, "tolist") else v) for k, v in fila.items()}
                f.write((json.dumps(fila, ensure_ascii=False, default=str) + "\n").encode("utf-8"))
    print(f"RESULTADO {salida} · {salida.stat().st_size / 1e6:.0f} MB · {len(docs)} documentos · sha256 {sha256(salida)}")
    return 0


LEEME = """Corpus e índice de {equipo} (Hackathon 2026, Universidad de los Andes).

Para usarlo con el código del repositorio:  python scripts/entrega_corpus.py instalar --zip <este archivo>
(deja indice/ en data/index_base/ y los fragmentos y textos en data/processed_base/, que es lo que lee config/responder.json).
Los hashes (sha256 de los fragmentos y del índice FAISS) están en indice/index_config.json.
"""


def cmd_instalar(args) -> int:
    destino = Path(args.destino)
    n = 0
    with zipfile.ZipFile(args.zip) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            nombre = info.filename
            if nombre.startswith("indice/chunks.parquet"):
                ruta = destino / "data" / "processed_base" / "chunks.parquet"
            elif nombre.startswith("indice/chunks.jsonl"):
                continue
            elif nombre.startswith("indice/"):
                ruta = destino / "data" / "index_base" / nombre[len("indice/"):]
            elif nombre.startswith("corpus/"):
                ruta = destino / "data" / "processed_base" / "texto" / nombre[len("corpus/"):]
            else:
                continue
            ruta.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as f, ruta.open("wb") as g:
                g.write(f.read())
            n += 1
    cfg = json.loads((destino / "data" / "index_base" / "index_config.json").read_text(encoding="utf-8"))
    ok = sha256(destino / "data" / "processed_base" / "chunks.parquet") == cfg["sha256_chunks"]
    ok_faiss = sha256(destino / "data" / "index_base" / "faiss.index") == cfg["denso"]["sha256_faiss"]
    print(f"RESULTADO {n} archivos instalados · sha256 de los fragmentos {'ok' if ok else 'NO COINCIDE'} · "
          f"sha256 de faiss.index {'ok' if ok_faiss else 'NO COINCIDE'}")
    return 0 if ok and ok_faiss else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for nombre in ("manifiesto", "empaquetar"):
        p = sub.add_parser(nombre)
        p.add_argument("--raiz", default=".")
        p.add_argument("--equipo", default="Oliv-IA")
    sub.choices["manifiesto"].add_argument("--licencia", default="<pendiente: licencia abierta>")
    sub.choices["manifiesto"].add_argument("--enlace", default="<pendiente: URL del comprimido con el corpus y el índice>")
    sub.choices["manifiesto"].add_argument("--fecha", default=dt.date.today().isoformat())
    sub.choices["empaquetar"].add_argument("--licencia-archivo", help="archivo LICENSE que se incluye en el comprimido")
    sub.choices["empaquetar"].add_argument("--sin-licencia", action="store_true")
    sub.choices["empaquetar"].add_argument("--salida", default="entrega")
    sub.choices["empaquetar"].add_argument("--nivel", type=int, default=3, help="nivel de compresión zip (1-9)")
    i = sub.add_parser("instalar")
    i.add_argument("--zip", required=True)
    i.add_argument("--destino", default=".")
    args = ap.parse_args()
    return {"manifiesto": cmd_manifiesto, "empaquetar": cmd_empaquetar, "instalar": cmd_instalar}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
