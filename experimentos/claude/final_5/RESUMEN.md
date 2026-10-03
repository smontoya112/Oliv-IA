# Configuración adoptada — `final_5` (sustituye a `final_2` como resumen vigente)

Misma configuración que `final_2` (ver `../final_2/RESUMEN.md`: qwen3-8b Q8_0, `data/index_base`, cerradas por logits de 4 rotaciones, texto libre por sub-tarea con
extracción literal) **más la expansión de la recuperación en las abiertas**, que es lo único que cambia: `config/responder.json` → `"abiertas": ["expansion"]`.

## Qué hace la expansión (`src/generacion/abiertas.py`, `Recuperador.recuperar_expandido`)

1. El decoder lee SOLO el enunciado del caso y devuelve el problema jurídico y 2–4 consultas cortas (instituciones, acciones, normas probables). Sin `legal_basis` ni nada de la muestra.
2. La recuperación se repite con el enunciado + esas consultas (BM25 y denso fusionados con RRF) y el reranker puntúa contra el problema jurídico y las preguntas del caso (cortos), no contra el relato completo, que se come los 512 tokens del cross-encoder.
3. **La lista final se fusiona por RRF con la lista de la recuperación original** (`abiertas.fusionar`): la expansión añade evidencia sin desplazar la que ya estaba bien.
   Con la lista expandida sola (`expansion_pura`) 4 de 5 abiertas empeoraban.
4. Mismo camino para el lote y la verificación en vivo (`responder.recuperar_item`); determinismo comprobado (8/8 ítems idénticos). Costo: ≈ +6 s por abierta (≈ 53 s en total) y ninguno en cerradas ni semiabiertas.

## Resultados (`sample_50`, evaluador oficial CON RAGAS real, juez `z-ai/glm-5.3-flash`)

| Corrida (misma `sample_50`) | Cerradas | RAGAS correctness | Citas | Abstención | **Total /80** |
|---|---|---|---|---|---|
| RAGAS #1 — `final_3`: sin expansión (config anterior) | 11/15 · 14,67 | 0,4912 · 14,74 | 0,857 · 17,14 | 0,861 · 8,60 | **55,15** |
| RAGAS #2 — `final_4`: expansión pura | 11/15 · 14,67 | 0,4783 · 14,35 | 0,878 · 17,55 | 0,884 · 8,84 | 55,41 |
| **RAGAS #3 — `final_5`: expansión fusionada (adoptada)** | 11/15 · 14,67 | **0,4923 · 14,77** | **0,898 · 17,96** | 0,884 · 8,84 | **56,24** |
| Referencia a superar (benchmark) | 0,905 | 0,451 | — | — | — |
| Mejor corrida histórica antes de esta rama (HANDOVER_3) | 10/15 | 0,457 | 0,837 | 0,837 | 51,31 |

Por formato (RAGAS por ítem, `ragas_*/ragas_items.json`; `src/analisis/comparar_ragas.py`):

| | semiabiertas (30) | abiertas (5) |
|---|---|---|
| #1 sin expansión | 0,5117 | 0,3682 |
| #2 expansión pura | 0,5047 | 0,3200 |
| #3 expansión fusionada | 0,5117 | 0,3760 |

Ítem a ítem en las abiertas (#1 → #3): 247 **0,217 → 0,481** (ahora concluye "procede la acción popular", Ley 472), 253 0,434 → 0,400, 272 0,309 → 0,267, 513 0,412 → 0,345, 679 0,469 → 0,387.

## Cómo leerlo (con honestidad)

* **El juez es ruidoso:** en los 30 ítems cuyo texto es idéntico entre dos corridas, la diferencia absoluta media entre dos juicios del mismo texto fue 0,043–0,053 por ítem (0,000 de sesgo medio). Con 5 abiertas, la diferencia de RAGAS entre #1 y #3 (+0,001 en total, +0,008 en abiertas) **es un empate**.
* Lo que sí es consistente: el ítem 247 se arregla de verdad (recupera la Ley 472), el recall de citas sube de 0,857 a 0,898 (los 6 cuerpos normativos de referencia de las abiertas quedan en el top-10 y 6/6 se citan, contra 5/6 y 4/6), y eso vale +0,8 puntos del componente de citación.
* La expansión pura quedó descartada: 1 ítem gana mucho y 4 pierden; la fusión conserva casi todo el beneficio sin esa pérdida (`ragas_final4_expansion/comparacion_vs_ragas_final3_base.json` y `ragas_final5_rrf/comparacion_*.json`).
* RAGAS está en el tope acordado: **3 corridas gastadas** (#1, #2, #3).
