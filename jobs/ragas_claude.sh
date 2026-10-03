#!/usr/bin/env bash
#SBATCH --job-name=ragas_claude
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=24G
#SBATCH --time=00:50:00
#
# RAGAS (answer_correctness, juez z-ai/glm-5.3-flash por OpenRouter) sobre una entrega de sample_50, guardando
# también el puntaje por ítem. Sin GPU. USA CRÉDITOS: una corrida = una llamada de este job.
#
#     sbatch jobs/ragas_claude.sh data/exp/bench/final_3.jsonl final_3
#
# Seguridad: la llave de OpenRouter solo se lee de scripts/.env (un archivo con UNA línea, OPENROUTER_API_KEY, creado en
# el servidor; nunca se imprime ni se sube a git). HF_TOKEN no se usa: se borra del entorno y los modelos van en modo offline.
# Salidas: experimentos/claude/<etiqueta>/ragas.json (reporte oficial) y ragas_items.json (puntaje por ítem).
source "$SLURM_SUBMIT_DIR/jobs/_comun.sh"
preparar_entorno
unset HF_TOKEN HUGGING_FACE_HUB_TOKEN
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1

SUBMISSION="${1:?uso: sbatch jobs/ragas_claude.sh <entrega.jsonl> <etiqueta>}"
ETIQUETA="${2:?falta la etiqueta}"
SALIDA="experimentos/claude/${ETIQUETA}"
mkdir -p "$SALIDA"

[[ -s "$SUBMISSION" ]] || { echo "ERROR: no existe $SUBMISSION" >&2; ESTADO=2; }
grep -qs '^OPENROUTER_API_KEY=' scripts/.env || { echo "ERROR: falta scripts/.env con OPENROUTER_API_KEY" >&2; ESTADO=3; }
[[ -x .venv/bin/python ]] || { echo "ERROR: falta .venv (el entorno del juez)" >&2; ESTADO=4; }
if [[ $ESTADO -eq 0 ]]; then
    paso "conectividad a openrouter.ai (sin llave)"
    curl -s -o /dev/null -w "HTTP %{http_code}\n" --max-time 15 https://openrouter.ai/api/v1/models || { echo "ERROR: sin salida a openrouter.ai" >&2; ESTADO=5; }
fi
if [[ $ESTADO -eq 0 ]]; then
    paso "RAGAS sobre $SUBMISSION"
    OLIVIA_RAGAS_ITEMS="$SALIDA/ragas_items.json" correr .venv/bin/python jobs/ragas_por_item.py \
        --submission "$SUBMISSION" --split sample --ragas --out "$SALIDA/ragas.json"
    grep -E '"correctness"|"n_fallidos"|"n_respondidos"|"puntos"' "$SALIDA/ragas.json" 2>/dev/null | sed 's/^/RESULTADO /'
fi
echo "== fin ESTADO=$ESTADO · $(date '+%F %T')"
exit "$ESTADO"
