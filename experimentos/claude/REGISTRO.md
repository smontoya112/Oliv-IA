# Registro de experimentos — rama `prueba-claude`

Generado por `python -m src.analisis.registro_claude` desde `catalogo.json` y los `metricas.json`.
Cerradas: aciertos sobre las 15 de `sample_50` (un ítem = 0,067; ruido de ±1-2). Texto libre: proxy local de RAGAS 
(0,25·coseno e5 + 0,75·F1 léxico; ordena variantes, no sustituye al juez). RAGAS real: ver los RESUMEN.md.

| Etiqueta | Modelo | Estrategia / política | Contexto | Cerradas | Proxy | Citas | s/cerr · semi · abierta | Decisión |
|---|---|---|---|---|---|---|---|---|
| letras_1 | qwen3-8b | razonada (solo logits, 4 permutaciones)  | actual vs base | 11/15 (perm. 0.7255) |  |  | 4.34 ·  ·  | **adoptar (base + sistema_letra)** |
| letras_2 | qwen3-8b | razonada (solo logits)  | base | 11/15 (perm. 0.7255) |  |  | 4.31 ·  ·  | **adoptar** |
| E0_r1 | qwen3-8b | actual  | actual | 8/15 | 0.0 | 0.2449 | 22.23 ·  ·  | **línea base** |
| E0b_r1 | qwen3-8b | actual  | base | 7/15 | 0.0 | 0.2449 | 21.76 ·  ·  | **inconcluso** |
| E1_r1 | qwen3-8b | razonada razonada | actual | 9/15 | 0.0 | 0.2449 | 44.6 ·  ·  | **descartar como política por defecto** |
| F0_base | qwen3-8b | actual  | base | 0/15 | 0.3481 | 0.6122 |  · 10.75 · 30.56 | **línea base** |
| F1_base | qwen3-8b | razonada (plantillas por sub-tarea, v2)  | base | 0/15 | 0.378 | 0.5918 |  · 9.14 · 28.26 | **adoptar** |
| F2_base | llama-3.1-8b | razonada (v2)  | base | 0/15 | 0.3755 | 0.5918 |  · 8.08 · 28.65 | **descartar** |
| F3_base | llama-3.1-8b | actual  | base | 0/15 | 0.3837 | 0.6122 |  · 11.11 · 37.82 | **referencia** |

## Hipótesis y razones

- **letras_1** — Las probabilidades de letra promediadas sobre permutaciones, con un sistema sin la regla de solo-JSON y sobre el corpus base, superan al JSON de un tiro. → adoptar (base + sistema_letra): 11/15 con base vs 9/15 con el índice actual; exactitud por permutación 0,73 vs 0,61; 4,3 s por pregunta; 8-10 pasajes mejor que 3-6.
- **letras_2** — El resultado es determinista y no cambia al subir el presupuesto a 10 pasajes. → adoptar: base y base_repite idénticos al decimal (determinismo); 10 pasajes = lo que ya cabía.
- **E0_r1** — Línea base con reset de contexto por ítem. → línea base: 8/15; 22 s por cerrada (el reset cuesta prefill del few-shot).
- **E0b_r1** — El corpus base mejora también la estrategia actual. → inconcluso: 7/15: dentro del ruido; la mejora aparece con logits y permutaciones, no con el JSON de un tiro.
- **E1_r1** — Pensar (<think>) antes de comprometer la letra mejora las cerradas. → descartar como política por defecto: 9/15 igual que solo logits (9/15) y 3 veces más lento (45 s); arregla 528 pero rompe 671.
- **F0_base** — Línea base de texto libre con el corpus base. → línea base: proxy 0,348.
- **F1_base** — Forma y longitud por sub-tarea (+ extracción literal) suben la parte factual. → adoptar: proxy 0,378 vs 0,348 (+0,030); léxico +23%; reproducción literal 0,28→0,58.
- **F2_base** — Llama con las plantillas v2. → descartar: proxy 0,3755 ≈ qwen v2; usar dos decodificadores arriesga la regla de ≤8.000 M y no mejora.
- **F3_base** — Llama con el prompt actual. → referencia: proxy 0,3837: su longitud natural (88 palabras) se acerca a la esperada (77,5); explica por qué ganaba en RAGAS.
