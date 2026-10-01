#!/usr/bin/env bash
#SBATCH --job-name=recuperar
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
# Fase 6 (src/recuperacion): para cada pregunta, los 10 mejores pasajes + señales para la
# fase 8. Es la etapa 1 de la corrida ciega y la que alimenta a la fase 7 (generación).
#     entrada:  data/sample_50.jsonl (o el split de 992 preguntas)
#     salida:   data/recuperacion/<split>.jsonl y <split>.config.json (hiperparámetros y
#               commits de los modelos, para reproducir)
# Con data/sample_50.jsonl también corre las ABLACIONES (sin reranker, sin directos, sin
# alias, con filtro de área) y las compara con la línea base de la fase 5 -> ablaciones.json.
# El filtro de área va DESACTIVADO por defecto (Config.area_modo = "ninguno"): las
# ablaciones de esta fase mostraron mejor cobertura sin él (ver checklist.md, paso 6.3), así
# que la ablación de área ahora prueba lo contrario: activarlo con --area filtro.
#
#     mkdir -p logs                                   # una sola vez
#     sbatch jobs/instalar_torch_gpu.sh               # una sola vez (.venv-gpu, torch cu118)
#     sbatch jobs/recuperar.sh                        # sample_50 + ablaciones
#     sbatch jobs/recuperar.sh data/test_992.jsonl    # otro split (sin ablaciones)
#
# Requiere data/index/ (jobs/indice.sh). Sale a logs/recuperar_<id>.out (avance y resultados)
# y logs/recuperar_<id>.err (solo errores).
source "$SLURM_SUBMIT_DIR/jobs/_comun.sh"
preparar_entorno

if [[ -x .venv-gpu/bin/python ]]; then
    echo "usando .venv-gpu (torch para CUDA 11.8)"
    uvpy() { PYTHONPATH=. .venv-gpu/bin/python "$@"; }
else
    echo "AVISO: no hay .venv-gpu; se usa el torch del proyecto (puede no ver la GPU)" >&2
fi

PREGUNTAS="${1:-data/sample_50.jsonl}"
NOMBRE="$(basename "$PREGUNTAS" .jsonl)"
SALIDA="data/recuperacion/${NOMBRE}"
mkdir -p data/recuperacion

paso "0/4 verificando índices, preguntas y GPU"
for f in "$PREGUNTAS" data/index/faiss.index data/index/index_config.json data/index/chunk_ids.json; do
    [[ -s "$f" ]] || { echo "ERROR: falta $f" >&2; ESTADO=2; }
done
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader || true
if [[ $ESTADO -eq 0 ]] && ! uvpy -c "import torch, sys; sys.exit(0 if torch.cuda.is_available() else 1)"; then
    echo "ERROR: torch no ve ninguna GPU en $(hostname)" >&2
    ESTADO=3
fi

if [[ $ESTADO -eq 0 ]]; then
    paso "1/4 recuperación completa (alias + híbrido + área + directos + cerradas + reranker)"
    correr uvpy -m src.recuperacion.pipeline --preguntas "$PREGUNTAS" --salida "${SALIDA}.jsonl"
fi

if [[ $ESTADO -eq 0 && "$NOMBRE" == "sample_50" ]]; then
    paso "2/4 ablaciones (cada paso de la fase 6 por separado)"
    correr uvpy -m src.recuperacion.pipeline --preguntas "$PREGUNTAS" --salida "${SALIDA}_sin_reranker.jsonl" --sin-reranker
    correr uvpy -m src.recuperacion.pipeline --preguntas "$PREGUNTAS" --salida "${SALIDA}_sin_directos.jsonl" --sin-directos
    correr uvpy -m src.recuperacion.pipeline --preguntas "$PREGUNTAS" --salida "${SALIDA}_sin_alias.jsonl" --sin-alias
    correr uvpy -m src.recuperacion.pipeline --preguntas "$PREGUNTAS" --salida "${SALIDA}_con_area.jsonl" --area filtro
    paso "3/4 métricas contra el legal_basis (solo para evaluar) y línea base de la fase 5"
    correr uvpy -m src.recuperacion.evaluar "${SALIDA}.jsonl" "${SALIDA}_sin_reranker.jsonl" \
        "${SALIDA}_sin_directos.jsonl" "${SALIDA}_sin_alias.jsonl" "${SALIDA}_con_area.jsonl" \
        --salida data/recuperacion/ablaciones.json
else
    echo "(ablaciones y métricas solo con data/sample_50.jsonl: el test no trae legal_basis)"
fi

paso "4/4 resumen"
ls -lh data/recuperacion 2>/dev/null
grep -E '^(RESULTADO|BASE|[0-9]+/[0-9]+ ítems|recuperación de)' "$OUT" 2>/dev/null | sed 's/^/  /'

enviar_resumen recuperar
exit "$ESTADO"
