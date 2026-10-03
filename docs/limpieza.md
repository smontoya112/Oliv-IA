# Limpieza del repositorio antes de congelar el corpus y el índice (3 oct 2026)

Criterio: se quita lo que ningún otro archivo del repo referencia y no forma parte del pipeline entregado, de los experimentos que se citan en la documentación ni de las plantillas de la organización.
Todo sigue en el historial de git. Para recuperar un archivo: `git checkout <commit anterior a la limpieza> -- <ruta>` (el commit anterior es el padre del commit «limpieza»).

## Se quitó

| Ruta | Por qué |
|---|---|
| `prueba.py`, `out_compare.txt`, `out_compare2.txt`, `out_ground_truth.txt` (raíz) | Pruebas sueltas de una persona (un `AutoModelForCausalLM` de ejemplo y volcados de comparación de 5 ítems de la muestra). Nadie las usa. |
| `requirements-descarga.txt` | Lo reemplaza `requirements.txt`, que incluye las dependencias de descarga. |
| `jobs/preparar_prueba_claude.sh` | Preparaba el clon de trabajo de la noche del 2 al 3 de octubre (enlaces a los datos del clon original); no sirve en un clon normal. |
| `jobs/recuperar_sin_area_sin_reranker.sh` | Ablación puntual cuyo resultado ya está en `data/recuperacion/ablaciones_sin_area_sin_reranker.json`; `jobs/recuperar.sh` corre las demás ablaciones. |
| `jobs/probar_decoder.sh` | Diagnóstico de la compilación de llama.cpp ya resuelta (`jobs/instalar_responder.sh` incluye su propia prueba). |
| `src/generacion/humo.py` | Prueba de humo del motor razonado; la cubren `tests/test_motor_razonado.py` y `tests/test_razonada.py` y la corrida de 6 preguntas. |
| `logs/` (150 archivos) | Salidas de jobs de Slurm: son de cada máquina. `logs/` queda en `.gitignore`; los resultados que importan están resumidos en `experimentos/claude/` y en los manifiestos de `data/`. |

## Se dejó (y por qué)

* **No modificables (organización):** `schema/submission.schema.json`, `scripts/evaluate.py`, `scripts/citations.py`, `scripts/common.py`, `scripts/requirements-evaluador.txt`.
* `scripts/baseline abstencion.py`, `scripts/extraer_normas_muestra.py`, `scripts/verificar_sentencias_cconst.py`, `scripts/normalizacion.py`, `scripts/datos.py`: herramientas de construcción y verificación del corpus (la última documenta por qué las sentencias de la Corte no se pueden bajar con una petición simple).
* `src/analisis/`, `src/generacion/exp_letras.py`, `src/generacion/bench.py`, `jobs/exp_claude.sh`, `jobs/ragas_*.{sh,py}`: reproducen los experimentos de `experimentos/claude/`.
* `jobs/scraper_proximidad.sh` y `src/descarga/proximidad.py`: construyen las «rondas de proximidad» del corpus ampliado, que el corpus entregado excluye pero cuyo origen documentan.
* `HANDOVER_2.md`, `HANDOVER_3.md`, `PROMPT_ITERACION.md`, `checklist.md`: notas internas del equipo; no se tocaron.
* `entregables/` y `Ejemplo de entrega/`: plantillas y ejemplo de la organización.
* `data/processed/`, `data/recuperacion/`: resultados de las fases 6–8 que citan los documentos y que usan algunos scripts como valores por defecto.
* `corpus 2.zip` y `md_corpus2.zip` (raíz, ignorados por git, 2 GB): respaldos locales del corpus ampliado; conviene sacarlos de la carpeta del repo (se sincronizan con OneDrive).

## Estructura resultante

Ver la tabla «Estructura del repositorio» del [README](../README.md). Lo que exige la organización y todavía falta o depende del equipo: `LICENSE`, `CORPUS.md`, `corpus_manifest.json` en la raíz,
el enlace al comprimido del corpus y del índice, el `submissions.jsonl` de las 992 preguntas, el video y las pruebas de la interfaz.
