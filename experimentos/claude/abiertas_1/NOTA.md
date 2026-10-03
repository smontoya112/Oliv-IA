# abiertas_1 — qué quedó y qué no

La corrida original (plantilla LARGA: analisis de 6 a 9 oraciones, un párrafo por pregunta) midió 5 variantes sobre las 5 abiertas de `sample_50`
(proxy = 0,25·coseno e5 + 0,75·F1 léxico). Valores impresos por esa corrida:

| Variante | Piezas | Proxy | Léxico | Palabras | s/ítem | Cuerpo de ref. en top-10 | Citas acertadas |
|---|---|---|---|---|---|---|---|
| A0_actual | (ninguna) | 0,3323 | 0,1438 | 302,4 | 46,1 | 5/6 | 4/6 |
| A1_plantilla (larga) | plantilla | 0,3137 | 0,1236 | 410,6 | 61,6 | 5/6 | 5/6 |
| A2_plantilla_expansion (larga) | plantilla + expansión pura | 0,3406 | 0,1551 | 394,8 | 69,3 | 6/6 | 5/6 |
| A3_completa (larga) | plantilla + expansión pura + revisión | 0,3390 | 0,1528 | 362,2 | 122,7 | 6/6 | 5/6 |
| A4_expansion | expansión pura | 0,3431 | 0,1586 | 297,2 | 56,4 | 6/6 | 5/6 |

**Honestidad sobre los archivos:** un proceso duplicado (relanzado por un reintento de conexión SSH) volvió a correr A0, A1 y A2 con el código
YA modificado (plantilla corta) y sobrescribió `ab_A1_plantilla.jsonl`, `ab_A2_plantilla_expansion.jsonl` y este `metricas.json`. Por eso:
* `metricas.json` conserva solo A0 (idéntico a la corrida original) y, de A3/A4, sus líneas `ab_A3_completa.jsonl` / `ab_A4_expansion.jsonl` siguen siendo las originales;
* los valores de A1 y A2 (plantilla larga) de la tabla vienen de la salida de consola de la corrida original y **sus archivos ya no existen**;
* las filas A1/A2 que había en `metricas.json` eran duplicados de B1/B2 (plantilla corta) y se quitaron.
