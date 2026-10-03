# Configuración adoptada — `final_2` (rama `prueba-claude`)

Qué entrega: el pipeline completo de la corrida (recuperación → generación → fase 8) con `estrategia: razonada`, medido sobre `sample_50` por el camino real
(`python -m src.lote`) y verificado en vivo contra `Responder` (`python -m src.responder`). `final_1` es una repetición anterior: las 50 líneas son idénticas salvo `latencia_ms`.

## Configuración (reproducible)

| | |
|---|---|
| Decoder | `qwen3-8b`, GGUF `Qwen3-8B-Q8_0.gguf` (repo `Qwen/Qwen3-8B-GGUF`, revisión `7c41481f57cb95916b40956ab2f0b139b296d974`, blob sha256 `408b955510e196121c1c375201744783b5c9a43c7956d73fc78df54c66e883d6`), `llama-cpp-python 0.3.36`, `n_ctx 8192`, temperatura 0, semilla 0, `reiniciar()` por ítem |
| Corpus / índice | `data/index_base`: 467 documentos (origen `None` del manifiesto, sin rondas de proximidad), 57.346 chunks, `sha256_chunks 413a44e4…e83b`, `faiss.index sha256 26901bc6a2ddf877b98e4e08b7c6b09ed7f850aa48400ea4c00dd03a0d47de7a`, encoder `BAAI/bge-m3@5617a9f6…`, reranker `BAAI/bge-reranker-v2-m3@953dc6f6…` (ver `config.json`, `../index_base_config.json`, `../corpus_base_docs.txt`, `../corpus_base_manifest.json`) |
| Recuperación | defaults de `Config` (sin cambios de código): híbrido BM25+denso con RRF, directos, alias, reranker, garantía por opción, tope 2 por norma, sin copias, tope 5 sentencias, top 10 |
| Cerradas | letra por probabilidades de 4 rotaciones de las opciones (sistema sin la regla "solo JSON", ancla `Respuesta:`, 10 pasajes ≤ 4.500 tokens) + justificación breve de esa letra con gramática JSON; fase 8 verifica citas |
| Texto libre | router por sub-tarea (`src/generacion/subtarea.py`), `SISTEMA_LIBRE`, límites por plantilla, extracción literal del artículo cuando la sub-tarea es "reproducción literal"; abiertas con prompt v2 |

## Resultados (evaluador oficial sin RAGAS + proxy de texto libre)

| | Cerradas | Citas (índice) | Abstención | **Automático /50** | Proxy texto libre | s/pregunta (mezcla del test) |
|---|---|---|---|---|---|---|
| Estado de `main` esta noche (`antes_completo`: estrategia anterior, índice completo) | 8/15 (0,533) | 0,7959 | 0,7442 | 34,03 | 0,3525 | 24,6 |
| Estrategia anterior sobre el corpus base (`antes_base`) | 7/15 (0,467) | 0,8571 | 0,7674 | 34,14 | 0,3500 | 24,3 |
| **Esta configuración (`final_2`)** | **11/15 (0,733)** | **0,8571** | **0,8605** | **40,41** | **0,3879** | **18,0** |
| Referencia: mejor corrida histórica (corpus 1, HANDOVER_3 §6) | 10/15 | 0,8367 | 0,8372 | 38,43 | — | ≈ 25 |

* Cerradas +4 ítems sobre `antes_base` con el MISMO corpus: la ganancia viene de la forma de decidir la letra (logits con permutaciones y sistema sin JSON), no solo del corpus. Medida por permutación (51 predicciones): 0,73 contra 0,61 con el índice completo.
* Citas: la ganancia (0,796 → 0,857) viene del corpus base (mismas citas con la estrategia anterior sobre el base).
* Texto libre: proxy +0,035 sobre el mismo corpus. **RAGAS real no se corrió** (la regla era correrlo solo con cerradas ≥ 0,905; aquí 0,733).
* Determinismo: `final_1` y `final_2` idénticas; 25 de 25 ítems regenerados con `Responder` coinciden con el lote (normas, pasajes y línea completa) → `determinismo.json`.
* Tiempos medidos en dos GPUs Quadro RTX 6000 compartiendo el nodo con otros experimentos: ≈ 22 s por cerrada, 13 s por semiabierta, 44 s por abierta (≈ 18 s de media en el test; presupuesto ≈ 22 s).

## Límites de lo que esto demuestra

15 cerradas y 35 de texto libre son pocas: +4 ítems en cerradas es una señal clara pero no una garantía de 0,73 en las 289 del test. Los fallos que quedan en cerradas (128, 308, 528, 647) son de conocimiento o lectura y uno está mal formado.
El corpus base deja fuera ~4 % de normas del banco (fuera de la lista objetivo). Proxy ≠ juez.
