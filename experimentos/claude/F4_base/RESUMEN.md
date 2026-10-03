# Texto libre por sub-tarea (`F1_base`, `F4_base`, `final_*`)

Qué entrega: la forma y la longitud de la respuesta dependen de la sub-tarea de la pregunta (`sub_tarea` si viene; si no, se infiere del enunciado):
definición/elementos 1–2 oraciones (≤ 70 palabras), existencia normativa, requisitos 2–4 oraciones (≤ 110), precedente/sentido del fallo, problema jurídico (solo con sentencia nombrada; si no, caso),
ratio, antecedentes, conflicto, caso con hechos (respuesta directa primero, hasta 150 palabras) y **reproducción literal**: se copia el artículo (o el numeral que describe la pregunta) del pasaje recuperado, sin generar.
El sistema de texto libre permite usar el conocimiento propio cuando ningún pasaje trata el punto (sin inventar números de artículos).
Abiertas: sin relleno ("no hay jurisprudencia"), conclusión primero, ≈ 300 palabras.

| Corrida (30 semiabiertas + 5 abiertas, corpus base) | Proxy | Léxico | Mediana palabras semi (esperada 77,5) | s/semi · s/abierta |
|---|---|---|---|---|
| F0: prompt anterior, qwen3-8b | 0,348 | 0,167 | 63,5 | 10,8 · 30,6 |
| F1: plantillas por sub-tarea | 0,378 | 0,205 | 53 | 9,1 · 28,3 |
| F4b: F1 afinada, sistema anterior | 0,375 | 0,202 | — | 8,7 · 28,2 |
| **F4: F1 afinada + sistema libre (adoptada)** | **0,388** | **0,218** | 51 | 8,8 · 28,2 |
| F3: llama-3.1-8b con el prompt anterior (referencia) | 0,384 | 0,212 | 88 | 11,1 · 37,8 |
| F2: llama-3.1-8b con las plantillas | 0,376 | 0,207 | 43 | 8,1 · 28,7 |

* El proxy es 0,25·coseno e5-large (el mismo encoder del juez) + 0,75·F1 de palabras de contenido; reproduce el orden de los RAGAS ya medidos (llama 0,48–0,49 > qwen 0,43–0,46, con proxy 0,388 > 0,349). **No es RAGAS**: el juez real no se corrió (regla: solo con cerradas ≥ 0,905).
* Por sub-tarea (léxico, F0 → F1): reproducción literal 0,28 → 0,58 (el ítem 865 pasa de 0,28 a 0,90), existencia normativa 0,20 → 0,41, antecedentes 0,13 → 0,28; empeoran definición básica (0,14 → 0,11, n=6) y precedente (0,18 → 0,14, n=3), grupos muy pequeños.
* Se mantiene un único decoder (qwen3-8b) para los tres formatos: Llama no mejora con las plantillas y dos decodificadores arriesgan la regla de ≤ 8.000 M.
