#!/usr/bin/env bash
#SBATCH --job-name=generacion_bench
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err
#SBATCH --mail-type=ALL
#SBATCH --mail-user=s.montoya112@uniandes.edu.co
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --gres=gpu:1
#SBATCH --partition=gpu
#SBATCH --time=12:00:00
#
# Fase 7 (7.1 y 7.2): compara los decoders sobre las 50 muestras con un contexto de PRUEBA
# (no depende de los índices de la fase 5/6): tiempo por formato, validez del JSON y
# exactitud en cerradas. Requiere data/processed/chunks.parquet (jobs/chunking.sh) y
# haber corrido antes jobs/instalar_llamacpp.sh (compila llama.cpp con CUDA 11.8).
#
#     mkdir -p logs            # una sola vez
#     sbatch jobs/generacion_bench.sh                              # los 3 modelos
#     sbatch jobs/generacion_bench.sh qwen3-8b                     # solo uno (o varios)
#     CONTEXTO=bm25 sbatch jobs/generacion_bench.sh qwen3-8b       # contexto BM25 en vez del oráculo
#     CONTEXTO=recuperacion sbatch jobs/generacion_bench.sh qwen3-8b   # pasajes REALES de la fase 6
#
# Usa modelos GGUF Q8_0 (src/generacion/motor.py): se bajan de Hugging Face la primera vez
# (el nodo necesita internet o una caché HF_HOME ya llena; ~9 GB por modelo).
#
# Salidas: data/processed/bench_generacion.csv (una fila por modelo y formato),
# data/processed/bench_generacion/<modelo>.jsonl (predicciones) y los logs del job.
source "$SLURM_SUBMIT_DIR/jobs/_comun.sh"
preparar_entorno
# El cluster auto-adjunta gdb cuando un proceso aborta (p. ej. un CUDA_CHECK fallido de
# ggml) y ese backtrace tapa el mensaje real de error en el .err. Se desactivan los core
# dumps para que, si vuelve a abortar, se vea el error de ggml sin ruido de gdb encima.
ulimit -c 0

MODELOS=("$@"); [[ ${#MODELOS[@]} -eq 0 ]] && MODELOS=(qwen3-8b llama-3.1-8b salamandra-7b)
CONTEXTO="${CONTEXTO:-oraculo}"
CTX_JSON="data/processed/contexto_${CONTEXTO}.json"

paso "1/4 contexto de prueba ($CONTEXTO) -> $CTX_JSON"
if [[ "$CONTEXTO" == "recuperacion" ]]; then
    # contexto REAL de la fase 6 (sbatch jobs/recuperar.sh antes)
    correr uvpy -m src.generacion.contexto_prueba --modo recuperacion         --entrada data/recuperacion/sample_50.jsonl --salida "$CTX_JSON"
else
    correr uvpy -m src.generacion.contexto_prueba --modo "$CONTEXTO" --salida "$CTX_JSON"
fi

if [[ $ESTADO -eq 0 ]]; then
    paso "2/4 entorno de llama.cpp (.venv-gen) y CUDA 11.8"
    module load cuda/11.8 || { echo "ERROR: no existe el módulo cuda/11.8" >&2; ESTADO=3; }
    # misma razón que en jobs/instalar_llamacpp.sh: libllama.so necesita std::filesystem
    # (GCC >= 9); /usr/lib64 (gcc 8.5) no lo trae, así que se usa la libstdc++ de gcc 9.3.0
    # (OpenHPC) en vez de la (más vieja) que empaqueta el Python de uv.
    export LD_LIBRARY_PATH="/opt/ohpc/pub/compiler/gcc/9.3.0/lib64:${LD_LIBRARY_PATH:-}"
    if ! .venv-gen/bin/python -c "import llama_cpp" 2>/dev/null; then
        echo "ERROR: .venv-gen no tiene llama_cpp: corran primero sbatch jobs/instalar_llamacpp.sh" >&2
        ESTADO=4
    fi
fi

if [[ $ESTADO -eq 0 ]]; then
    paso "3/4 benchmark: ${MODELOS[*]}"
    nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
    # con pasajes reales, la fase 8 respalda las citas con el corpus (data/index) en vez de borrarlas
    EXTRA=(); [[ "$CONTEXTO" == "recuperacion" && -s data/index/index_config.json ]] && EXTRA=(--catalogo data/index)
    PYTHONPATH=. correr .venv-gen/bin/python -m src.generacion.bench \
        --modelo "${MODELOS[@]}" --contexto "$CTX_JSON" "${EXTRA[@]}"
    paso "4/4 resultados"
    cat data/processed/bench_generacion.csv
fi

enviar_resumen generacion_bench
exit "$ESTADO"
