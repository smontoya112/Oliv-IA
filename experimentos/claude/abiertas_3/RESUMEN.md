# Abiertas: las tres propuestas, implementadas y comparadas (`abiertas_1`, `abiertas_2`, `abiertas_3`, `final_4`, `final_5`, `ragas_*`)

Código: `src/generacion/abiertas.py`, `Recuperador.recuperar_expandido`, `responder.recuperar_item`, `src/analisis/exp_abiertas.py` (5 abiertas, proxy local) y RAGAS real con `jobs/ragas_claude.sh`
(puntaje por ítem en `ragas_*/ragas_items.json`). Activación: `config/responder.json` → `"abiertas": [...]` (o `OLIVIA_ABIERTAS`).

| Propuesta | Qué hace | Proxy (5 abiertas; A0 = 0,332) | Veredicto |
|---|---|---|---|
| 1. Plantilla por tipo de caso | Numera las preguntas del caso y pide contestar cada una (acción procedente / responsable / viabilidad); la larga (6–9 oraciones) | 0,314 (410 palabras) | **Descartada**: más larga y peor |
| 1b. Plantilla corta | analisis ≤ 200 palabras | 0,323 | Descartada: no mejora la línea base |
| 2. Expansión de la recuperación | El decoder deduce el problema jurídico y consultas del caso; reranker contra problema + preguntas | pura 0,343 · fusionada (RRF) 0,337 | **Adoptada fusionada**; la pura descartada por RAGAS |
| 3. Segunda pasada de revisión | Quita lo no respaldado por los pasajes | 0,340 (igual que sin ella) con 2× tiempo (101–123 s) | **Descartada**: no cambia el texto de forma útil |

RAGAS real (35 ítems de texto libre): sin expansión 0,4912 → expansión pura 0,4783 → **expansión fusionada 0,4923**; abiertas 0,368 → 0,320 → 0,376. Detalle e interpretación (ruido del juez ±0,045 por ítem): `../final_5/RESUMEN.md`.

Nota de trazabilidad: `abiertas_1/NOTA.md` explica que los archivos de A1/A2 (plantilla larga) fueron sobrescritos por un proceso duplicado; sus valores salen de la consola de la corrida original.
