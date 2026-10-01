#!/usr/bin/env bash
#SBATCH --job-name=recuperar_sin_area_sin_reranker
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err
#SBATCH --mail-type=ALL
#SBATCH --mail-user=s.montoya112@uniandes.edu.co
#SBATCH --partition=gpu
#SBATCH --gres=gpu:1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=02:00:00
#
# Fase 6 (src/recuperacion): ablación combinada, apaga a la vez el filtro de área (6.3) y
# el reranker (6.5), para ver el efecto conjunto de ambos (las ablaciones de jobs/recuperar.sh
# solo apagan una pieza a la vez).
#     entrada:  data/sample_50.jsonl
#     salida:   data/recuperacion/sample_50_sin_area_sin_reranker.jsonl (+ .config.json)
#               data/recuperacion/ablaciones_sin_area_sin_reranker.json (métricas, comparadas
#               contra la corrida completa y la línea base de la fase 5)
#
# Requiere data/index/ (jobs/indice.sh) y haber corrido antes jobs/recuperar.sh al menos una
# vez (usa data/recuperacion/sample_50.jsonl, la corrida completa, como punto de comparación).
#
#     mkdir -p logs                                          # una sola vez
#     sbatch jobs/instalar_torch_gpu.sh                       # una sola vez (.venv-gpu, torch cu118)
#     sbatch jobs/recuperar.sh                                # si aún no existe data/recuperacion/sample_50.jsonl
#     sbatch jobs/recuperar_sin_area_sin_reranker.sh
#
# Sale a logs/recuperar_sin_area_sin_reranker_<id>.out (avance y resultados) y
# logs/recuperar_sin_area_sin_reranker_<id>.err (solo errores).
source "$SLURM_SUBMIT_DIR/jobs/_comun.sh"
preparar_entorno

if [[ -x .venv-gpu/bin/python ]]; then
    echo "usando .venv-gpu (torch para CUDA 11.8)"
    uvpy() { PYTHONPATH=. .venv-gpu/bin/python "$@"; }
else
    echo "AVISO: no hay .venv-gpu; se usa el torch del proyecto (puede no ver la GPU)" >&2
fi

PREGUNTAS="data/sample_50.jsonl"
SALIDA="data/recuperacion/sample_50_sin_area_sin_reranker"
BASE_COMPLETA="data/recuperacion/sample_50.jsonl"
mkdir -p data/recuperacion

paso "0/3 verificando índices, preguntas y GPU"
for f in "$PREGUNTAS" data/index/faiss.index data/index/index_config.json data/index/chunk_ids.json; do
    [[ -s "$f" ]] || { echo "ERROR: falta $f" >&2; ESTADO=2; }
done
[[ -s "$BASE_COMPLETA" ]] || echo "AVISO: no existe $BASE_COMPLETA; la comparación saldrá incompleta" >&2
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader || true
if [[ $ESTADO -eq 0 ]] && ! uvpy -c "import torch, sys; sys.exit(0 if torch.cuda.is_available() else 1)"; then
    echo "ERROR: torch no ve ninguna GPU en $(hostname)" >&2
    ESTADO=3
fi

if [[ $ESTADO -eq 0 ]]; then
    paso "1/3 recuperación sin filtro de área y sin reranker"
    correr uvpy -m src.recuperacion.pipeline --preguntas "$PREGUNTAS" --salida "${SALIDA}.jsonl" \
        --sin-reranker --area ninguno
fi

if [[ $ESTADO -eq 0 ]]; then
    paso "2/3 métricas contra el legal_basis y comparación con la corrida completa"
    correr uvpy -m src.recuperacion.evaluar "$BASE_COMPLETA" "${SALIDA}.jsonl" \
        --salida data/recuperacion/ablaciones_sin_area_sin_reranker.json
fi

paso "3/3 resumen"
ls -lh data/recuperacion 2>/dev/null
grep -E '^(RESULTADO|BASE|[0-9]+/[0-9]+ ítems|recuperación de)' "$OUT" 2>/dev/null | sed 's/^/  /'

enviar_resumen recuperar_sin_area_sin_reranker
exit "$ESTADO"
