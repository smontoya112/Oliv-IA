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
- [ ] **Paso 5.1:** Seleccionar e integrar el modelo encoder (`BAAI/bge-m3` o `intfloat/multilingual-e5-large`).
- [ ] **Paso 5.2:** Construir el índice denso en FAISS (`faiss.IndexFlatIP`) o Qdrant.
- [ ] **Paso 5.3:** Construir el índice léxico con `bm25s` (normalizando texto y conservando tokens numéricos).
- [ ] **Paso 5.4:** Crear el script reproducible `python -m src.indice.build` que genere el índice y escriba `index_config.json`.
- [ ] **Paso 5.5:** Evaluar métricas de recuperación aisladas (Recall@10 y Recall@50) sobre las muestras usando `ranx`.

## Fase 6: Recuperación (Jueves 1)
- [ ] **Paso 6.1:** Implementar la extracción e inclusión directa por metadato de normas explicitadas en la pregunta.
- [ ] **Paso 6.2:** Configurar la expansión de consultas mediante el diccionario de alias.
- [ ] **Paso 6.3:** Aplicar filtrado por área con fallback a corpus general según umbral.
- [ ] **Paso 6.4:** Implementar búsqueda híbrida (BM25 + Denso/Sparse) y fusión con Reciprocal Rank Fusion (RRF, k=60).
- [ ] **Paso 6.5:** Integrar reranker (`BAAI/bge-reranker-v2-m3`) para filtrar los top 50 a los 10 mejores pasajes.
- [ ] **Paso 6.6:** Adaptar la recuperación para preguntas cerradas (enunciado + opciones) para recopilar evidencia de descarte.
- [ ] **Paso 6.7:** Diseñar la construcción del prompt delimitando contexto entre 3.000 y 5.000 tokens ([P1]…[P8]).

## Fase 7: Generación (Jueves 1)
- [ ] **Paso 7.1:** Evaluar modelos decoder (`Qwen3-8B`, `Llama-3.1-8B-Instruct`, `salamandra-7b-instruct`) comparando calidad y tiempo de respuesta.
- [ ] **Paso 7.2:** Configurar vLLM (temperatura 0, semilla fija, structured outputs por JSON schema y ejecución offline por lotes `LLM.generate`).
- [ ] **Paso 7.3:** Diseñar y probar los 3 prompts en español adaptados a cada formato (cerrado, semiabierto, abierto) e incluir ejemplos few-shot propios.
- [ ] **Paso 7.4:** Implementar el postprocesamiento estricto de longitud de texto (oraciones y conteo máximo de palabras).
- [ ] **Paso 7.5:** Ajustar la concisión y terminología jurídica orientada a optimizar RAGAS Answer Correctness.

## Fase 8: Verificación de citas y abstención (Jueves 1 - Viernes 2)
- [ ] **Paso 8.1:** Extraer y canonizar citas presentes en el texto generado mediante el parser de la Fase 4.
- [ ] **Paso 8.2:** Validar que cada cita tenga respaldo en los primeros 10 pasajes recuperados; suprimir o corregir las no respaldadas.
- [ ] **Paso 8.3:** Reordenar los pasajes recuperados garantizando que los citados estén dentro del top 10.
- [ ] **Paso 8.4:** Definir la política de abstención según puntaje de reranking, disponibilidad de citas e insuficiencia de evidencia.
- [ ] **Paso 8.5:** Implementar la validación automática del esquema JSON final con `jsonschema`.

## Fase 9: Iteración sobre las muestras (Miércoles 30 - Viernes 2)
- [ ] **Paso 9.1:** Ejecutar ciclos de evaluación sobre las 50 muestras con y sin bandera `--ragas`.
- [ ] **Paso 9.2:** Construir la matriz de análisis de errores por ítem (evaluando presencia en corpus, top-50, top-10, cita y formato).
- [ ] **Paso 9.3:** Ampliar el conjunto de desarrollo mediante preguntas sintéticas o manuales para pruebas adicionales.
- [ ] **Paso 9.4:** Registrar parámetros, tiempos y métricas de cada experimento en un CSV o MLflow.

## Fase 10: Tiempo y robustez (Viernes 2)
- [ ] **Paso 10.1:** Medir tiempos de ejecución por formato y proyectar el tiempo total para las 992 preguntas (meta: 3–4 horas).
- [ ] **Paso 10.2:** Implementar checkpointing para escritura incremental y reanudación ante fallos.
- [ ] **Paso 10.3:** Realizar pruebas de determinismo comparando ejecuciones individuales frente a ejecuciones por lote.

## Fase 11: Conexión de la interfaz (Viernes 2)
- [ ] **Paso 11.1:** Exponer la función `responder(pregunta)` (por ejemplo mediante `FastAPI`) garantizando coherencia con el pipeline de lote.
- [ ] **Paso 11.2:** Verificar que la interfaz visualice correctamente los pasajes recuperados y las normas citadas.
- [ ] **Paso 11.3:** Validar la ejecución del comando CLI `python -m src.responder --id 512` para la verificación en vivo.

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