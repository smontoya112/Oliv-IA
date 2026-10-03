# Checklist Hackathon 2026

## Fase 0: Preparación (Martes 29)
- [x] **Paso 0.1:** Crear la estructura base del repositorio (`scripts/`, `src/`, `data/`, `config.yaml`, etc.) y fijar el entorno con `uv` o `poetry`.
- [x] **Paso 0.2:** Verificar la memoria de GPU disponible (Turing / Colab / propia) y configurar el servidor de inferencia (`vLLM` con `enable_thinking=False` o `llama.cpp`/`Ollama`).
- [x] **Paso 0.3:** Leer `scripts/evaluate.py` línea por línea para entender extracción de normas, respaldo, normalización y comparación con `legal_basis`.
- [ ] **Paso 0.4:** Generar y validar una línea base trivial (`entrega.jsonl` con abstención) y ejecutar la evaluación inicial con `sample_50.jsonl`.
- [x] **Paso 0.5:** Inspeccionar `sample_50.jsonl` (campos, subtareas, formato de `legal_basis` y necesidad de clasificación de área).

## Fase 1: Inventario de fuentes (Martes 29 - Miércoles 30)
- [x] **Paso 1.1:** Parsear los `legal_basis` de las 50 muestras, agruparlos por cuerpo normativo y cruzar con `seed_targets.json`.
- [x] **Paso 1.2:** Consolidar la lista objetivo de normas base por área jurídica.
- [x] **Paso 1.3:** Compilar la jurisprudencia requerida (sentencias citadas, sentencias C-, SU de la Corte Constitucional, Consejo de Estado y Corte Suprema).
- [x] **Paso 1.4:** Auditar que todas las fuentes seleccionadas sean estrictamente primarias (sin bancos de preguntas ni material de estudio).

## Fase 2: Descarga (Miércoles 30)
- [x] **Paso 2.1:** Implementar el scraper base (`httpx`/`requests` + `selectolax`/`BeautifulSoup` o `Playwright`) con rate limiting, reintentos y caché local.
- [x] **Paso 2.2:** Configurar la gestión de casos especiales (paginación del Senado, codificación `windows-1252`, HTMLs de la Corte Constitucional).
- [x] **Paso 2.3:** Guardar archivos crudos en `data/raw/` con hash SHA-256 y registrar metadatos en el manifest.
- [x] **Paso 2.4:** Extraer texto de archivos PDF (vía `PyMuPDF`/`pdfplumber` o OCR con `ocrmypdf`/`docling`) y registrar en `CORPUS.md`.

## Fase 3: Limpieza y segmentación (Miércoles 30 - Jueves 1)
- [x] **Paso 3.1:** Aplicar limpieza mínima (normalización Unicode NFC, remoción de menús/encabezados sin alterar caracteres jurídicos clave).
- [x] **Paso 3.2:** Implementar segmentación por artículo mediante expresiones regulares (cubriendo variantes y parágrafos).
- [x] **Paso 3.3:** Asociar la ruta jerárquica (Libro > Título > Capítulo) a cada artículo.
- [x] **Paso 3.4:** Extraer notas de vigencia (`vigente`, `modificado_por`, `notas`) a campos independientes.
- [x] **Paso 3.5:** Subdividir artículos extensos en bloques de 400–500 tokens manteniendo metadatos y numeración de partes.
- [x] **Paso 3.6:** Segmentar sentencias por secciones (antecedentes, consideraciones, resuelve) en ventanas de 400 tokens con solapamiento.
- [x] **Paso 3.7:** Anteponer encabezados contextualmente estructurados a cada fragmento de texto.
- [x] **Paso 3.8:** Guardar la estructura de fragmentos en `chunks.parquet`.
- [x] **Paso 3.9:** Correr validación automática de completitud (conteo de artículos, vacíos, duplicados con hash/`datasketch`).

## Fase 4: Normalización canónica de citas (Miércoles 30)
- [x] **Paso 4.1:** Definir el estándar de identificadores canónicos (`ley_1564_2012#art_391`, `sentencia_C-355_2006`).
- [x] **Paso 4.2:** Crear el diccionario YAML de alias para mapear siglas y formas comunes.
- [x] **Paso 4.3:** Construir el parser de citas con expresiones regulares y escribir pruebas unitarias con `pytest` basadas en `sample_50.jsonl`.

## Fase 5: Indexación (Jueves 1)
- [x] **Paso 5.1:** Seleccionar e integrar el modelo encoder (`BAAI/bge-m3` o `intfloat/multilingual-e5-large`). → `bge-m3` fijado en `src/indice/encoder.py`.
- [x] **Paso 5.2:** Construir el índice denso en FAISS (`faiss.IndexFlatIP`) o Qdrant. → hecho en Hypatia (Quadro RTX 6000, 60.329 vectores, `faiss.index` en `data/index/`).
- [x] **Paso 5.3:** Construir el índice léxico con `bm25s` (normalizando texto y conservando tokens numéricos).
- [x] **Paso 5.4:** Crear el script reproducible `python -m src.indice.build` que genere el índice y escriba `index_config.json`.
- [x] **Paso 5.5:** Evaluar métricas de recuperación aisladas (Recall@10 y Recall@50) sobre las muestras usando `ranx`. → `data/index/eval_recuperacion.json`. Denso: Recall@10 artículo 0,35 / documento 0,64; RRF: Recall@50 documento 0,71; cobertura de cuerpo normativo en el top-50 (RRF) 1,0 (n=40).

## Fase 6: Recuperación (Jueves 1)
- [x] **Paso 6.1:** Implementar la extracción e inclusión directa por metadato de normas explicitadas en la pregunta. → código listo (`src/recuperacion/normas_pregunta.py`; solo normas del enunciado); falta validar en Hypatia (`sbatch jobs/recuperar.sh`).
- [x] **Paso 6.2:** Configurar la expansión de consultas mediante el diccionario de alias. → código listo (`src/recuperacion/alias.py`); falta validar en Hypatia (`sbatch jobs/recuperar.sh`).
- [x] **Paso 6.3:** Aplicar filtrado por área con fallback a corpus general según umbral. → código listo (`src/recuperacion/area.py`); calibrado con las ablaciones de `sample_50` (`data/recuperacion/ablaciones.json`): con reranker activo, desactivar el filtro de área dio mejor cobertura (cuerpo@10 0.9375, articulo@10 0.6158) que con el filtro activo (0.925/0.6053), así que `Config.area_modo` queda en `"ninguno"` por defecto (`--area filtro` sigue disponible para reactivarlo).
- [x] **Paso 6.4:** Implementar búsqueda híbrida (BM25 + Denso/Sparse) y fusión con Reciprocal Rank Fusion (RRF, k=60). → código listo (`src/recuperacion/hibrido.py` (RRF en `src/indice/fusion.py`)); falta validar en Hypatia (`sbatch jobs/recuperar.sh`).
- [x] **Paso 6.5:** Integrar reranker (`BAAI/bge-reranker-v2-m3`) para filtrar los top 50 a los 10 mejores pasajes. → código listo (`src/recuperacion/reranker.py`); falta validar en Hypatia (`sbatch jobs/recuperar.sh`).
- [x] **Paso 6.6:** Adaptar la recuperación para preguntas cerradas (enunciado + opciones) para recopilar evidencia de descarte. → código listo (`src/recuperacion/cerradas.py`); falta validar en Hypatia (`sbatch jobs/recuperar.sh`).
- [x] **Paso 6.7:** Diseñar la construcción del prompt delimitando contexto entre 3.000 y 5.000 tokens ([P1]…[P8]). → código listo (`src/recuperacion/contexto.py` (lo usa `src/generacion/prompts.py`)); falta validar en Hypatia (`sbatch jobs/recuperar.sh`).

## Fase 7: Generación (Jueves 1)
- [x] **Paso 7.1:** Evaluar modelos decoder (`Qwen3-8B`, `Llama-3.1-8B-Instruct`, `salamandra-7b-instruct`) comparando calidad y tiempo de respuesta. → corrido en Hypatia (`sbatch jobs/generacion_bench.sh`, contexto "oráculo", `data/processed/bench_generacion.csv`). Con el contexto oráculo ganó `llama-3.1-8b` (66.7% vs 53.3% de qwen3-8b y 46.7% de salamandra-7b en cerradas; ≈ 3.07 h proyectadas a 992 preguntas), pero esa exactitud tiene ruido de ±1-2 preguntas entre corridas (15 ítems). **Decisión final: `qwen3-8b`**, tras repetir el benchmark de qwen3-8b y llama-3.1-8b con los pasajes reales de la Fase 6 corregida (`CONTEXTO=recuperacion`) y evaluarlos con RAGAS (subtotal automático sobre 80): qwen3-8b 51.23 vs llama-3.1-8b 47.20 — cerradas 0.667 vs 0.600, citas (índice) 0.796 vs 0.674, abstención (calibración) 0.826 vs 0.721 y RAGAS `correctness` 0.457 vs 0.484 (ambos sobre el baseline 0.451; diferencia dentro del ruido del juez). Riesgo conocido: qwen3-8b proyecta ≈ 3.9 h a 992 preguntas (llama ≈ 3.7 h), al límite de la meta de 3-4 h, sobre todo por las preguntas abiertas (35.9 vs 26.7 s). `salamandra-7b` se descarta: ~2.5-3× más lento (vocabulario multilingüe grande) y proyecta ~8.1 h, el doble del límite, con la peor exactitud. JSON siempre válido en los 3 modelos (150/150).
- [x] **Paso 7.2:** Configurar vLLM (temperatura 0, semilla fija, structured outputs por JSON schema y ejecución offline por lotes `LLM.generate`). → vLLM no corre en los nodos GPU de Hypatia (Quadro RTX 6000, driver CUDA 11.8); se adaptó a `llama-cpp-python` (`src/generacion/motor.py`) con temperatura 0, semilla fija y gramática JSON schema. Sin batching real entre ítems (llama.cpp los atiende uno a uno); validado end-to-end en Hypatia tras resolver: (1) el job necesita GPU para poder importar la librería compilada (`libcuda.so.1`), (2) compilar con `GGML_CUDA_NO_VMM=on` — el allocator VMM de ggml-cuda aborta en el primer `llama_decode` con este driver — y con `uv pip install --no-cache` (si no, reusa una build vieja), (3) usar la libstdc++ de gcc 9.3.0 (OpenHPC) en vez de la del sistema (gcc 8.5, sin `std::filesystem`) ni la (más vieja) que empaqueta el Python de `uv`.
- [x] **Paso 7.3:** Diseñar y probar los 3 prompts en español adaptados a cada formato (cerrado, semiabierto, abierto) e incluir ejemplos few-shot propios. → `src/generacion/prompts.py` (los 3 prompts) + `src/generacion/ejemplos.py` (un ejemplo redactado a mano por formato, armado con `construir_mensajes` para que luzca igual a una consulta real). Se activan por defecto en `pipeline.preparar`/`generar_lote` sin que haya que pasarlos explícitamente (`ejemplos={}` los desactiva, para una ablación). Tiempo/calidad remedidos con los ejemplos activos y el contexto real de la Fase 6 (ver Paso 7.1 y 7.5): los ejemplos suben el tiempo por pregunta (qwen3-8b ≈ 14.7 s en cerradas, 10.2 s en semiabiertas, 35.9 s en abiertas).
- [x] **Paso 7.4:** Implementar el postprocesamiento estricto de longitud de texto (oraciones y conteo máximo de palabras). → código listo (`src/generacion/postproceso.py`); validado en Hypatia: JSON válido y dentro de los límites de longitud en las 150 respuestas generadas (3 modelos × 50 preguntas).
- [x] **Paso 7.5:** Ajustar la concisión y terminología jurídica orientada a optimizar RAGAS Answer Correctness. → corrido en Hypatia (`jobs/evaluar_ragas.sh`, envoltorio `jobs/ragas_con_timeout.py` que le pone timeout/menos concurrencia al juez sin tocar `scripts/evaluate.py`, ver Paso 0.3). Con contexto oráculo: `correctness=0.3475` (por debajo del baseline 0.451); se intentó ajustar `semi_open`/`open_ended` en `src/generacion/prompts.py` pero una regla nueva degradó la exactitud de `multiple_choice` (0.667→0.533) al aplicarse también a ese formato — se revirtió todo el cambio a su versión original (confirmado luego que la exactitud seguía variando con el prompt ya idéntico: es no-determinismo de `llama.cpp`/CUDA en Hypatia entre corridas, no el prompt). Repetido el benchmark con el contexto real de la Fase 6 (`CONTEXTO=recuperacion sbatch jobs/generacion_bench.sh llama-3.1-8b`, tras la corrección de recuperación de `smontoya112`): **`correctness=0.4724`, ya supera el baseline 0.451**. Nota para Fase 8: con pasajes reales la abstención mecánica actual (solo si no hay pasajes) casi no se dispara (`abstuvo_bien` 5→0, `respondio_mal` 1→12) porque la recuperación siempre trae candidatos aunque sean irrelevantes (`hit_doc@10=0.85`); la política fina de abstención queda como la mejora de mayor impacto pendiente. Tras fusionar la corrección de recuperación (`sin_copias`, tope de 5 sentencias: `hit_doc@10` 0.85→0.90, `cuerpo@10` 0.9375→0.9625) y la Fase 8 en `postproceso.ensamblar`, se repitió todo con qwen3-8b y llama-3.1-8b (`recuperar.sh` → `CONTEXTO=recuperacion generacion_bench.sh` → `evaluar_ragas.sh`): RAGAS `correctness` llama 0.484 (0.4724 en la corrida anterior) y qwen3-8b 0.457; los dos superan el baseline 0.451. Modelo elegido: `qwen3-8b` (ver Paso 7.1).

## Fase 8: Verificación de citas y abstención (Jueves 1 - Viernes 2)
- [x] **Paso 8.1:** Extraer y canonizar citas presentes en el texto generado mediante el parser de la Fase 4. → código listo (`src/verificacion/citas.py`: `citations.extract`, el mismo parser del evaluador, + `normalizacion.to_canonical_id`); Validado en Hypatia (`jobs/verificar.sh`, job 755211, qwen3-8b, con catálogo): 0 errores de schema, 0 citas insertadas, 0 oraciones eliminadas y 0 citas sin respaldo; las métricas quedan idénticas antes y después (el bench de `generacion_bench.sh` ya aplica `ensamblar` con la Fase 8, así que `_antes` no es una línea base sin verificar).
- [x] **Paso 8.2:** Validar que cada cita tenga respaldo en los primeros 10 pasajes recuperados; suprimir o corregir las no respaldadas. → código listo (`src/verificacion/citas.py`, `verificar`): si la norma está en el corpus trae su chunk al top 10; si no, elimina la oración; Validado con `jobs/verificar.sh` (job 755211, ver Paso 8.1). Mejora posterior: `completar_con_evidencia` agrega a la respuesta las normas de los 3 primeros pasajes que el modelo no nombró (prueba local sin catálogo: índice de citas de qwen 0,796 → 0,857); falta confirmar en Hypatia con `RAGAS=1 sbatch jobs/verificar.sh qwen3-8b`.
- [x] **Paso 8.3:** Reordenar los pasajes recuperados garantizando que los citados estén dentro del top 10. → código listo (`src/verificacion/orden.py`); Validado con `jobs/verificar.sh` (job 755211, ver Paso 8.1).
- [x] **Paso 8.4:** Definir la política de abstención según puntaje de reranking, disponibilidad de citas e insuficiencia de evidencia. → código listo (`src/verificacion/abstencion.py`): abstención mínima (nunca en selección múltiple; en libres solo si falla la generación o la recuperación); `UMBRAL_TOP1` desactivado; para calibrarlo: `UMBRALES="-2 0 2" RAGAS=1 sbatch jobs/verificar.sh <modelo>`. Resultado (qwen3-8b, 755211): 1 abstención (`generacion_fallida`); `abstencion_calib` 0.8256 sin cambio. El barrido de umbral no se corrió: solo 1 ítem cumple la condición (`items_sin_cita_respaldada=1`), así que el umbral no puede mover más de 1 ítem; se deja desactivado. La pérdida restante son 7 `respondio_mal` (recuperación sin evidencia que igual se responde).
- [x] **Paso 8.5:** Implementar la validación automática del esquema JSON final con `jsonschema`. → código listo (`src/verificacion/esquema.py`): `jsonschema` si está instalado (el job `jobs/verificar.sh` lo instala en `.venv-gen` y lo usa con `uv run --with`), si no un validador mínimo equivalente, + `evaluate.validate`. Validado con `jobs/verificar.sh` (job 755211, ver Paso 8.1).

## Fase 9: Iteración sobre las muestras (Miércoles 30 - Viernes 2)
- [x] **Paso 9.1:** Ejecutar ciclos de evaluación sobre las 50 muestras con y sin bandera `--ragas`. → hechos en Hypatia con `jobs/evaluar_ragas.sh` (con RAGAS) y `jobs/verificar.sh` (sin RAGAS) sobre qwen3-8b y llama-3.1-8b con contexto oráculo y con pasajes reales; resultados en `data/processed/ragas_*.json`, `data/processed/verificacion/eval_*.json` y consolidados en `data/processed/experimentos.csv` (Paso 9.4). Mejor entrega: qwen3-8b con recuperación real, subtotal automático 51.23/80 (RAGAS `correctness` 0.457).
- [x] **Paso 9.2:** Construir la matriz de análisis de errores por ítem (evaluando presencia en corpus, top-50, top-10, cita y formato). → `python -m src.analisis.matriz_errores` -> `data/processed/analisis/matriz_errores.csv` (qwen3-8b, 50 ítems). Sin columna de top-50: la Fase 6 solo guarda el top 10. Resultado: 34 ok, 9 `sin_citas_ref` (legal_basis en prosa, no diagnosticables), 2 `no_en_top10` (ids 128, 247), 2 `recuperado_no_citado` (490, 991), 3 `cerrada_incorrecta` con la evidencia ya en el top 10 (ids 51, 528, 647); 0 fuera del corpus, 0 formatos inválidos. La recuperación ya no es el cuello de botella en la muestra: la mayor pérdida controlable son las cerradas con evidencia presente y letra equivocada. `ok` significa que se citó un cuerpo del legal_basis, no que RAGAS dé puntaje alto (el RAGAS por ítem no se guarda). Iteración sobre esas fallas (qwen3-8b, job 755463): la regla de nombrar la norma/sentencia de la pregunta arregló el ítem 991 (citas 0.796→0.837); el ítem 247 fallaba por un bucle de repetición de Qwen3 en voraz (repetía "artículo 209 de la Constitución Política" hasta el tope), no por truncamiento: duplicar `max_tokens` no lo arreglaba (+109 s) y el reintento con `repeat_penalty=1.2` y el mismo tope sí (+22 s, abstenciones de `open_ended` 1→0), aunque la respuesta rescatada es incorrecta (la recuperación no trajo la Ley 472). Subtotal automático 37.51→38.43.
- [x] **Paso 9.3:** Registrar parámetros, tiempos y métricas de cada experimento en un CSV o MLflow. → `python -m src.analisis.registro_experimentos` -> `data/processed/experimentos.csv` (formato largo: fase, experimento, parámetros, métrica, valor, fuente; consolida ablaciones de la Fase 6, benchmarks de la Fase 7 y las evaluaciones de las Fases 7 y 8). Se regenera completo desde los resultados de los jobs.

## Fase 10: Tiempo y robustez (Viernes 2)
- [ ] **Paso 10.1:** Medir tiempos de ejecución por formato y proyectar el tiempo total para las 992 preguntas (meta: 3–4 horas).
- [ ] **Paso 10.2:** Implementar checkpointing para escritura incremental y reanudación ante fallos.
- [ ] **Paso 10.3:** Realizar pruebas de determinismo comparando ejecuciones individuales frente a ejecuciones por lote.

## Fase 11: Conexión de la interfaz (Viernes 2)
- [ ] **Paso 11.1:** Exponer la función `responder(pregunta)` (por ejemplo mediante `FastAPI`) garantizando coherencia con el pipeline de lote. → código listo (`src/responder.py` + `src/api.py` (usa el mismo camino que el lote); falta validar en Hypatia (`sbatch jobs/instalar_responder.sh` y `jobs/servir.sh`)).
- [ ] **Paso 11.2:** Verificar que la interfaz visualice correctamente los pasajes recuperados y las normas citadas. → código listo (`interfaz/index.html` muestra fuentes, normas citadas y abstención (probado en el navegador con un backend falso); falta verla con el modelo real).
- [ ] **Paso 11.3:** Validar la ejecución del comando CLI `python -m src.responder --id 512` para la verificación en vivo. → código listo (`python -m src.responder --id N [--comparar submissions.jsonl]`; falta correrlo en Hypatia).

## Fase 12: Reproducibilidad y publicación (Viernes 2)
- [ ] **Paso 12.1:** Construir el `Dockerfile` basado en CUDA y configurar el comando `make reproduce`.
- [ ] **Paso 12.2:** Congelar versiones de dependencias y commits exactos de los modelos en Hugging Face.
- [ ] **Paso 12.3:** Empaquetar y publicar el corpus procesado e índice (Zenodo / Google Drive) probando descarga en modo incógnito.
- [ ] **Paso 12.4:** Documentar `CORPUS.md` y estructurar el archivo `corpus_manifest.json`.

## Fase 13: Hitos del Viernes 2 y congelación
- [ ] **Paso 13.1:** Enviar el reporte de avance (PDF de 1 página) antes de las 13:00 a `rf.manrique@uniandes.edu.co`.
- [ ] **Paso 13.2:** Realizar la auditoría de integridad (confirmar ausencia de modelos cerrados y verificar n-gramas contra fugas).
- [ ] **Paso 13.3:** Crear el tag de Git definitivo, registrar el hash del índice y congelar el código.

## Fase 14: Día de la entrega (Sábado 3)
- [ ] **09:00 AM:** Recibir el conjunto final de 992 preguntas y validar la estructura de entrada.
- [ ] **Ejecución:** Iniciar la corrida ciega y monitorear logs de progreso.
- [ ] **Validación:** Validar los esquemas JSON de todas las respuestas generadas y verificar ausencia de IDs omitidos.
- [ ] **Antes de 15:00 PM:** Hacer commit de `submissions.jsonl` y realizar simulación de prueba en vivo.

## Fase 15: Entregables finales
- [ ] **Informe técnico:** Redactar el documento técnico (máximo 3 páginas) detallando arquitectura, decisiones y resultados.
- [ ] **Video:** Grabar la presentación (máximo 5 minutos) cubriendo arquitectura, corpus, demo end-to-end y limitaciones.