# Oliv-IA — Hackathon 2026

**Integrantes:** Ariadna Thais Vargas Contreras, Laura Rodriguez Sierra y Samuel Montoya Salazar · **Universidad de los Andes**

Sistema de respuesta a preguntas de derecho colombiano con un decoder abierto de tamaño reducido
(Qwen3-8B, cuantizado a Q8_0, temperatura 0) y un corpus jurídico propio. Responde preguntas cerradas,
semiabiertas y abiertas, cita las normas que respaldan cada respuesta, verifica esas citas contra la evidencia
recuperada y se abstiene cuando no puede responder.

## Corpus e índice

| Recurso | Enlace | Tamaño | Licencia |
|---|---|---|---|
| Corpus procesado e índice vectorial | [corpus_Oliv-IA.zip (OneDrive)](https://1drv.ms/u/c/6c8185a7cb3fb6b0/IQCTpAESkIKYRqOr3PiM6w10AbC6z_9dPSdXqr41knvdnqY?e=cj23d1) | 366 MB (365.524.102 bytes) | CC BY 4.0 |

El enlace es de solo lectura para cualquier persona que lo tenga (se comprobó sin iniciar sesión). `sha256` del comprimido: `462cd0166db753de1fcf01f35f85850a9b8ae90ba2424c4220e38cf5300f4c16`.

El comprimido (`corpus_<equipo>.zip`) contiene `LICENSE`, `corpus_manifest.json`, `corpus/` con los documentos
procesados e `indice/` con el índice serializado y los fragmentos. El corpus de generación tiene **504 documentos y
62.824 fragmentos** (`data/index_base`); el enlace debe permanecer activo hasta el 2 de noviembre de 2026.
Para usarlo con este código, un solo comando deja el índice en `data/index_base/` y los fragmentos y textos en `data/processed_base/` (lo que lee `config/responder.json`) y comprueba los `sha256`
de los fragmentos y del índice FAISS (también guardados en `indice/index_config.json`):

```bash
python scripts/entrega_corpus.py instalar --zip corpus_Oliv-IA.zip
```

El inventario de los 504 documentos (URL, fecha de consulta, artículos, fragmentos y áreas), el criterio de selección, el método de ingesta y la evolución del puntaje están en [`CORPUS.md`](CORPUS.md) y [`corpus_manifest.json`](corpus_manifest.json)
(se generan con `scripts/entrega_corpus.py`; `data/corpus_manifest.json` es el manifiesto interno de la descarga, con todos los documentos intentados). El índice y los fragmentos no se modifican después de la entrega.

## Arquitectura

```
pregunta ─► recuperación híbrida (BM25 + bge-m3, RRF) ─► reranker ─► 10 pasajes
              ├─ cerradas ──► probabilidad de cada letra (4 rotaciones de las opciones) ─► justificación breve
              ├─ semiabiertas ─► sub-tarea ─► plantilla de forma y longitud (o copia literal del artículo)
              └─ abiertas ──► recuperación expandida con consultas deducidas del enunciado ─► respuesta
                                                      │
                          verificación de citas contra los pasajes ─► abstención si procede ─► submissions.jsonl
```

| Componente | Elección | Motivo |
|---|---|---|
| Encoder | `BAAI/bge-m3` (rev. `5617a9f6`), vectores de 1024 d, FAISS `IndexFlatIP` | Multilingüe; en el corpus completo la fusión con BM25 (RRF) dio cuerpo@10 0,8875 contra 0,8625 del denso y 0,8125 del léxico. No se comparó otro encoder. |
| Decoder | `Qwen3-8B` GGUF Q8_0 con llama.cpp, temperatura 0, semilla 0, ventana de 8.192 | Con él, el método de letras acierta 11/15 cerradas de la muestra; una sola familia para los tres formatos. Alternativas probadas: Llama-3.1-8B y Salamandra-7B (`informe/INFORME_TECNICO.pdf`). |
| Segmentación | Fragmentos de ≤300 palabras con encabezado norma/artículo; párrafo → oración → `;`/`:`; solo texto vigente | Citas y artículos conservan su contexto; no se corta a mitad de oración. |
| Recuperación | 100 léxicos + 100 densos → RRF (k=60) → 50 candidatos → 10 pasajes; normas nombradas en el enunciado, alias y un pasaje por opción en cerradas; máximo 2 pasajes por norma | Solo cuentan los 10 primeros pasajes en el evaluador. |
| Reordenamiento | `BAAI/bge-reranker-v2-m3` (commit `953dc6f6`) | Sin él, cuerpo@10 0,875 y artículo@10 0,668; con él 0,8875 y 0,7105 (corpus completo). |
| Verificación y abstención | Cada cita debe tener su cuerpo normativo en los 10 pasajes; si no, se trae el mejor fragmento de esa norma o se elimina la oración. Cerradas: nunca se abstiene; texto libre: solo si falla la generación o no hay pasajes. | El evaluador castiga el doble una cita sin respaldo. |

Documentación del diseño y de lo que se probó y se descartó: [`informe/INFORME_TECNICO.pdf`](informe/INFORME_TECNICO.pdf) (resumen),
[`docs/prueba_claude.md`](docs/prueba_claude.md) (rediseño de la generación), [`docs/congelacion.md`](docs/congelacion.md) (versiones, hashes y auditoría de integridad) y [`experimentos/claude/REGISTRO.md`](experimentos/claude/REGISTRO.md) (cada experimento con sus métricas).

## Dependencias

* **Hardware:** una GPU NVIDIA de 24 GB por parte de la corrida (probado en Quadro RTX 6000, arquitectura Turing, CUDA 11.8) y 32 GB de RAM.
  No se midió el mínimo de memoria de GPU. En hypatia, la cola `gpu` da 2 GPU por usuario.
* **Software:** Python 3.12, CUDA 11.8 (módulo `cuda/11.8`), GCC entre 9 y 11 para compilar llama.cpp. Versiones exactas en [`requirements.txt`](requirements.txt)
  (torch 2.7.1+cu118, transformers 4.57.6, faiss-cpu 1.15.1, bm25s 0.3.11, llama-cpp-python 0.3.36, fastapi, uvicorn…). El juez de texto libre del evaluador usa
  [`scripts/requirements-evaluador.txt`](scripts/requirements-evaluador.txt).
* **Modelos** (públicos, sin token; se descargan a la caché de Hugging Face la primera vez): `Qwen/Qwen3-8B-GGUF` (`*Q8_0.gguf`, ≈ 9 GB), `BAAI/bge-m3` y `BAAI/bge-reranker-v2-m3`.
* **Instalación en hypatia** (una vez):

```bash
sbatch jobs/instalar_torch_gpu.sh      # .venv-gpu: torch 2.7.1 para CUDA 11.8 y las librerías de src/indice
```

```bash
sbatch jobs/instalar_responder.sh      # compila llama-cpp-python con CUDA, instala fastapi/uvicorn y prueba que conviven
```

* **Instalación en otra máquina con GPU:** `pip install -r requirements.txt` y compilar `llama-cpp-python==0.3.36` con CUDA como indica el encabezado de `requirements.txt`
  (o `jobs/preparar_local.sh`).

## Reproducción

Con el corpus y el índice descargados (sección anterior) y el archivo de preguntas en `data/test_992.jsonl`, **un único comando** genera la entrega:

```bash
bash run.sh
```

En hypatia (Slurm) manda las 3 partes como jobs de GPU en paralelo y un job que las une; sin Slurm corre las partes una tras otra en la GPU local.
El resultado queda en `data/lote/test_992/submissions.jsonl`, que se copia a `submissions.jsonl`. Variantes:

```bash
PARTES=1 bash run.sh data/sample_50.jsonl   # las 50 preguntas de muestra, ≈ 20 min en una GPU
```

```bash
REHACER_INDICE=1 bash run.sh                # rehace chunking e índice del corpus base desde data/md antes de responder
```

```bash
REHACER_CORPUS=1 bash run.sh                # además, vuelve a descargar el corpus (horas)
```

* **Tiempo:** ≈ 19 s por pregunta con la mezcla del test (cerradas 24 s, semiabiertas 14 s, abiertas 53 s) más ≈ 3,5 min por parte para cargar los modelos:
  992 preguntas ≈ 5,2 h de GPU en total (≈ 1,8 h con 3 GPU, ≈ 2,7 h con 2).
* **Determinismo:** temperatura 0, semilla 0 y caché KV reiniciada por pregunta; dos corridas completas dan las mismas respuestas y la verificación en vivo (`python -m src.responder --id N --comparar …`) regenera lo mismo que el lote, en la misma máquina.
* **Qué se verificó:** la corrida por partes con unión automática (6 preguntas en 3 partes, con el índice final), el lote de la muestra completa y la coincidencia entre lote y verificación en vivo. `run.sh` solo se probó en modo `DRY_RUN=1` (los jobs que lanza sí se probaron por separado); la descarga, el chunking y el índice del corpus se ejecutaron paso a paso, no encadenados desde cero con `REHACER_CORPUS=1`.
* **Evaluar la muestra** (evaluador oficial, sin modificar):

```bash
python scripts/evaluate.py --submission data/lote/sample_50/submissions.jsonl --split sample
```

## Resultados sobre las preguntas de muestra

Evaluador oficial sobre `sample_50` con la configuración entregada (juez de texto libre `glm-5.3-flash`):

| Componente | Puntos | Posibles |
|---|---:|---:|
| Exactitud en cerradas (11/15) | 14,67 | 20 |
| Calidad de citación (recall de cuerpos 0,898) | 17,96 | 20 |
| Abstención calibrada (0,884) | 8,84 | 10 |
| **Total automático sin RAGAS** | **41,47** | **50** |
| Texto libre (RAGAS *answer correctness* 0,4923; referencia 0,451) | 14,77 | 30 |

La muestra tiene 15 cerradas (un ítem = 0,067) y 5 abiertas: las diferencias pequeñas son ruido. Detalle y errores en el informe técnico.

## Interfaz gráfica

La interfaz (`interfaz/index.html`, servida por `src/api.py`) corre en un nodo con GPU de hypatia; recuperación y generación comparten un solo proceso.

```bash
mkdir -p logs && sbatch jobs/servir.sh          # PUERTO=8100 para otro puerto
```

```bash
tail -f logs/servir_<jobid>.out                 # ahí salen el nodo y el comando del túnel
```

En otra terminal de tu computador abre el túnel que imprime el `.out` (`ssh -L 8000:<nodo>:8000 <usuario>@<hypatia>`) y entra a http://localhost:8000.
Cada respuesta muestra el texto, las normas citadas (en naranja las que ningún pasaje respalda), las fuentes recuperadas y un aviso si el sistema se abstuvo.
La API es `POST /api/consulta` con `{"pregunta": "...", "formato": opcional, "opciones": opcional}`; sin `formato` se deduce del texto (con opciones A) B) C) es cerrada; un caso largo es abierta; el resto, semiabierta).

**Verificación en vivo (jurado):**

```bash
srun --mem=32gb --time=00:30:00 --gres=gpu:1 -p gpu --pty bash -i
```

```bash
module load cuda/11.8 && PYTHONPATH=. .venv-gpu/bin/python -m src.responder --id 512 --comparar submissions.jsonl
```

`--id` busca la pregunta en `data/test_992.jsonl` y luego en `data/sample_50.jsonl`; `--comparar` regenera la respuesta y la contrasta con la línea de `submissions.jsonl`
(normas citadas, pasajes recuperados y su orden, respuesta) y sale con código 0 si coinciden las normas y los pasajes. El decoder se cambia en `config/responder.json` (o con `OLIVIA_MODELO`).
Para volver a la estrategia anterior sin tocar código: `OLIVIA_ESTRATEGIA=actual OLIVIA_INDICE=data/index`.

## Licencias

* **Código** (este repositorio): MIT, ver [`LICENSE`](LICENSE).
* **Corpus procesado e índice** (el comprimido de la sección «Corpus e índice»): CC BY 4.0, ver [`LICENSE_CORPUS`](LICENSE_CORPUS) (dentro del comprimido se llama `LICENSE`). Los textos normativos colombianos son de dominio público; la licencia cubre el procesamiento, la segmentación y los metadatos.
* **Modelos** (Qwen3-8B, bge-m3, bge-reranker-v2-m3): conservan sus propias licencias.

## Estructura del repositorio

| Ruta | Contenido |
|---|---|
| `run.sh` | Comando único de reproducción |
| `CORPUS.md`, `corpus_manifest.json` | Bitácora e inventario del corpus entregado |
| `LICENSE`, `LICENSE_CORPUS` | Licencia del código (MIT) y del corpus e índice (CC BY 4.0) |
| `src/` | Pipeline: `descarga/` y `procesamiento/` (ingesta), `indice/`, `recuperacion/`, `generacion/`, `verificacion/`, `lote.py` (corrida por partes), `responder.py` y `api.py` (verificación en vivo), `analisis/` (métricas y experimentos) |
| `jobs/` | Jobs de Slurm: instalación, corpus, índice, corrida (`lanzar_corrida.sh`, `corrida.sh`, `unir_corrida.sh`), empaquetado del corpus (`entrega_corpus.sh`), interfaz |
| `config/responder.json` | Decoder, índice, estrategia y ventana de contexto |
| `scripts/`, `schema/` | Evaluador oficial (`evaluate.py`, `citations.py`, `common.py`) y esquema de la entrega (`submission.schema.json`): no se modifican |
| `interfaz/` | Interfaz gráfica |
| `informe/` | Informe técnico (`INFORME_TECNICO.pdf`, fuente en Markdown) |
| `data/` | Solo lo liviano: manifiestos, alias, muestra, fuentes y resultados; el corpus, los índices y las preguntas del test no se versionan |
| `tests/` | Pruebas (`python -m pytest`; corren sin GPU con un motor falso) |
| `docs/`, `experimentos/claude/` | Diseño de la generación y registro de experimentos |
| `entregables/`, `Ejemplo de entrega/` | Plantillas y ejemplo de la organización |

## Limitaciones conocidas

1. **Muestra pequeña:** 15 cerradas y 5 abiertas; las decisiones se tomaron sobre ese ruido. En cerradas (0,733) no se alcanzó la referencia de 0,905.
2. **Corpus:** el corpus base deja fuera normas que el corpus ampliado tenía (≈ 4 % del banco) y no se pudo medir esa pérdida; hay normas nombradas en las preguntas sin texto
   (`sentencia_su-279_2019`, `ley_2568_2021`, `decreto_3030_2022`, `decreto_4302_2008`, SL-3871 de 2021 y la Resolución 368 de 2014).
3. **Abstención sin calibrar:** la muestra casi no trae casos para abstenerse; la política es mínima.
4. **Reproducibilidad dependiente del hardware:** idéntica en la misma GPU y compilación de llama.cpp; no se verificó en otro modelo de GPU.
5. **Sin comparación de encoders** y con hiperparámetros de recuperación fijados sobre pocas preguntas.
