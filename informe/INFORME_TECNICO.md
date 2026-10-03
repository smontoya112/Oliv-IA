# Informe técnico — Oliv-IA

**Hackathon 2026 · Universidad de los Andes** · Integrantes: _completar_

## 1. Arquitectura del sistema

Una pregunta recorre seis etapas, todas en un solo proceso por GPU (`src/lote.py` para la entrega, `src/responder.py` para la verificación en vivo; ambos usan el mismo camino de código).

| Etapa | Qué hace |
|---|---|
| Ingesta | Descarga de fuentes oficiales (Senado, Corte Constitucional, DIAN…) a Markdown con metadatos (`src/descarga`). Corpus final: **504 documentos / 62.824 fragmentos**: la lista objetivo de normas más las que nombran las 992 preguntas (37 normas nuevas). |
| Segmentación | Fragmentos de ≤300 palabras con encabezado (norma y artículo); se parte por párrafo, oración y `;`/`:`, sin cortar oraciones; se indexa el texto vigente (sin apartes tachados) (`src/procesamiento`). |
| Índice | BM25 (`bm25s`) y FAISS `IndexFlatIP` sobre vectores `bge-m3` de 1024 dimensiones; versiones y sha256 quedan en `index_config.json` (`src/indice`). |
| Recuperación | 100 candidatos léxicos + 100 densos → fusión RRF (k=60) → 50 al reranker → **10 pasajes**. Además: inclusión directa de normas nombradas en el enunciado, expansión con alias, un pasaje garantizado por opción en cerradas, máximo 2 pasajes por norma y 5 sentencias (`src/recuperacion`). |
| Generación | Una sola estrategia por formato (abajo). Temperatura 0, semilla 0, caché KV reiniciada por pregunta. |
| Verificación | Cada cita se extrae con el parser oficial y debe tener su cuerpo normativo en los 10 pasajes; si no, se trae el mejor fragmento de esa norma del catálogo y, si la norma no está, se elimina la oración que la cita (`src/verificacion`). |

**Generación por formato.** *Cerradas:* se toma la probabilidad de cada letra como primer token tras «Respuesta:» (con `<think>` vacío), promediada sobre 4 rotaciones cíclicas de las opciones; la justificación breve se genera después, para la letra ya decidida. *Semiabiertas:* un router de sub-tarea (la trae la pregunta o se infiere) elige una plantilla de forma y longitud; en «reproducción literal» el texto del artículo se copia del pasaje sin generar. *Abiertas:* el decoder deduce, solo del enunciado, el problema jurídico y consultas cortas; se recupera de nuevo, el reranker puntúa contra ese resumen y la lista se fusiona (RRF) con la original. **Abstención:** política mínima; en cerradas nunca (adivinar sobre la evidencia rinde más que el 0,5 de abstenerse) y en texto libre solo si la generación falla o no hay pasajes.

## 2. Selección de encoder y decoder

| Componente | Modelo | Motivo | Alternativas |
|---|---|---|---|
| Encoder | `BAAI/bge-m3` (rev. `5617a9f6`) | Multilingüe, vector denso de 1024 d; se alimenta con 512 tokens (los fragmentos tienen ≤300 palabras) y corre en fp16 en una GPU de 24 GB. Se combina con BM25: sobre el corpus completo, cuerpo@10 fue 0,8125 (BM25), 0,8625 (denso) y **0,8875 (RRF)**; en el corpus base, antes del reranker, el denso solo (0,9125) superó a la fusión (0,8875) y no se evaluó quitar BM25. | **No se comparó otro encoder**; no hay ablación registrada. |
| Reranker | `BAAI/bge-reranker-v2-m3` | Cross-encoder multilingüe de la misma familia. Sin reranker: cuerpo@10 0,875 y artículo@10 0,668, contra 0,8875 y 0,7105 con él (corpus completo). | Sin reranker (peor). |
| Decoder | `Qwen3-8B`, GGUF Q8_0, llama.cpp | Una sola familia para los tres formatos. Con contexto oráculo, cerradas de `sample_50`: Qwen3-8B 8/15 (11 s/preg.), Llama-3.1-8B 10/15 (12 s) y Salamandra-7B 7/15 (27 s). Con recuperación real y el método de letras, Qwen alcanzó 11/15. Llama-3.1-8B empató en texto libre (proxy 0,376 vs 0,378) y usar dos decoders complica el límite de parámetros. | Llama-3.1-8B, Salamandra-7B; modo `<think>` de Qwen (9/15 y 45–50 s por cerrada: descartado). |

**Inferencia:** Q8_0, ventana de 8.192 tokens, temperatura 0, semilla 0, llama.cpp con CUDA 11.8 en una Quadro RTX 6000 (24 GB). Tiempo medio **≈19 s por pregunta** con la mezcla del test (cerradas 24 s, semiabiertas 14 s, abiertas 53 s; ≈2,7 h estimadas para 992 preguntas en 2 GPU).

## 3. Resultados sobre las preguntas de muestra (`sample_50`, evaluador oficial)

| Componente | Puntos | Posibles |
|---|---:|---:|
| Exactitud en cerradas (11/15) | 14,67 | 20 |
| Calidad de citación (recall de cuerpos 0,898) | 17,96 | 20 |
| Abstención calibrada (0,884) | 8,84 | 10 |
| **Total automático sin RAGAS** | **41,47** | **50** |
| Texto libre (RAGAS *answer correctness* 0,4923; referencia 0,451) | 14,77 | 30 |
| **Total con RAGAS** | **56,24** | **80** |

Punto de partida de esta ronda: 34,03 / 50 sin RAGAS (8/15 en cerradas, citas 0,796). Las mejoras vienen de decidir la letra por probabilidades sobre rotaciones (7 → 11 ítems con el mismo corpus), de un corpus sin ~3.000 documentos de «rondas de proximidad» que en la muestra eran distractores (cuerpo@10 0,9625 contra 0,8875) y de la expansión de la recuperación en abiertas (citas 0,857 → 0,898). El juez RAGAS (`glm-5.3-flash`) varía ≈0,045 por ítem sobre el mismo texto: la diferencia de 0,001 en RAGAS entre usar o no la expansión es un empate; lo medible es el recall de citas.

**Cómo llegamos a esta configuración** (cerradas de `sample_50`, 15 ítems; un ítem = 0,067; detalle en `experimentos/claude/REGISTRO.md`):

| Variante | Cerradas | Tiempo por cerrada |
|---|---:|---:|
| Estrategia anterior (un JSON con veredicto por opción), índice completo / corpus base | 8/15 / 7/15 | 22–35 s |
| Letra elegida solo por la evidencia (opción cuyos pasajes puntúan más en el reranker) | 4/15 | — |
| Razonar con `<think>` (1.200 tokens) y luego comprometer la letra | 9/15 (10/15 con respaldo en probabilidades) | 45–50 s |
| Menos pasajes (3, 5, 6) / solo los pasajes de cada opción / 12–14 pasajes | 9–10/15 / 6/15 / igual o peor que 10 | — |
| **Probabilidades de la letra, 4 rotaciones, corpus base, 8–10 pasajes (adoptada)** | **11/15** | **≈24 s** (4 s la letra + justificación) |

En texto libre, medido con un proxy local de RAGAS (0,25·coseno e5 + 0,75·F1 léxico; ordena variantes pero no sustituye al juez): 0,348 con el prompt único anterior, 0,378 con plantillas por sub-tarea y 0,388 con la instrucción de sistema libre. Que el no determinismo viniera de reutilizar la caché KV entre preguntas se comprobó: con el reinicio por pregunta, dos corridas completas dieron las mismas 50 respuestas.

**Errores frecuentes.** En cerradas fallan 4 de 15: el 128 (la norma no llegó al top-10: fallo de recuperación), el 528 (aritmética de cuantía), el 647 (ítem mal formado) y el 308 (lectura/conocimiento). Las abiertas son lo más débil (RAGAS 0,376 contra 0,512 en semiabiertas) y solo hay 5. Se probaron y descartaron: razonar antes de responder, usar menos o más de 10 pasajes, una plantilla por tipo de caso y una segunda pasada de revisión (sin ganancia y el doble de tiempo).

## 4. Limitaciones

1. **Muestra pequeña:** 15 cerradas (un ítem = 0,067) y 5 abiertas. Las decisiones de diseño se tomaron sobre ese ruido y los 40 ítems evaluables de recuperación; hay riesgo de sobreajuste. En cerradas (0,733) no se alcanzó la referencia de 0,905 (14/15).
2. **Cobertura del corpus:** el corpus base deja fuera normas que el corpus ampliado sí tenía (≈4 % del banco según la lista objetivo) y no se pudo medir esa pérdida. De las normas que nombran las 992 preguntas, quedan sin texto `sentencia_su-279_2019` (la Corte la sirve como página dinámica), `ley_2568_2021`, `decreto_3030_2022`, `decreto_4302_2008` y la Sentencia SL-3871 de 2021; la Resolución 368 de 2014 (23 preguntas de teoría del acto administrativo) tampoco está.
3. **Abstención sin calibrar:** `sample_50` casi no trae casos donde convenga abstenerse; la política es mínima y nunca se activa en cerradas. No se midió qué hace el sistema ante preguntas fuera del corpus.
4. **Decoder:** razona poco en cálculos (ítem 528) y su conocimiento jurídico depende del contexto recuperado; el modo de pensamiento extendido arregla algunos casos pero rompe otros y es 3–12 veces más lento.
5. **Reproducibilidad dependiente del hardware:** el resultado es idéntico entre corridas y entre lote y verificación en vivo en la misma GPU y con la misma compilación de llama.cpp; no se verificó en otro modelo de GPU. Sin reiniciar la caché KV por pregunta, la misma configuración daba entre 0,47 y 0,67 en cerradas.
6. **Sin comparación de encoders** y con hiperparámetros de recuperación (k, tope por norma) fijados sobre pocas preguntas.
