# Corpus base enriquecido con las normas que nombran las 992 preguntas (`data/index_base`, 3 oct)

Misma definición de corpus base de `../corpus_base/RESUMEN.md` (todo `data/md` salvo las rondas de proximidad `ronda_01..04`), pero con las normas que las 992 preguntas nombran y que
no estaban. Solo se usó el texto de los enunciados (ni `legal_basis` ni respuestas).

## Qué se hizo (en `~/hackatron/prueba_claude`, datos propios: copias de `data/md` y `data/raw`; el clon `Oliv-IA2/Oliv-IA` no se tocó)

| Paso | Comando / job | Resultado |
|---|---|---|
| Extracción de normas nombradas (otro clon, rama `corpus3.0`) | `jobs/enriquecer_corpus.sh data/test_992.jsonl` | 404 preguntas con mención normativa · 142 normas distintas · 99 ya en el corpus · 41 por descargar · 2 a mano → `data/enriquecimiento/test_992/{normas,fuentes,pendientes}.json` |
| Scraper con `fuentes.json` | `jobs/descargar_fuentes.sh` (job 756997) | 34 ok (todas sentencias de la Corte Constitucional) · 7 con 404 en el Senado |
| Scraper con `fuentes_alternativas.json` | `jobs/descargar_fuentes.sh data/enriquecimiento/test_992/fuentes_alternativas.json` (job 756998) | 4 ok desde gestores normativos públicos (CRA, Colpensiones): `ley_54_1990`, `ley_29_1982`, `ley_45_1990`, `decreto_2663_1950` |
| Chunking del corpus base | `CORPUS=base sbatch jobs/chunking.sh` (jobs 756999, 757010) | 62.824 chunks de 504 documentos (antes 57.346 y 467) |
| Índice del corpus base | `CORPUS=base sbatch jobs/indice.sh` (jobs 757004, 757011) | `data/index_base`: BM25 + FAISS (bge-m3), `n_chunks` 62.824, `sha256_chunks` `06438a86…` (`index_config.json`) |
| Recuperación de `sample_50` | `bash jobs/exp_claude.sh recuperar enriquecido data/index_base` (job 757006) | sin regresión (tabla de abajo) |
| Cobertura del enriquecimiento | `python -m src.analisis.cobertura_enriquecimiento` (jobs 757007, 757012) | la norma nueva aparece en el top-10 en 43 de 44 pares (norma, pregunta) |

Manifest: 3.523 documentos `ok` (3.485 antes). Documentos nuevos con chunks: 37 (`../corpus_enriquecido_docs.txt`, marca `nuevo`; `cambios.json`), 5.478 chunks nuevos. Ningún documento salió del corpus base.
Respaldo del índice anterior: `data/index_base_prev/` y `data/processed_base_prev/` (hypatia).

## Recuperación sobre `sample_50` (40 evaluables; mismo arnés que `../corpus_base/RESUMEN.md`)

| | cuerpo@10 | artículo@10 | hit_doc@10 | cobertura de opciones @8 |
|---|---|---|---|---|
| Corpus base anterior (57.346 chunks) | 0,9625 | 0,5982 | 0,90 | 0,9167 |
| **Corpus base enriquecido (62.824 chunks)** | 0,9625 | 0,5982 | 0,90 | **0,9375** |

Las 3 primeras métricas no cambian (la muestra no nombra las normas nuevas) y la cobertura de opciones sube 1 ítem: las normas añadidas no meten distractores que bajen lo que ya funcionaba.
Archivos: `recuperacion_base_anterior_eval.json`, `recuperacion_enriquecido_eval.json`, `eval_indice.json` (nivel de índice, sin reranker).

## Cobertura de lo descargado (`cobertura.json`)

De las 44 preguntas de `test_992` que nombran una norma descargada, la norma aparece en el top-10 de la recuperación en **43** (97,7 %), y 37 de las 38 normas descargadas son recuperadas por al menos una pregunta.

## Lo que sigue faltando (dicho con claridad)

* `sentencia_su-279_2019`: el scraper la bajó, pero la Corte la sirve como página dinámica (Angular) sin el texto (8.607 bytes con cualquier variante de URL); quedó con 0 chunks (1 pregunta). Pendiente a mano.
* `ley_2568_2021`, `decreto_3030_2022`, `decreto_4302_2008`: 404 en el Senado y sin copia pública encontrada (1 pregunta cada una).
* A mano desde el principio: Resolución 368 de 2014 (Ministerio de Ambiente; 23 preguntas, ids 721–752, de teoría del acto administrativo: el contenido de la resolución aporta poco) y Sentencia SL-3871 de 2021 (Corte Suprema; 1 pregunta).
* `pendientes.json` y `data/descubiertos.csv` listan lo demás.
* No se midió el efecto de las normas nuevas sobre las respuestas (no hay respuestas esperadas para `test_992`); solo que se recuperan y que no se pierde nada en `sample_50`.

## Reproducir

```bash
sbatch jobs/descargar_fuentes.sh data/enriquecimiento/test_992/fuentes.json        # REINDEXAR=0 para no encadenar chunking e índice
sbatch jobs/descargar_fuentes.sh data/enriquecimiento/test_992/fuentes_alternativas.json
CORPUS=base sbatch jobs/chunking.sh                                                  # -> data/processed_base/
CORPUS=base sbatch --dependency=afterok:<id del chunking> jobs/indice.sh             # -> data/index_base/
```
