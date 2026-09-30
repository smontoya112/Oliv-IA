#!/usr/bin/env bash
# Descarga todo el corpus (seed + fuentes_propias.json + data/enlaces.txt) en un nodo del clúster.
#
# Uso, desde la raíz del repo en hypatia (mejor dentro de tmux o con nohup):
#     bash scrapper.sh           # pide RAM (CPU) y corre
#     bash scrapper.sh --gpu     # pide GPU; el scraper no la usa, solo por si la necesitan
#     bash scrapper.sh --forzar  # cualquier otro argumento se pasa a `run` tal cual
#
# El scraper no usa GPU. 32 GB de RAM y 4 h sobran; use --gpu solo si de verdad hace falta.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p logs

RECURSOS=(--mem=32gb --time=04:00:00)                    # srun --mem=32gb --time=04:00:00 --pty bash -i
if [[ "${1:-}" == "--gpu" ]]; then
    RECURSOS=(--mem=64gb --time=12:00:00 --gres=gpu:1 -p gpu)   # srun --mem=64gb ... -p gpu --pty bash -i
    shift
fi
EXTRA="$*"

LOG="logs/scrapper_$(date +%Y%m%d_%H%M%S).log"
echo "Recursos: ${RECURSOS[*]} · log: $LOG"

# Igual que los srun con --pty bash -i, pero en vez de una shell interactiva
# ejecuta el trabajo y termina solo (así se puede dejar corriendo).
srun "${RECURSOS[@]}" bash -c "
    set -euo pipefail
    cd '$PWD'
    echo '== 1/3 seed -> fuentes_seed.json'
    uv run python -m src.descarga.seed_a_fuentes
    echo '== 2/3 descarga de todo el corpus (fuentes + enlaces.txt)'
    uv run python -m src.descarga.run $EXTRA
    echo '== 3/3 reintento de los que fallaron'
    uv run python -m src.descarga.run --solo-fallidos $EXTRA || true
    echo '== listo. Revisen data/corpus_manifest.json y data/descubiertos.csv'
" 2>&1 | tee "$LOG"
