# Handover 2 — Oliv-IA · Hackathon 2026 (Uniandes, AI Week)

Segundo traspaso, para continuar en otro chat. Complementa el primer handover (contexto del reto,
reglas, puntaje) y cubre todo lo hecho después: corpus ampliado y deduplicado, fases 6, 7 y 11,
entorno de `hypatia` y decisiones abiertas. Escrito el **viernes 2 de octubre de 2026**.
Responde al equipo **en español**. Ningún modelo cerrado puede formar parte del sistema.

---

## 1. Reto y plazos (recordatorio)

- RAG jurídico colombiano con decoder abierto ≤ 8.000 M de parámetros; temperatura 0; índice **congelado** al entregar.
- Puntaje: cerradas 20 · texto libre (RAGAS, juez `z-ai/glm-5.3-flash`) 30 · citación 20 · abstención 10 · interfaz/corpus/ingeniería 20.
  `citations.score` compara por **cuerpo normativo** (sin artículo); solo cuentan los 10 primeros `pasajes_recuperados`.
- **Viernes 2 oct:** congelar el índice esta noche; reporte de avance (PDF de 1 página a `rf.manrique@uniandes.edu.co`; el
  handover dice 17:00 y `checklist.md` dice antes de las 13:00 → confirmar).
- **Sábado 3 oct:** 9:00 llegan las 992 preguntas; entrega antes de las 15:00; verificación en vivo 15:00–17:00
  (el jurado regenera 2–3 preguntas con `python -m src.responder --id N`; deben coincidir normas citadas y pasajes).
- Presupuesto ≈ 22 s por pregunta.

## 2. Estado por fase (`checklist.md` es la fuente; aquí el resumen)

| Fase | Estado |
|---|---|
| 0–3 Preparación, fuentes, descarga, limpieza y segmentación | Hechas (Samuel + compañera). Chunking en `src/procesamiento/`. |
| 4 Normalización de citas | Hecha por el equipo: `scripts/normalizacion.py`, `data/alias_normas.yaml`. |
| 5 Indexación | Hecha y ejecutada en `hypatia` (`src/indice/`, `jobs/indice.sh`). Reindexada con el corpus ampliado. |
| 6 Recuperación | **Código mío, ejecutado y medido** (`src/recuperacion/`). Ver §6. |
| 7 Generación | **Código mío listo** (`src/generacion/`, motor llama.cpp). Una compañera corre la fase 7 completa en la rama `generacion`. El benchmark con contexto real está **pendiente**. |
| 8 Verificación de citas y abstención | **Pendiente.** Rama `verificacion` (compañera). Hoy `responder.verificar()` es un gancho vacío. |
| 9 Iteración sobre muestras | Pendiente (no hay conjunto de desarrollo más grande que `sample_50`). |
| 10 Tiempo y robustez | Pendiente (checkpointing, determinismo lote vs individual). |
| 11 Interfaz y verificación en vivo | **Código mío listo** (`src/responder.py`, `src/api.py`, interfaz). Entorno validado; `servir.sh` y `--id` end-to-end **sin confirmar**. |
| 12 Reproducibilidad (Docker, versiones, publicar corpus) | Pendiente. |
| 13 Hitos del viernes y congelación | Pendiente: reporte, tag de git, hash del índice. |
| 14–15 Sábado y entregables (informe, video) | Pendiente. |

## 3. Ramas y repositorio

- Repo: `github.com/smontoya112/Oliv-IA`. **Rama de trabajo actual: `interfazV2`** (parte de `recuperacion` + `origin/main`;
  último commit `373d8e6`, subido). Pendiente: PR de `interfazV2` hacia `main`.
- Otras ramas: `main`, `corpus`, `corpus_mejorado` (datos viejos, no es el corpus nuevo), `limpieza`, `normalizacion`, `indexation`,
  `recuperacion`, `interfaz`, `generacion` y `verificacion` (de las compañeras).
- En `hypatia` el repo está en `~/hackatron/Oliv-IA2/Oliv-IA` (clon con `interfazV2`).
- Los commits llevan `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- `git push` desde el portátil falla a ratos por la red: reintentar (hay que usar un bucle de 3 intentos).
- **No hay** `uv.lock` actualizado para `docling`, `olefile`, `pyarrow`, `fastapi`, `uvicorn` (se regenera al hacer `uv run` con red).

## 4. Entorno

**hypatia (Slurm, sin tmux):** nodos GPU = **Quadro RTX 6000 (Turing, 24 GB, compute 7.5)**, **driver 520 (CUDA 11.8)**,
`gcc` 8.5, `module load cuda/11.8`. Consecuencias que costaron horas:
- vLLM **no corre** (exige CUDA 12) → decoder con **llama.cpp** (`llama-cpp-python` 0.3.36 compilado en `.venv-gpu`
  con `-DGGML_CUDA=on -DCMAKE_CUDA_ARCHITECTURES=75 -DGGML_CUDA_NO_VMM=ON -DCMAKE_CXX_STANDARD_LIBRARIES=-lstdc++fs`).
  - `NO_VMM`: sin él abortaba con `CUDA error: out of memory` en `cuMemAddressReserve`.
  - `-lstdc++fs` **al final** del enlace (gcc 8 no trae `std::filesystem` en la `.so`); como flag de linker normal no funciona (orden).
  - Hace falta `LD_LIBRARY_PATH` con `$CUDA_HOME/lib64` (`cargar_cuda` en `jobs/_comun.sh`).
- El `torch` del proyecto (PyPI, cu12) **no ve la GPU** → entorno **`.venv-gpu`** con `torch 2.7.1+cu118`
  (`jobs/instalar_torch_gpu.sh`), `transformers>=4.56,<5`, `faiss-cpu`, `bm25s`, `ranx`, `pyarrow`, `pyyaml`,
  y luego `llama-cpp-python` + `fastapi` + `uvicorn` (`jobs/instalar_responder.sh`). **Un solo entorno** para recuperar y generar.
- El nodo de login mata procesos pesados (git checkout grande, etc.): usar `srun`.
- `.venv-gen` (llama.cpp viejo) lo usa la compañera para la fase 7 por lotes.

**Convención de jobs** (todos en `jobs/`, se lanzan desde la raíz con `logs/` creada): `logs/<job>_<id>.out` = avance y resultados;
`logs/<job>_<id>.err` = **solo errores** (las librerías ruidosas se filtran; `PYTHONWARNINGS=ignore`; los `ggml_cuda_init` no cuentan).
`jobs/_comun.sh` da `preparar_entorno`, `paso`, `correr`, `uvpy`, `cargar_cuda`, `cargar_gcc` (`GCC_MODULE`), `enviar_resumen`
(correo a `s.montoya112@uniandes.edu.co`; asunto OK / con errores / FALLÓ) y `resumen_manifest`.

**Portátil Windows de Samuel:** Application Control bloquea el `.venv` del proyecto y el DLL de parquet de `pyarrow`;
no hay `faiss`/`torch`. Se prueba con un venv aparte en el scratchpad (`.../scratchpad/venv/Scripts/python.exe`) y pruebas sin GPU.
Trucos: los heredocs de bash con apóstrofes se rompen → escribir con la herramienta Write y ejecutar el script;
`rm` en `/tmp` o rutas raíz está bloqueado → usar el scratchpad; los `.sh` van con LF (`.gitattributes`).

## 5. Lo que hice, en orden (resumen)

1. **Scraper (fase 2):** de YAML a JSON (`data/fuentes_propias.json`, `fuentes_seed.json`) y `data/enlaces.txt` (un link por línea; la
   metadata se completa sola: `src/descarga/metadatos.py`). `jobs/scrapper.sh` (sbatch, correo, reanudable).
2. **Codificación/Word/PDF:** detección de formato por bytes (`.doc` OLE y `.docx` guardados como `.html` salían como `�`);
   `.docx` por XML, `.doc` por `olefile` (tabla de piezas); PDF con capa de texto ilegible o escaneado → OCR con **docling**
   (código sin probar: no se pudo instalar en Windows); advertencias en el manifest.
3. **Merge** de `corpus` y `limpieza` en `main`; `jobs/chunking.sh`; `build.py`: stdout/stderr separados, omite `*.notas.md`,
   retira de `data/processed/texto/` los `.txt` obsoletos, y `--excluir-origen ronda_NN`.
4. **Proximidad / corpus recursivo:** `jobs/scraper_proximidad.sh` (4 rondas, `--rondas --minimo --max-por-ronda`),
   `src/descarga/proximidad.py --ronda N`. **Bug propio (corregido):** ids con sufijo -2/-3/-4 al releer el acumulado y URLs distintas
   de la misma norma (Senado, ruta antigua, DIAN) → copias. Arreglo: `src/descarga/claves.py` (clave de norma `ley_599_2000`),
   ids estables (un link ya descargado reutiliza su `doc_id`), `descubiertos.csv` por clave, y
   **`python -m src.descarga.deduplicar [--aplicar] [--explicar]`** (conserva la mejor copia; mueve el resto a `data/descartados/`;
   escribe `data/duplicados.json`). Resultado en hypatia: 7.063 entradas → ~3.590 documentos únicos.
5. **Fase 6 Recuperación** (`src/recuperacion/`): ver §6.
6. **Fase 7 Generación** (`src/generacion/`): ver §7. Motor llama.cpp porque vLLM no corre en hypatia.
7. **Fase 11** (`src/responder.py`, `src/api.py`, `interfaz/index.html`, `config/responder.json`, `jobs/instalar_responder.sh`,
   `jobs/servir.sh`, `jobs/probar_decoder.sh`): ver §8. Depuración larga del decoder (libstdc++fs, NO_VMM, LD_LIBRARY_PATH).
8. **Evaluación del corpus ampliado** y opción `--max-por-norma` (§9).

## 6. Fase 6 — Recuperación (`src/recuperacion/`)

Entrada: ítem (`pregunta`, `formato`, `opciones?`, `area?`). Salida de `Recuperador.recuperar(item)`:
`{"pasajes": [≤10 {doc_id, inicio, fin, texto, score, chunk_id, norma_id, via, opcion?}], "senales": {...}}`.

| Paso | Módulo | Qué hace |
|---|---|---|
| puente de ids | `catalogo.py` | `chunks.norma_id_canonico` (`codigo_general_proceso#art_391`) → id de la fase 4 (`ley_1564_2012#art_391`) |
| 6.1 | `normas_pregunta.py` | promueve chunks de las normas que nombra el **enunciado** (no las opciones de una cerrada) |
| 6.2 | `alias.py` | expande la consulta léxica con nombres completos desde `alias_normas.yaml` |
| 6.3 | `area.py` | filtro por área con salto al corpus general; **desactivado por defecto** (`area_modo="ninguno"`) |
| 6.4 | `hibrido.py` | BM25 + denso `bge-m3`, RRF k=60, 50 candidatos (`src/indice/fusion.py`) |
| 6.5 | `reranker.py` | `BAAI/bge-reranker-v2-m3` (50 → 10). Commit del modelo se registra en `<salida>.config.json` |
| 6.6 | `cerradas.py` | consulta base + una por opción, 2 pasajes de evidencia por opción |
| 6.7 | `contexto.py` | prompt `[P1]…[P8]`, ≤5.000 tokens (la usa `src/generacion/prompts.py`) |
| nuevo | `seleccion.py` | `--max-por-norma N`: tope de pasajes por norma en el top-10 (por defecto 0 = sin tope) |

`jobs/recuperar.sh` (GPU): corre `sample_50` + ablaciones (`sin_reranker`, `sin_directos`, `sin_alias`, `con_area`, `max2`, `max3`) y
`python -m src.recuperacion.evaluar` las compara contra la línea base de la fase 5 (`data/recuperacion/ablaciones.json`).
Latencia ≈ 0,46 s por ítem. `legal_basis` se usa **solo** para evaluar, nunca dentro de `recuperar`.

## 7. Fase 7 — Generación (`src/generacion/`)

`generar(item, pasajes, motor)` / `generar_lote(...)` → línea de `submissions.jsonl`. Esquemas JSON por formato (gramática de
llama.cpp; la justificación va **antes** de la letra), `prompts.py` (3 prompts en español; punto de entrada para few-shot, **vacío**),
`postproceso.py` (3–5 oraciones/≤150 palabras en semiabiertas, 5–8 en `analisis`, abstención válida si el JSON no sirve),
`motor.py` (`qwen3-8b`, `llama-3.1-8b`, `salamandra-7b`, GGUF Q8_0; `OLIVIA_FLASH_ATTN`, `OLIVIA_LLAMA_VERBOSE`),
`contexto_prueba.py` (`--modo oraculo|bm25|recuperacion`), `bench.py`, `jobs/generacion_bench.sh`
(`CONTEXTO=recuperacion sbatch jobs/generacion_bench.sh qwen3-8b`). **Sin medir** el tiempo por pregunta real ni RAGAS.
Pregunta abierta: ¿se permiten few-shot tomados de `sample_50`? (confirmar con el organizador).

## 8. Fase 11 — Responder, API e interfaz

- `src/responder.py`: `Responder.responder(texto|dict)`; deduce el formato (con opciones A) B) C) → cerrada; > ~120 palabras →
  abierta; si no, semiabierta); usa **el mismo camino que el lote**; devuelve `{submission, respuesta, pasajes, normas_citadas, abstencion,
  senales, latencia_ms}`. CLI: `python -m src.responder --id 512 [--comparar submissions.jsonl] [--solo-recuperar] [--json]`
  (busca el id en `data/test_992.jsonl` y luego en `data/sample_50.jsonl`; sale con 0 si coinciden normas y pasajes).
  `verificar(sub, rec)` llama `src.verificacion.aplicar` si existe (gancho de la fase 8).
- `src/api.py` (FastAPI): `POST /api/consulta`, `GET /api/salud`, sirve `interfaz/index.html`. Modelos al arrancar, un candado.
  `python -m src.api` con logs stdout/stderr separados.
- `interfaz/index.html`: muestra fuentes recuperadas, normas citadas (naranja = sin respaldo) y aviso de abstención; probada con backend falso.
- Instalación **validada en hypatia**: torch y llama.cpp conviven; decoder `qwen3-8b` cargó en ~170 s y generó JSON guiado.
  **Falta** correr `sbatch jobs/servir.sh` (túnel SSH) y `python -m src.responder --id N` con el modelo real y medir el tiempo.

## 9. Resultados y la decisión abierta (corpus)

Corpus: inicial 499 entradas (476 ok) → rondas → 7.063 → deduplicado ~3.590. Ahora **220.903 chunks / 3.480 documentos**
(antes 60.329 / 472). Cobertura de las citas de referencia en el top-10 (40 preguntas evaluables):

| Configuración | cuerpo@10 | artículo@10 | hit_doc@10 |
|---|---|---|---|
| Corpus anterior, pipeline completo | **0,925** (0,9375 sin área) | 0,605 (0,616) | 0,85 |
| **Corpus ampliado**, pipeline completo | 0,8875 | **0,7105** | 0,75 |
| ampliado, sin reranker | 0,875 | 0,668 | 0,75 |
| ampliado, sin directos / sin alias / con área | 0,8875 / 0,90 / 0,90 | 0,7105 / 0,7105 / 0,658 | 0,725 / 0,75 / 0,775 |

Índice solo (sin reranker), corpus ampliado: denso cuerpo@10 0,8625 · artículo@10 0,640; RRF cuerpo@10 0,8875 · cuerpo@50 0,9625.
Lectura: artículo sube ~10 puntos; cuerpo (lo que puntúa el evaluador) baja 1–2 preguntas de 40 → dentro del ruido.
Hipótesis: muchas normas parecidas llenan los 10 lugares. **Siguiente paso inmediato:** `git pull` en hypatia y `sbatch jobs/recuperar.sh`
→ mirar las filas `sample_50_max2` y `sample_50_max3` (grep `RESULTADO`). Regla de decisión propuesta:
- si el tope devuelve cuerpo@10 ≳ 0,925 sin bajar artículo@10 → **adoptar el corpus ampliado con `max_por_norma`** (poner el valor en `Config`);
- si no → recortar con `sbatch jobs/chunking.sh --excluir-origen ronda_03 ronda_04` (cada documento de ronda lleva `origen`) y rehacer índice;
- n=40 es poco: un punto es medio ítem. Ideal: ampliar el conjunto de desarrollo (paso 9.3).
Los documentos de la lista inicial no tienen `origen` y nunca se excluyen.

## 10. Pendientes priorizados

1. Decidir corpus (§9) y **congelar el índice esta noche**: guardar `sha256` de `faiss.index` (queda en `data/index/index_config.json`),
   tag de git (13.3). No volver a tocar `chunks.parquet` ni el índice.
2. `sbatch jobs/servir.sh` + `python -m src.responder --id N` en hypatia: confirmar funcionamiento y medir el tiempo por pregunta.
3. `CONTEXTO=recuperacion sbatch jobs/generacion_bench.sh qwen3-8b`: tiempo y RAGAS con el contexto real; elegir el decoder
   (`config/responder.json`, `OLIVIA_MODELO`). Integrar lo que traiga la compañera de `generacion`.
4. Fase 8: integrar `verificacion` (citas contra los 10 primeros pasajes, abstención por `senales`, validación con `jsonschema`).
5. Fase 10: checkpointing y prueba de determinismo (individual vs lote). Fase 12: Dockerfile, versiones congeladas
   (commit del reranker en `data/recuperacion/sample_50.config.json`), publicar corpus, `CORPUS.md`.
6. Reporte de avance (PDF 1 pág.), informe técnico, video. PR `interfazV2` → `main`; actualizar `uv.lock`.
7. Archivos grandes (`faiss.index`, `embeddings.npy`, `bm25/`) **no van a git**: carpeta compartida.

## 11. Mapa rápido de comandos (hypatia, desde la raíz del repo, con `logs/` creada)

```
sbatch jobs/instalar_torch_gpu.sh          # .venv-gpu (una vez)
sbatch jobs/instalar_responder.sh          # llama.cpp + FastAPI en .venv-gpu (una vez; ~20 min)
sbatch jobs/scrapper.sh                    # corpus (seed + propias + enlaces + proximidad)
sbatch jobs/scraper_proximidad.sh          # rondas recursivas (4 por defecto)
uv run python -m src.descarga.deduplicar [--aplicar] [--explicar]
sbatch jobs/chunking.sh [--excluir-origen ronda_03 ronda_04]
sbatch jobs/indice.sh                      # FAISS + BM25 + evaluación de la fase 5
sbatch jobs/recuperar.sh                   # fase 6 + ablaciones (sample_50)
CONTEXTO=recuperacion sbatch jobs/generacion_bench.sh qwen3-8b
sbatch jobs/servir.sh                      # interfaz; túnel SSH que imprime el .out
sbatch jobs/probar_decoder.sh              # diagnóstico del decoder (modo detallado)
PYTHONPATH=. .venv-gpu/bin/python -m src.responder --id 51 [--comparar submissions.jsonl]   # dentro de srun con GPU
```

## 12. Notas para el siguiente asistente

- Lee primero `checklist.md`, este archivo y `entregables/` (plantillas de entrega).
- Antes de proponer cambios al formato de citas/pasajes, confirma cómo lo lee `scripts/evaluate.py` y `scripts/citations.py`
  (no se modifican: son del evaluador oficial).
- `data/` no se analiza archivo por archivo (pidió Samuel): solo procesamiento; lo crítico es el código.
- Samuel prefiere planes antes de implementar cosas grandes (se usó modo plan) y respuestas concisas con comandos listos.
- Hay un riesgo no resuelto: la muestra de desarrollo es de 50 preguntas; cualquier ajuste fino puede sobreajustar.
