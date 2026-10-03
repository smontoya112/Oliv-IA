# Rama `prueba-claude`: rediseño de cómo se generan las respuestas

Trabajo de la noche del 2 al 3 de octubre de 2026. Todo vive en la rama `prueba-claude` (commits locales, sin `git push`) y se corrió en
`~/hackatron/prueba_claude` de hypatia (clon con enlaces de solo lectura a `data/md`, `data/raw`, `data/index` y los entornos; el repo original
`~/hackatron/Oliv-IA2/Oliv-IA` no se tocó). Cada experimento está en `experimentos/claude/<etiqueta>/` y resumido en
[`experimentos/claude/REGISTRO.md`](../experimentos/claude/REGISTRO.md).

## 1. Qué se encontró (diagnóstico)

| # | Hallazgo | Evidencia |
|---|---|---|
| 1 | El decoder nunca razonaba: la gramática JSON obligaba a abrir con `{`, así que Qwen3 no abría su `<think>`, y la "razón por opción" iba después del veredicto. | `src/generacion/motor.py` (versión anterior) |
| 2 | La instrucción de sistema pedía "responde solo JSON" también cuando se quería una letra y la evidencia estaba diluida en un corpus 3,8 veces más grande. | letras_1: 9/15 → 11/15 solo con corpus base + sistema sin JSON |
| 3 | **El no determinismo de las corridas anteriores (mismo config: 0,47–0,67 en cerradas) venía de reutilizar el prefijo de KV entre ítems**: el mismo ítem se calculaba con otra forma de lote según lo que se hubiera respondido antes. Con `reset()` por ítem el resultado es idéntico entre corridas. | `base` y `base_repite` (letras_2) idénticos al decimal; lote vs `Responder` idénticos (final_*/determinismo.json) |
| 4 | La mejor corrida histórica (corpus 1) ganaba porque el corpus 2 añade ~3.000 documentos de rondas de proximidad y DIAN que son distractores en la muestra. | cuerpo@10 0,9625 vs 0,8875; hit_doc@10 0,90 vs 0,80 |
| 5 | En texto libre la longitud y la forma no dependían de la sub-tarea (`sample_50` la trae y el código no la usaba). | `src/generacion/subtarea.py` |

## 2. Arquitectura nueva (detrás de `estrategia: razonada` en `config/responder.json`; `actual` sigue disponible)

```
pregunta ─► Recuperador (índice base, sin cambios de código) ─► pasajes (10)
            ├─ cerradas ─► logits de la letra (4 rotaciones de las opciones, "Respuesta:" como ancla) ─► letra
            │              └► justificación breve de ESA letra (JSON con gramática) ─► citas verificadas (fase 8)
            ├─ semiabiertas ─► sub-tarea (dada o inferida) ─► plantilla de forma y longitud ─► JSON ─► fase 8
            │                  └ "reproducción literal": el texto del artículo se copia del pasaje (sin generar)
            └─ abiertas ─► prompt v2 (conclusión primero, sin relleno) ─► JSON ─► fase 8
```

* **Corpus base** (`data/index_base`, 467 documentos, 57.346 chunks): el corpus 1 reconstruido con
  `src.procesamiento.build --excluir-origen ronda_01 ronda_02 ronda_03 ronda_04` y `src.indice.build` (el índice completo `data/index` no se tocó).
  Lista de documentos: `experimentos/claude/corpus_base_docs.txt`; manifiesto filtrado: `corpus_base_manifest.json`; configuración del índice: `index_base_config.json`.
* **Cerradas**: `src/generacion/cerradas_razonar.py` (política `ens`). Sin razonamiento libre: ver §4. Costo ≈ 4 s (logits) + ≈ 15 s (justificación).
* **Texto libre**: `src/generacion/subtarea.py` (router + plantillas + extracción literal) y `SISTEMA_LIBRE` en `src/generacion/prompts.py`.
* **Determinismo**: `Motor.reiniciar()` antes de cada ítem; los tiempos NO van a la entrega.
* **Motor**: `Motor.pensar`, `Motor.probabilidades_letras`, `Motor.chatml` (solo Qwen; con otro decoder la estrategia razonada cae al camino actual).

## 3. Resultados sobre `sample_50` (evaluador oficial; ver REGISTRO.md)

| | Cerradas | Citas (índice) | Abstención | **Automático /50** | Proxy texto libre | s/pregunta (mezcla del test) |
|---|---|---|---|---|---|---|
| Estado de `main` esta noche (`antes_completo`: estrategia anterior, índice completo) | 8/15 (0,533) | 0,7959 | 0,7442 | 34,03 | 0,3525 | 24,6 |
| Estrategia anterior sobre el corpus base (`antes_base`) | 7/15 (0,467) | 0,8571 | 0,7674 | 34,14 | 0,3500 | 24,3 |
| **Esta configuración (`final_2`)** | **11/15 (0,733)** | **0,8571** | **0,8605** | **40,41** | **0,3879** | **18,0** |
| Referencia: mejor corrida histórica (corpus 1, HANDOVER_3 §6) | 10/15 | 0,8367 | 0,8372 | 38,43 | — | ≈ 25 |

* Cerradas +4 ítems sobre `antes_base` con el MISMO corpus: la ganancia viene de la forma de decidir la letra, no solo del corpus.
* Citas (+0,06) y abstención calibrada vienen del corpus base; el proxy de texto libre (+0,035) de las plantillas por sub-tarea.
* Dos corridas completas independientes (`final_1`, `final_2`) dan las mismas 50 líneas; 25/25 ítems regenerados con `Responder` (en vivo) coinciden con el lote.
* Detalle por experimento: `experimentos/claude/REGISTRO.md`; resumen de la configuración adoptada: `experimentos/claude/final_5/RESUMEN.md`.

### 3b. RAGAS real y las abiertas (segunda ronda de la noche)

Con permiso expreso de Samuel se corrió RAGAS (juez `z-ai/glm-5.3-flash`, **3 corridas, el tope**) y se implementaron las tres ideas para abiertas
(`src/generacion/abiertas.py`): plantilla por tipo de caso, expansión de la recuperación y revisión. Resultado:

| Corrida (misma `sample_50`) | RAGAS correctness (referencia 0,451) | Abiertas | Citas | **Total /80** |
|---|---|---|---|---|
| #1 `final_3`: sin cambios en abiertas | **0,4912** | 0,368 | 0,857 | 55,15 |
| #2 `final_4`: expansión pura | 0,4783 | 0,320 | 0,878 | 55,41 |
| **#3 `final_5`: expansión fusionada por RRF (adoptada)** | **0,4923** | 0,376 | **0,898** | **56,24** |

* La expansión de la recuperación (el decoder deduce el problema jurídico y consultas **solo del enunciado**; el reranker puntúa contra eso y no contra el relato) arregla el ítem 247
  (concluye "acción popular", Ley 472: RAGAS 0,217 → 0,481) y sube el recall de citas 0,857 → 0,898; pero 4 de las 5 abiertas empeoran un poco con la lista expandida sola, por eso se fusiona (RRF) con la original.
* **La diferencia en RAGAS entre #1 y #3 es un empate** (ruido del juez ≈ ±0,045 por ítem sobre el mismo texto). La mejora medible es la de citas (+0,8 pt) y el caso 247.
* **Plantilla por tipo de caso: peor** (proxy 0,314 la larga, 0,323 la corta, contra 0,332). **Revisión: sin efecto** y 2× más lenta. Quedan implementadas pero apagadas (`"abiertas": ["expansion"]`).
* Los RAGAS de antes de esta rama (0,43–0,49) y los de esta (0,478–0,492) están por encima de la referencia 0,451; la parte nueva no es una ganancia grande en RAGAS, sino en cerradas (+3–4 ítems) y citas.

## 4. Lo que se probó y se descartó (con razón)

* **Pensar antes de responder** (`<think>`, 1.200 tokens): 9/15 sobre el corpus actual y 9/15 (10/15 con respaldo en logits) sobre el base, frente a 11/15 de los logits solos;
  3–12 veces más lento (45–50 s por cerrada) y 4 de 15 razonamientos se cortan por el presupuesto. Arregla el ítem 528 (aritmética de cuantía) y rompe el 671.
* **Evidencia sola** (letra de la opción cuyos pasajes puntúan más en el reranker): 4/15, es el azar.
* **Promediar dos contextos** (base y completo): misma exactitud con NLL menor, el doble de tiempo.
* **Menos pasajes (3, 5, 6) o solo los de cada opción**: peor (9–10/15 y 6/15); **más pasajes (12, 14)**: igual o algo peor que 10.
* **Llama-3.1-8b para texto libre**: el proxy empata con qwen (0,376 vs 0,378 con las mismas plantillas) y usar dos decodificadores arriesga la regla de ≤ 8.000 M parámetros: se mantiene qwen3-8b para todo.

## 5. Cómo correrlo el sábado

La configuración adoptada ya está en `config/responder.json` (`modelo qwen3-8b`, `indice data/index_base`, `estrategia razonada`). Cada máquina necesita
`data/index_base/` y `data/processed_base/chunks.parquet` además de lo de siempre; en hypatia están en `~/hackatron/prueba_claude/data/`.
Para llevarlos a otra máquina sin usar el token de Hugging Face:

```bash
tar czf indice_base.tar.gz data/index_base data/processed_base/chunks.parquet
scp indice_base.tar.gz <usuario>@<maquina>:<repo>/ && ssh <usuario>@<maquina> "cd <repo> && tar xzf indice_base.tar.gz"
```

### 5.1 Corpus enriquecido con las normas que nombran las 992 preguntas (sábado 3 oct)

`jobs/enriquecer_corpus.sh data/test_992.jsonl` (otro clon, rama `corpus3.0`) extrajo de los enunciados las normas nombradas: 404 preguntas con mención normativa,
142 normas distintas, 99 ya en el corpus, 41 por descargar y 2 a buscar a mano (`data/enriquecimiento/test_992/`). Luego, en `~/hackatron/prueba_claude`:

| Paso | Job | Resultado |
|---|---|---|
| Scraper con `fuentes.json` | `jobs/descargar_fuentes.sh` (nuevo; reanudable; usa `src.descarga.run --solo <ids del json>`) | 34 sentencias de la Corte Constitucional; las 7 leyes y decretos (Senado) dieron 404 |
| Scraper con `fuentes_alternativas.json` | `jobs/descargar_fuentes.sh data/enriquecimiento/test_992/fuentes_alternativas.json` | 4 de las 7 desde gestores normativos públicos (CRA y Colpensiones): `ley_54_1990`, `ley_29_1982`, `ley_45_1990`, `decreto_2663_1950` |
| Chunking del corpus base | `CORPUS=base sbatch jobs/chunking.sh` → `data/processed_base/` | 504 documentos y 62.824 chunks (antes 467 y 57.346: las normas nuevas llevan `origen: preguntas_test_992`, que no se excluye) |
| Índice del corpus base | `CORPUS=base sbatch jobs/indice.sh` → `data/index_base/` | `n_chunks` 62.824; sin regresión en `sample_50` (cuerpo@10 0,9625, hit_doc@10 0,90) y 43 de 44 preguntas que nombran una norma nueva la recuperan en el top-10: `experimentos/claude/corpus_enriquecido/RESUMEN.md` |

Manifest: 3.523 documentos `ok` (eran 3.485 antes del enriquecimiento). **Siguen sin texto**: `sentencia_su-279_2019` (la Corte la sirve como página dinámica: 0 chunks), `ley_2568_2021`, `decreto_3030_2022` y `decreto_4302_2008` (404 en el Senado y sin copia encontrada; 1 pregunta cada una),
y a mano: Resolución 368 de 2014 del Ministerio de Ambiente (23 preguntas, ids 721–752, pero preguntan teoría general del acto administrativo, no el contenido de la resolución) y Sentencia SL-3871 de 2021 (Corte Suprema, 1 pregunta).
El índice anterior quedó como respaldo en `data/index_base_prev/` y `data/processed_base_prev/`.

Los datos pesados (`data/md`, `data/raw`, los índices) no van a git: las copias están en `~/hackatron/prueba_claude/data/` y el clon `Oliv-IA2/Oliv-IA` no se modificó (el clon de trabajo tiene copias propias de `md` y `raw`).

### 5.2 Corrida

`jobs/corrida.sh` corre UNA parte y valida el índice y los chunks de `config/responder.json`; `jobs/lanzar_corrida.sh` lanza todas las partes en paralelo:

```bash
mkdir -p logs                                          # una sola vez
cp <archivo recibido> data/test_992.jsonl              # el MISMO archivo en todas las máquinas
bash jobs/lanzar_corrida.sh                            # 3 partes en paralelo + un job que las une (data/lote/test_992/submissions.jsonl)
PARTES=2 bash jobs/lanzar_corrida.sh                   # 2 partes (si solo hay 2 GPU libres)
ESPERAR=<id del job de indice> bash jobs/lanzar_corrida.sh   # las partes arrancan al terminar el índice
bash jobs/corrida.sh 3                                 # una parte en otro computador con GPU (sin Slurm)
python -m src.responder --id N --comparar data/lote/test_992/submissions.jsonl     # verificación en vivo
```

* Divide una sola vez (`src.lote dividir`, reparto estratificado por formato) para que los jobs no se pisen; manda `corrida_p1..pN` y `unir_corrida` (`--dependency=afterok`, se cancela sola si una parte falla).
* **La cola `gpu` de hypatia da como máximo 2 GPU por usuario a la vez** (`QOS gpu: gres/gpu=2`; los jobs de otros usuarios no cuentan, los `servir` propios sí). Con 3 partes y 2 GPU libres la tercera espera a que acabe una y la corrida dura ~2 veces más: con 2 GPU, `PARTES=2` (~2,7 h).
  Tiempo por parte: ≈ 19 s por pregunta (cerradas ~23 s, semiabiertas ~14 s, abiertas ~53 s) → ~1,8 h con 3 partes, ~2,7 h con 2.
* Si una parte se cae o se acaba el tiempo, relanzar solo esa (`sbatch --job-name=corrida_pN jobs/corrida.sh N`): sigue desde el checkpoint. La unión manual está al final de la salida del lanzador.
* Los `servir` de la verificación en vivo del clon `Congelacion` usan el índice congelado del corpus 1, no el enriquecido: si se entrega el índice enriquecido hay que servir con él (`config/responder.json` de este clon).

Para volver a la estrategia anterior sin tocar código: `OLIVIA_ESTRATEGIA=actual OLIVIA_INDICE=data/index`.

## 6. Limitaciones (dichas con claridad)

* Son **15 cerradas** y 35 de texto libre: 1 ítem = 0,067 en cerradas. 11/15 contra 9–10/15 de antes es una mejora real en dirección (la medimos también por permutación: 0,73 vs 0,61) pero no concluyente.
  El umbral de 0,905 exigiría 14/15; con los ítems 128, 308, 528 y 647 fallando (conocimiento y lectura, y uno mal formado) **no se alcanzó**.
* **RAGAS**: al principio no se corrió (la regla era hacerlo solo con cerradas ≥ 0,905, y no se llegó). Después Samuel autorizó correrlo: se usaron las 3 corridas del tope (§3b). Para iterar sin créditos se usó un **proxy local**
  (`src/analisis/proxy_texto.py`: 0,25·coseno e5-large + 0,75·F1 léxico); ordena igual que los RAGAS de antes (llama > qwen) pero **no coincidió** con el juez en la expansión pura (proxy +0,011, RAGAS −0,048 en abiertas): no es el juez.
* **Las abiertas son 5 ítems**: cualquier conclusión sobre ellas es débil; el juez cambia el puntaje de un mismo texto en ≈ 0,045 de media.
* El corpus base cubre ~96 % del banco según `seed_targets`; el ~4 % restante (normas fuera del corpus 1) pierde la cobertura que daba el corpus 2. La muestra no tiene ítems fuera del corpus 1, así que no se puede medir.
* Tres pruebas preexistentes fallan igual en `main` (`test_corpus_manifest` ×2, `test_recuperacion::test_tope_por_norma...`); no son de esta rama.
* La corrida del sábado y la verificación en vivo deben hacerse en la misma máquina/GPU que generó cada parte.

## 7. Seguridad

Ni `HF_TOKEN` ni la contraseña de hypatia se usaron ni se enviaron a ningún servidor: los jobs hacen `unset HF_TOKEN`, los GGUF y modelos públicos se bajan sin token (ya estaban en la caché) y el acceso a hypatia fue por una llave SSH
creada para esto (`~/.ssh/id_ed25519_hypatia`, sin passphrase; conviene borrarla de `authorized_keys` al terminar).
La única llave que salió del servidor es `OPENROUTER_API_KEY`, y solo hacia OpenRouter, en las 3 corridas de RAGAS autorizadas: `jobs/ragas_claude.sh` la lee de `scripts/.env` (un archivo con esa única línea, copiada en el servidor
desde el `.env` original sin imprimirla, ignorado por git), con `HF_HUB_OFFLINE=1` y sin `HF_TOKEN`.

## 8. Reproducir los experimentos

```bash
# en una asignación de GPU (srun --jobid=<ID> --overlap bash -l -c "cd ~/hackatron/prueba_claude && ...")
bash jobs/exp_claude.sh corpus_base                       # índice base
bash jobs/exp_claude.sh recuperar base data/index_base    # tabla de recuperación (cuerpo@10, ...)
bash jobs/exp_claude.sh contexto base
python -m src.generacion.exp_letras --contextos base=data/exp/contexto_base.json --salida experimentos/claude/letras_X/metricas.json
bash jobs/exp_claude.sh bench <etiqueta> qwen3-8b razonada base multiple_choice
bash jobs/exp_claude.sh lote <nombre>                     # camino real (src.lote) con config/responder.json
bash jobs/exp_claude.sh determinismo <nombre> --ids 51 79 ...
python -m src.analisis.registro_claude                    # REGISTRO.md
```
