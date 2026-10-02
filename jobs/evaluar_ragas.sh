#!/usr/bin/env bash
#SBATCH --job-name=evaluar_ragas
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err
#SBATCH --mail-type=ALL
#SBATCH --mail-user=s.montoya112@uniandes.edu.co
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=24G
#SBATCH --time=00:45:00
#
# Paso 7.5: corre el juez de texto libre (scripts/evaluate.py --ragas) sobre una entrega ya
# generada. No necesita GPU: el juez (z-ai/glm-5.3-flash) corre en OpenRouter por API, y el
# encoder de similitud semantica (intfloat/multilingual-e5-large) es chico y va por CPU.
# Si corre mas rapido, puede pedirse una GPU agregando --gres=gpu:1 --partition=gpu, pero
# no hace falta para un lote de ~35 items.
#
# Requiere OPENROUTER_API_KEY en .env (raiz del repo o scripts/.env) o en el entorno.
#
#     mkdir -p logs                                             # una sola vez
#     sbatch jobs/evaluar_ragas.sh data/processed/bench_generacion/llama-3.1-8b.jsonl
#
# Salidas: data/processed/ragas_<nombre_submission>.json (reporte completo) y los logs del job.
source "$SLURM_SUBMIT_DIR/jobs/_comun.sh"
preparar_entorno

SUBMISSION="${1:?uso: sbatch jobs/evaluar_ragas.sh <submission.jsonl>}"
NOMBRE="$(basename "$SUBMISSION" .jsonl)"
SALIDA="data/processed/ragas_${NOMBRE}.json"

paso "0/3 verificando entrega y llave"
[[ -s "$SUBMISSION" ]] || { echo "ERROR: no existe $SUBMISSION" >&2; ESTADO=2; }
if [[ $ESTADO -eq 0 ]] && [[ -z "${OPENROUTER_API_KEY:-}" ]] \
    && ! grep -qs '^OPENROUTER_API_KEY=' .env scripts/.env 2>/dev/null; then
    echo "ERROR: falta OPENROUTER_API_KEY (variable de entorno o .env / scripts/.env)" >&2
    ESTADO=3
fi

if [[ $ESTADO -eq 0 ]]; then
    paso "1/3 conectividad del nodo de computo a OpenRouter"
    # Los nodos de computo de hypatia a veces solo permiten salida a ciertos dominios (ya
    # confirmamos que huggingface.co si funciona); si openrouter.ai esta bloqueado, el
    # cliente HTTP se queda colgado en vez de fallar rapido, y el job se cuelga 30 min sin
    # imprimir nada (ver evaluar_ragas_751603). Se prueba primero con un timeout corto.
    if curl -s -o /dev/null -w "HTTP %{http_code}\n" --max-time 15 https://openrouter.ai/api/v1/models; then
        :
    else
        echo "ERROR: no hay conectividad a openrouter.ai desde $(hostname) (curl con timeout)." >&2
        echo "  Puede que este nodo bloquee ese dominio; probar desde otro nodo o pedirle a" >&2
        echo "  soporte de hypatia que lo habilite." >&2
        ESTADO=4
    fi
fi

if [[ $ESTADO -eq 0 ]]; then
    paso "2/3 dependencias del juez (ragas, langchain-openai, sentence-transformers...)"
    correr uv pip install --quiet -r scripts/requirements-evaluador.txt
fi

if [[ $ESTADO -eq 0 ]]; then
    paso "3/3 corriendo el juez sobre $SUBMISSION"
    mkdir -p data/processed
    # --no-sync: `uv run` normalmente re-sincroniza el entorno con uv.lock antes de correr,
    # lo que deshace el tope langchain-community<0.4 que acabamos de instalar a mano (ragas
    # importa langchain_community.chat_models.vertexai, que las versiones nuevas eliminaron).
    # jobs/ragas_con_timeout.py: mismo scripts/evaluate.py, sin tocarlo (inmodificable), pero
    # con timeout/reintentos acotados en el cliente del juez (ver ese archivo para el porque).
    correr uv run --quiet --no-sync python jobs/ragas_con_timeout.py --submission "$SUBMISSION" \
        --split sample --ragas --out "$SALIDA"
fi

enviar_resumen evaluar_ragas
exit "$ESTADO"
