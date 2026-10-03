# Congelación de la entrega y auditoría de integridad (3 oct 2026)

## 1. Qué quedó fijado

**Código.** Las respuestas de las 992 preguntas se generaron con el commit `88e2569` de la rama `main` (clon `~/hackatron/prueba_claude` de hypatia). Lo posterior son documentos, el empaquetado del corpus, la limpieza y la auditoría;
la única diferencia en `src/` y `config/` es que se borró `src/generacion/humo.py` (una prueba de humo que nada importa). Falta el tag definitivo: `git tag -a entrega-final -m "Entrega Hackathon 2026"` sobre el commit que incluya `submissions.jsonl`.

**Índice y fragmentos** (`data/index_base`, `data/processed_base/chunks.parquet`; creados el 3 oct 2026 en hypatia, Quadro RTX 6000; ver `experimentos/claude/corpus_enriquecido/index_config.json`):

| Elemento | Valor |
|---|---|
| Fragmentos / documentos | 62.824 / 504 |
| sha256 de `chunks.parquet` | `06438a86902d489dd3489b5f2c7a4cb844b0692052155aff8ac9995d7e6e0831` |
| sha256 de `faiss.index` | `b4108466398e67ffc71876b985b4d0a4908f38b7f2c9d2c09d23638253078924` |
| Encoder / dimensión / tipo | `BAAI/bge-m3`, 1024, `IndexFlatIP`; BM25 con `bm25s` (k1 1,2; b 0,75) |
| Preguntas de entrada (`data/test_992.jsonl`) | sha256 que empieza por `9b128c805169f634` (992 líneas; el mismo archivo en las máquinas) |

Para comprobarlos tras instalar el comprimido: `python scripts/entrega_corpus.py instalar --zip corpus_Oliv-IA.zip` (compara ambos hashes). El comprimido entregado (`corpus_Oliv-IA.zip`, 365.524.102 bytes) tiene sha256 `462cd0166db753de1fcf01f35f85850a9b8ae90ba2424c4220e38cf5300f4c16` y está en https://1drv.ms/u/c/6c8185a7cb3fb6b0/IQCTpAESkIKYRqOr3PiM6w10AbC6z_9dPSdXqr41knvdnqY?e=cj23d1 (lectura pública). La copia de `corpus_manifest.json` que va dentro del zip se generó antes de existir el enlace y trae `enlace_nube` como pendiente; la del repositorio sí lo trae.

**Modelos** (públicos; revisiones exactas de la caché de Hugging Face de hypatia; el nombre del blob es su sha256):

| Rol | Repositorio | Commit | Archivo principal | sha256 |
|---|---|---|---|---|
| Decoder | `Qwen/Qwen3-8B-GGUF` | `7c41481f57cb95916b40956ab2f0b139b296d974` | `Qwen3-8B-Q8_0.gguf` (8.709.518.112 bytes) | `ce48260c074613c3e6632f26b19dd4cdab35ae91b0edf3259dd15cd3ea2a1830` |
| Encoder | `BAAI/bge-m3` | `5617a9f61b028005a4858fdac845db406aefb181` | `pytorch_model.bin` | `b5e0ce3470abf5ef3831aa1bd5553b486803e83251590ab7ff35a117cf6aad38` |
| Reranker | `BAAI/bge-reranker-v2-m3` | `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e` | `model.safetensors` | `d9e3e081faff1eefb84019509b2f5558fd74c1a05a2c7db22f74174fcedb5286` |

El encoder y el reranker quedan fijados por revisión en el código (`src/indice/encoder.py`, `data/recuperacion/sample_50.config.json`). El GGUF se descarga con `Llama.from_pretrained(repo, filename)` sin revisión: lo fija la caché; en una máquina nueva
conviene comprobar el sha256 de arriba.

**Entorno y parámetros.** Python 3.12.12, torch 2.7.1+cu118, transformers 4.57.6, faiss-cpu 1.15.1, bm25s 0.3.11, llama-cpp-python 0.3.36 compilado con CUDA 11.8 (`-DCMAKE_CUDA_ARCHITECTURES=75 -DGGML_CUDA_NO_VMM=ON`); lista completa en `requirements.txt`.
Inferencia (`config/responder.json`): `qwen3-8b` Q8_0, `n_ctx` 8192, temperatura 0, semilla 0, caché KV reiniciada por pregunta, estrategia `razonada`, abiertas con `expansion`.

## 2. Auditoría de integridad

Herramienta: `python -m src.analisis.auditoria_integridad` (resultado completo en `experimentos/claude/auditoria/auditoria.json`; no contiene texto de preguntas).

**Modelos cerrados.** Se buscaron clientes y nombres de modelos de APIs cerradas en `src/`, `config/`, `jobs/` y `scripts/`: **0 coincidencias en el sistema que responde**. El decoder configurado es `qwen3-8b` (GGUF local). Las 9 coincidencias restantes están en el evaluador oficial
(`scripts/evaluate.py` y sus dependencias) y en los jobs de RAGAS: el juez de texto libre llama a un modelo por OpenRouter, solo para **evaluar** la muestra, nunca para responder. El pipeline que responde no llama a ningún servicio de modelos externo: el decoder (llama.cpp), el encoder y el reranker corren en la GPU local con los pesos de la caché.

**Fugas por n-gramas.** Se compararon el enunciado y las opciones de las 992 preguntas del test y de las 50 de muestra con el texto procesado de los 509 documentos del corpus, con n-gramas de 12 palabras (normalizadas: minúsculas, sin puntuación).

| Archivo | Preguntas | Con algún 12-grama en el corpus | Cobertura > 0,5 | Cobertura 0,2–0,5 | Cobertura máxima |
|---|---:|---:|---:|---:|---:|
| `test_992.jsonl` | 992 | 38 | 2 | 14 | 0,896 |
| `sample_50.jsonl` | 50 | 1 | 0 | 1 | 0,353 |

La cobertura es la fracción de los 12-gramas de la pregunta que aparecen en un mismo documento. Lectura: los documentos con más solapamiento son siempre **fuentes primarias** (sentencias, Código Penal, Código Civil, Código General del Proceso,
Constitución, leyes), no bancos de preguntas ni material de estudio; son preguntas que **citan literalmente** el texto de una norma o de una sentencia (la de mayor cobertura, 0,896, es una pregunta semiabierta que reproduce un pasaje de la sentencia C-75 de 2007,
una de las normas que nombra su propio enunciado y que se añadió al corpus por eso). No se encontró ningún documento con muchas preguntas del test.

Límites de esta auditoría: detecta coincidencias literales, no paráfrasis; solo revisa el corpus entregado (no los datos de entrenamiento de los modelos); y que un enunciado cite una norma que luego se incorpora al corpus es una decisión de diseño (el corpus se enriqueció con las normas
que nombran las preguntas, usando solo el texto de los enunciados), no una fuga de respuestas: el archivo de preguntas del test no trae respuestas. En el sistema entregado, `legal_basis` y las respuestas de la muestra solo se usan para evaluar; los experimentos del 1 de octubre con «contexto oráculo» (que sí usaron `legal_basis`) fueron solo para comparar decoders y no forman parte del pipeline.

## 3. Preguntas que fallaron por truncación en el reranker (corrida del 3 oct)

Durante la corrida de las 992 preguntas algunas lanzaron `Truncation error: Sequence to truncate too short to respect the provided max_length`: el reranker (`truncation="only_second"`) solo puede recortar el pasaje, y si la consulta
por sí sola pasa de 512 tokens el tokenizador falla; el ítem quedaba como abstención (id 695, una abierta con un enunciado de 3.364 caracteres; id 86, una cerrada; y los ids 245 y 258 de la parte 3).
Corrección (`src/recuperacion/reranker.py`, commit «reranker: si la consulta no cabe…»): solo cuando antes fallaba, se recorta la consulta a sus primeros 96 y últimos 160 tokens y se reintenta; las demás consultas se puntúan igual que antes.
Prueba: `tests/test_reranker_truncacion.py`. Los ids afectados se volvieron a responder con el código corregido y sus líneas van en `data/lote/test_992/sub_0_fix.jsonl`, que al ordenar los `sub_*.jsonl` queda primero y `src.lote unir` conserva
la primera aparición de cada id. El resto de las respuestas se generó con el commit `88e2569`; la corrección no cambia ninguna respuesta que no hubiera fallado.
