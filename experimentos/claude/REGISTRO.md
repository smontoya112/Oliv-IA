# Registro de experimentos — rama `prueba-claude`

Generado por `python -m src.analisis.registro_claude` desde `catalogo.json` y los `metricas.json`.
Cerradas: aciertos sobre las 15 de `sample_50` (un ítem = 0,067; ruido de ±1-2). Texto libre: proxy local de RAGAS 
(0,25·coseno e5 + 0,75·F1 léxico; ordena variantes, no sustituye al juez). RAGAS real: ver los RESUMEN.md.

| Etiqueta | Modelo | Estrategia / política | Contexto | Cerradas | Proxy | Citas | s/cerr · semi · abierta | Decisión |
|---|---|---|---|---|---|---|---|---|
| letras_1 | qwen3-8b | razonada (solo logits, 4 permutaciones)  | actual vs base | 11/15 (perm. 0.7255) |  |  | 4.34 ·  ·  | **adoptar (base + sistema_letra)** |
| letras_2 | qwen3-8b | razonada (solo logits)  | base | 11/15 (perm. 0.7255) |  |  | 4.31 ·  ·  | **adoptar** |
| letras_3 | qwen3-8b | razonada (solo logits)  | base / mixto / solo_opciones | 11/15 (perm. 0.6863) |  |  | 8.95 ·  ·  | **descartar** |
| letras_4 | qwen3-8b | razonada (solo logits)  | base / base14 | 11/15 (perm. 0.7059) |  |  | 6.52 ·  ·  | **descartar** |
| E0_r1 | qwen3-8b | actual  | actual | 8/15 |  |  | 22.23 ·  ·  | **línea base** |
| E0b_r1 | qwen3-8b | actual  | base | 7/15 |  |  | 21.76 ·  ·  | **inconcluso** |
| E1_r1 | qwen3-8b | razonada razonada | actual | 9/15 |  |  | 44.6 ·  ·  | **descartar como política por defecto** |
| E1b_r1 | qwen3-8b | razonada razonada (pensar) con ens como señal | base | 10/15 |  |  | 50.09 ·  ·  | **descartar** |
| E2_r1 | qwen3-8b | razonada ens (logits de 4 permutaciones + justificación generada aparte) | base | 11/15 |  |  | 23.42 ·  ·  | **adoptar** |
| F0_base | qwen3-8b | actual  | base |  | 0.3481 |  |  · 10.75 · 30.56 | **línea base** |
| F1_base | qwen3-8b | razonada (plantillas por sub-tarea, v2)  | base |  | 0.378 |  |  · 9.14 · 28.26 | **adoptar** |
| F2_base | llama-3.1-8b | razonada (v2)  | base |  | 0.3755 |  |  · 8.08 · 28.65 | **descartar** |
| F3_base | llama-3.1-8b | actual  | base |  | 0.3837 |  |  · 11.11 · 37.82 | **referencia** |
| F4b_base | qwen3-8b | razonada (plantillas v2 afinadas, sistema anterior)  | base |  | 0.3751 |  |  · 8.73 · 28.72 | **descartar** |
| F4_base | qwen3-8b | razonada (plantillas v2 afinadas + sistema libre)  | base |  | 0.3883 |  |  · 8.77 · 28.17 | **adoptar** |
| antes_completo | qwen3-8b | actual  | actual | 8/15 | 0.3525 | 0.7959 | 34.73 · 16.78 · 53.63 | **línea base** |
| antes_base | qwen3-8b | actual  | base | 7/15 | 0.35 | 0.8571 | 34.97 · 16.67 · 49.63 | **línea base** |
| final_1 | qwen3-8b | razonada (ens en cerradas + plantillas por sub-tarea)  | base | 11/15 | 0.3879 | 0.8571 | 22.26 · 13.04 · 44.71 | **adoptar** |
| final_2 | qwen3-8b | razonada (ens en cerradas + plantillas por sub-tarea)  | base | 11/15 | 0.3879 | 0.8571 | 22.36 · 13.09 · 44.42 | **adoptar** |
| final_3 | qwen3-8b | razonada (ens en cerradas + plantillas por sub-tarea)  | base | 11/15 | 0.3879 | 0.8571 | 23.09 · 13.46 · 46.74 | **adoptar** |

## Hipótesis y razones

- **letras_1** — Las probabilidades de letra promediadas sobre permutaciones, con un sistema sin la regla de solo-JSON y sobre el corpus base, superan al JSON de un tiro. → adoptar (base + sistema_letra): 11/15 con base vs 9/15 con el índice actual; exactitud por permutación 0,73 vs 0,61; 4,3 s por pregunta; 8-10 pasajes mejor que 3-6.
- **letras_2** — El resultado es determinista y no cambia al subir el presupuesto a 10 pasajes. → adoptar: base y base_repite idénticos al decimal (determinismo); 10 pasajes = lo que ya cabía.
- **letras_3** — Promediar logits sobre dos contextos (base y completo) o usar solo los pasajes por opción. → descartar: mixto 11/15 con NLL menor (1,24 vs 1,77) pero exactitud por permutación 0,69 vs 0,73 y el doble de tiempo; solo_opciones 6/15 (la evidencia general importa).
- **letras_4** — Más pasajes en el prompt (12 o 14, hasta 6.500 tokens) siguen mejorando como pasó de 3 a 10. → descartar: 11/15 igual; exactitud por permutación 0,706 vs 0,726 con 10; más lento (5-6,5 s).
- **E0_r1** — Línea base con reset de contexto por ítem. → línea base: 8/15; 22 s por cerrada (el reset cuesta prefill del few-shot).
- **E0b_r1** — El corpus base mejora también la estrategia actual. → inconcluso: 7/15: dentro del ruido; la mejora aparece con logits y permutaciones, no con el JSON de un tiro.
- **E1_r1** — Pensar (<think>) antes de comprometer la letra mejora las cerradas. → descartar como política por defecto: 9/15 igual que solo logits (9/15) y 3 veces más lento (45 s); arregla 528 pero rompe 671.
- **E1b_r1** — Con el corpus base, pensar (<think>, 1.200 tokens) antes de comprometer la letra supera a los logits. → descartar: razonada 9/15 (10/15 con respaldo en logits) frente a 11/15 de los logits solos; 50 s por cerrada (12 veces más); 4/15 pensamientos cortados por el presupuesto.
- **E2_r1** — La política ens con una justificación posterior de la letra ya decidida mantiene las citas y reduce el tiempo. → adoptar: 11/15 (0,733) frente a 7-8/15 de la estrategia anterior; 23 s por cerrada con justificación larga (se acortó a 2 oraciones en la versión final).
- **F0_base** — Línea base de texto libre con el corpus base. → línea base: proxy 0,348.
- **F1_base** — Forma y longitud por sub-tarea (+ extracción literal) suben la parte factual. → adoptar: proxy 0,378 vs 0,348 (+0,030); léxico +23%; reproducción literal 0,28→0,58.
- **F2_base** — Llama con las plantillas v2. → descartar: proxy 0,3755 ≈ qwen v2; usar dos decodificadores arriesga la regla de ≤8.000 M y no mejora.
- **F3_base** — Llama con el prompt actual. → referencia: proxy 0,3837: su longitud natural (88 palabras) se acerca a la esperada (77,5); explica por qué ganaba en RAGAS.
- **F4b_base** — Aislar el efecto del sistema libre. → descartar: proxy 0,375 < 0,388 de F4: el sistema libre aporta ~+0,013 (poco, pero consistente en semi y abiertas).
- **F4_base** — Corregir 'problema jurídico' sin sentencia → caso, 'existencia' sin forzar Sí/No y permitir conocimiento propio cuando ningún pasaje trata el punto. → adoptar: proxy 0,388: el mejor, con un solo decodificador (qwen3-8b); +0,040 sobre la línea base de texto libre (0,348).
- **antes_completo** — Estado de main (estrategia anterior, índice completo) en el mismo arnés, con determinismo corregido. → línea base: 8/15, citas 0,796, total automático 34,0: reproduce los números del HANDOVER_3.
- **antes_base** — Estrategia anterior sobre el corpus base, mismo arnés. → línea base: 7/15: el corpus base ayuda a las citas (0,857) pero no a la estrategia de un JSON por pregunta.
- **final_1** — Configuración adoptada, camino real src.lote. → adoptar: 11/15, citas 0,857, abstención 0,86, total automático 40,4/50, proxy 0,388, 18 s por pregunta; verificación en vivo idéntica.
- **final_2** — Repetición independiente de final_1 con el código final. → adoptar: idéntica a final_1 línea por línea (salvo latencias) y 25/25 ítems idénticos entre Responder (en vivo) y lote.
- **final_3** — Tercera corrida independiente con el commit final (incluye el respaldo ante excepciones). → adoptar: idéntica línea por línea a final_2 (salvo latencias).
