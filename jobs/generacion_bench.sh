#!/usr/bin/env bash
#SBATCH --job-name=generacion_bench
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err
#SBATCH --mail-type=ALL
#SBATCH --mail-user=s.montoya112@uniandes.edu.co
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --gres=gpu:1
#SBATCH --partition=gpu
#SBATCH --time=12:00:00
#
# Fase 7 (7.1 y 7.2): compara los decoders sobre las 50 muestras con un contexto de PRUEBA
# (no depende de los índices de la fase 5/6): tiempo por formato, validez del JSON y
# exactitud en cerradas. Requiere data/processed/chunks.parquet (jobs/chunking.sh).
#
#     mkdir -p logs            # una sola vez
#     sbatch jobs/generacion_bench.sh                              # los 3 modelos
#     sbatch jobs/generacion_bench.sh qwen3-8b                     # solo uno (o varios)
#     CONTEXTO=bm25 sbatch jobs/generacion_bench.sh qwen3-8b       # contexto BM25 en vez del oráculo
#
# vLLM se instala una vez en un entorno aparte (.venv-gen) para no chocar con el torch del
# proyecto. Los modelos se bajan de Hugging Face la primera vez (el nodo necesita internet o
# una caché HF_HOME ya llena). Llama-3.1 es "gated": requiere haber aceptado la licencia y
# tener HF_TOKEN exportado.
#
# Salidas: data/processed/bench_generacion.csv (una fila por modelo y formato),
# data/processed/bench_generacion/<modelo>.jsonl (predicciones) y los logs del job.
source "$SLURM_SUBMIT_DIR/jobs/_comun.sh"
preparar_entorno

MODELOS=("$@"); [[ ${#MODELOS[@]} -eq 0 ]] && MODELOS=(qwen3-8b llama-3.1-8b salamandra-7b)
CONTEXTO="${CONTEXTO:-oraculo}"
CTX_JSON="data/processed/contexto_${CONTEXTO}.json"

paso "1/4 contexto de prueba ($CONTEXTO) -> $CTX_JSON"
correr uvpy -m src.generacion.contexto_prueba --modo "$CONTEXTO" --salida "$CTX_JSON"

if [[ $ESTADO -eq 0 ]]; then
    paso "2/4 entorno de vLLM (.venv-gen)"
    if [[ ! -x .venv-gen/bin/python ]]; then
        correr uv venv .venv-gen --python 3.12
        correr uv pip install --quiet --python .venv-gen/bin/python vllm pyarrow
    fi
fi

if [[ $ESTADO -eq 0 ]]; then
    paso "3/4 benchmark: ${MODELOS[*]}"
    nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
    PYTHONPATH=. correr .venv-gen/bin/python -m src.generacion.bench \
        --modelo "${MODELOS[@]}" --contexto "$CTX_JSON"
    paso "4/4 resultados"
    cat data/processed/bench_generacion.csv
fi

enviar_resumen generacion_bench
exit "$ESTADO"
