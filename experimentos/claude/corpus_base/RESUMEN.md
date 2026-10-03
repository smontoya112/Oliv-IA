# Corpus base (`data/index_base`) — qué es y por qué se adopta

El corpus 1 reconstruido como índice **separado** (el índice completo `data/index` no se tocó):

```
python -m src.procesamiento.build --salida data/processed_base --excluir-origen ronda_01 ronda_02 ronda_03 ronda_04
python -m src.indice.build --chunks data/processed_base/chunks.parquet --salida data/index_base
```

* 467 documentos (todos con `origen: null` en `data/corpus_manifest.json`: la lista objetivo y lo descargado desde las preguntas, sin las rondas de proximidad ni la DIAN masiva), 57.346 chunks.
* Archivos: `../corpus_base_docs.txt` (doc_id y n.º de chunks), `../corpus_base_manifest.json` (manifiesto filtrado), `../index_base_config.json` (versiones, hashes, encoder).

## Recuperación sobre `sample_50` (40 evaluables; `python -m src.recuperacion.evaluar`)

| | cuerpo@10 (lo que puntúa) | artículo@10 | hit_doc@10 | cobertura de opciones @8 |
|---|---|---|---|---|
| Índice completo (220.903 chunks, 3.480 docs) | 0,8875 | 0,6053 | 0,80 | 0,9583 |
| **Índice base (57.346 chunks, 467 docs)** | **0,9625** | 0,5982 | **0,90** | 0,9167 |

Regla de decisión (HANDOVER_3 / PROMPT_ITERACION): manda cuerpo@10 y no bajar artículo@10 de forma material. Sube 3 ítems de 40 en cuerpo@10 y 4 en `hit_doc@10`; artículo@10 baja 0,007.

## Qué cambia aguas abajo (mismo arnés, estrategia anterior)

Citas 0,7959 → 0,8571 y abstención calibrada 0,744 → 0,767 (`antes_completo` vs `antes_base`).

## Costo / límites

* Se pierde la cobertura del corpus completo para normas fuera de `seed_targets.json` (~4 % del banco según el HANDOVER_2). La muestra no tiene ítems fuera del corpus 1, así que esa pérdida **no se puede medir**.
  Alternativa si se quiere cubrirla: cascada al índice completo cuando `normas_nombradas_fuera_del_corpus > 0` (no implementada).
* Para usarlo: `config/responder.json` → `"indice": "data/index_base"`; cada máquina necesita `data/index_base/` y `data/processed_base/chunks.parquet` (ver `docs/prueba_claude.md` §5).
