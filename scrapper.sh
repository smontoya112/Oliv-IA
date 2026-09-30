#!/usr/bin/env bash
# Descarga el corpus COMPLETO en un nodo del clúster: las ~220 normas y sentencias de
# data/seed_targets.json (rama corpus) + data/fuentes_propias.json + data/enlaces.txt.
#
# Uso, desde la raíz del repo en hypatia (dentro de tmux o con nohup, porque dura horas):
#     tmux new -s scrapper
#     bash scrapper.sh            # pide RAM (CPU) y corre
#     bash scrapper.sh --gpu      # pide GPU; el scraper no la usa, solo por si la necesitan
#     bash scrapper.sh --forzar   # cualquier otro argumento se pasa a `run` tal cual
#
# Es reanudable: lo ya descargado queda en data/raw y no se vuelve a bajar. Si el job se
# corta por tiempo, basta volver a lanzar el script.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p logs

RECURSOS=(--mem=32gb --time=04:00:00)                    # srun --mem=32gb --time=04:00:00 --pty bash -i
if [[ "${1:-}" == "--gpu" ]]; then
    RECURSOS=(--mem=64gb --time=12:00:00 --gres=gpu:1 -p gpu)   # srun --mem=64gb --time=12:00:00 --gres=gpu:1 -p gpu --pty bash -i
    shift
fi
EXTRA="$*"

LOG="logs/scrapper_$(date +%Y%m%d_%H%M%S).log"
echo "Recursos: ${RECURSOS[*]} · log: $LOG"

# Igual que los srun con --pty bash -i, pero en vez de una shell interactiva
# ejecuta el trabajo y termina solo.
srun "${RECURSOS[@]}" bash -c "
    set -euo pipefail
    cd '$PWD'
    echo '== 1/4 seed -> data/fuentes_seed.json'
    uv run python -m src.descarga.seed_a_fuentes
    echo '== 2/4 descarga de todo el corpus (seed + fuentes_propias + enlaces.txt)'
    uv run python -m src.descarga.run $EXTRA || true
    echo '== 3/4 reintento de los que fallaron (2 pasadas)'
    uv run python -m src.descarga.run --solo-fallidos $EXTRA || true
    uv run python -m src.descarga.run --solo-fallidos $EXTRA || true
    echo '== 4/4 resumen del manifest'
    uv run python -c \"
import json, collections
m = json.load(open('data/corpus_manifest.json', encoding='utf-8'))
c = collections.Counter(r.get('estado') for r in m)
print('documentos:', len(m), dict(c))
for r in m:
    if r.get('estado') != 'ok': print('  FALLO', r['doc_id'], '|', r.get('error'))
\"
    echo '== listo. Revisen data/corpus_manifest.json, data/descubiertos.csv y data/fuentes_pendientes.json'
" 2>&1 | tee "$LOG"
