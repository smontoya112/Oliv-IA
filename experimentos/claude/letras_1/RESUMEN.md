# Cerradas: letra por probabilidades de permutaciones (`letras_1`…`letras_4`, `E1*`, `E2_r1`)

Qué entrega: la letra de las preguntas cerradas se decide leyendo las probabilidades del PRIMER token tras `Respuesta:` (bloque de pensamiento vacío),
promediadas sobre 4 rotaciones cíclicas de las opciones (quita el sesgo de posición; con opciones compuestas "todas/ninguna/A y B" no se permuta).
Después se genera una justificación breve de esa letra (de ahí salen las citas) y el descarte de las demás opciones.

| Variante (15 cerradas) | Aciertos | Exactitud por permutación (51) | s/pregunta |
|---|---|---|---|
| JSON de un tiro (estrategia anterior), índice completo | 8/15 | — | 22 |
| logits, sistema con regla "solo JSON", índice completo | 9/15 | 0,608 | 4,7 |
| logits, sistema sin esa regla, índice completo | 9/15 | 0,608 | 4,7 |
| **logits, sistema sin esa regla, corpus base (adoptada)** | **11/15** | **0,726** | **4,3** |
| pensar (`<think>` 1.200 tokens) + JSON, corpus base | 9/15 (10/15 con respaldo en logits) | — | 50 |
| logits con 3 / 5 / 6 pasajes | 10 / 9 / 9 | 0,63 / 0,61 / 0,61 | 1–2 |
| logits con 12 / 14 pasajes | 11 / 11 | 0,706 / 0,706 | 5,3 / 6,5 |
| logits sobre dos contextos (base + completo) | 11/15 | 0,686 (NLL 1,24 vs 1,77) | 9 |
| solo pasajes por opción | 6/15 | 0,451 | 2,2 |

* Es determinista: dos corridas dan exactamente las mismas probabilidades (`base` = `base_repite`).
* Con la justificación el costo total por cerrada es ≈ 20 s (4 s de logits + ≈ 15 s de justificación).
* Fallan: 128 (el modelo está seguro de B con p=0,9997), 308, 528 (lectura/cálculo) y 647 (ítem mal formado).
* La política `cascada` (pensar solo si P < 0,9) y `voto` están implementadas (`cerradas_razonar.decidir`) pero no ganan nada en la muestra.
