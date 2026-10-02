# Reporte de avance — Hackathon 2026

**Equipo:** Oliv-IA
**Integrantes:** Laura Rodríguez, Ariadna Vargas, Samuel Montoya
**Fecha de la medición:** 2 de octubre de 2026, 12:26 (última corrida completa sobre las 50 preguntas de muestra)

---

## 1. Puntaje sobre las preguntas de muestra

Resultado de `python scripts/evaluate.py --submission data/processed/bench_generacion/qwen3-8b.jsonl --split sample`.

| Componente | Puntos obtenidos | Puntos posibles |
|---|---:|---:|
| Exactitud en cerradas (10/15 = 0,667) | 13,33 | 20 |
| Calidad de citación (índice 0,837; 0 % sin respaldo) | 16,73 | 20 |
| Abstención calibrada (0,837; 36 bien, 7 mal) | 8,37 | 10 |
| **Total automático sin RAGAS** | **38,43** | **50** |

Observaciones sobre el resultado:

Qwen3-8B superó a Llama-3.1-8B (32,68/50) con los mismos pasajes recuperados, por eso lo elegimos como modelo generador. Con el filtro que elimina las citas ausentes de los pasajes, el puntaje fue 37,51. Dos ajustes lo subieron a 38,43: pedir al modelo que nombre la norma por la que pregunta el enunciado y reintentar con penalización de repetición cuando entra en bucle. Con el juez RAGAS, la última medición de Qwen fue 0,457 (13,72/30), por encima de la referencia de 0,451.

## 2. Estado del corpus

| Métrica | Valor |
|---|---|
| Documentos incorporados | 3.480 en la versión ampliada del corpus (3.485 descargados de 3.590 intentados): leyes, decretos, conceptos DIAN, sentencias, códigos y Constitución |
| Fragmentos indexados | 220.903 en la versión ampliada. El puntaje de la sección 1 se midió con la versión anterior (476 documentos, 60.329 fragmentos) |
| Áreas del banco con cobertura | 10 de 10 |
| Áreas del banco sin cobertura | Ninguna; las más delgadas son penal (212 documentos) y familia (190) |

Fuentes consultadas: Secretaría General del Senado (2.137 documentos), DIAN (1.213), Relatoría de la Corte Constitucional (116), Corte Suprema de Justicia (14), Consejo de Estado (4) y Comunidad Andina (1). Texto extraído sin OCR.

## 3. Arquitectura actual

| Componente | Elección |
|---|---|
| Encoder | BAAI/bge-m3 (vectores de 1.024 dimensiones), índice FAISS exacto |
| Decoder | Qwen3-8B cuantizado a 8 bits, temperatura 0, semilla fija y salida forzada al formato JSON del esquema |
| Estrategia de recuperación | Híbrida: BM25 (léxica) y búsqueda densa aportan 100 candidatos cada una, se fusionan y un *reranker* (bge-reranker-v2-m3) elige los 10 mejores. Si la pregunta nombra una norma, sus artículos entran directamente; en cerradas se garantiza un pasaje por opción. En las muestras, la norma correcta aparece entre los 10 pasajes en el 89 % de los casos y el artículo exacto en el 71 % |
| Segmentación del corpus | Un fragmento por artículo (máx. 300 palabras), encabezado con la norma y el artículo de origen; sentencias por secciones; se excluye el texto derogado o declarado inexequible |
| Mecanismo de abstención | Verificación posterior a la generación: se elimina toda cita que no figure en los pasajes recuperados, y el sistema se abstiene si no queda ninguna cita respaldada o si la generación falla tras un reintento |

## 4. Riesgos identificados

1. **Corpus ampliado sin medir:** el puntaje proviene de la versión anterior del corpus. Repetiremos la recuperación, la generación y la verificación de citas con los 220.903 fragmentos, y conservaremos la versión que puntúe mejor.
2. **Cerradas y abstención:** 3 cerradas fallan aunque la evidencia correcta está entre los 10 pasajes, y hay 7 respuestas erróneas frente a 0 abstenciones. Ajustaremos las instrucciones para cerradas y fijaremos un umbral de confianza de la recuperación por debajo del cual el sistema se abstenga.
3. **Tiempo de ejecución:** las 50 muestras tardan 725 s, lo que proyecta ~4,0 h para las 992 (~38 s por pregunta abierta), dentro de las ~6 h disponibles. Guardaremos el avance pregunta por pregunta para reanudar si el proceso se interrumpe.
4. **Determinismo en la verificación en vivo:** el motor de inferencia en GPU mostró variación entre corridas con la misma entrada. Fijaremos la semilla, probaremos la regeneración de respuestas y congelaremos el índice en la entrega.
5. **Entregables del sábado:** faltan el contenedor reproducible con comando único, la interfaz conectada al sistema, `CORPUS.md` y la publicación del corpus y del índice.
