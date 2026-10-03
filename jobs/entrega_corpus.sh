#!/usr/bin/env bash
#SBATCH --job-name=entrega_corpus
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err
#SBATCH --mail-type=ALL
#SBATCH --mail-user=s.montoya112@uniandes.edu.co
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=00:40:00
#
# Material de entrega del corpus (scripts/entrega_corpus.py): corpus_manifest.json y CORPUS.md en la raíz del repo y
# entrega/corpus_<equipo>.zip con LICENSE, corpus_manifest.json, corpus/ e indice/. Solo CPU. Desde la raíz, con el índice
# (data/index_base) y los fragmentos (data/processed_base) ya congelados y un archivo LICENSE_CORPUS en la raíz:
#
#     mkdir -p logs
#     LICENCIA=CC-BY-4.0 ENLACE="https://..." sbatch jobs/entrega_corpus.sh
#
# LICENCIA y ENLACE se escriben en corpus_manifest.json y CORPUS.md (si no se dan, quedan como «pendiente»). El comprimido
# se genera con LICENSE_CORPUS (CC BY 4.0), que dentro del zip se llama LICENSE como exige el enunciado; el LICENSE de la raíz
# (MIT) es el del código. Sin LICENSE_CORPUS el job falla.
source "$SLURM_SUBMIT_DIR/jobs/_comun.sh"
preparar_entorno

PY="${PYTHON:-.venv-gpu/bin/python}"
EQUIPO="${EQUIPO:-Oliv-IA}"
FECHA="${FECHA:-$(date +%F)}"
ARGS=(--equipo "$EQUIPO")
[[ -x "$PY" ]] || { echo "ERROR: falta $PY" >&2; ESTADO=2; }
[[ -s LICENSE_CORPUS ]] || { echo "ERROR: falta LICENSE_CORPUS en la raíz del repo (la licencia abierta del corpus)" >&2; ESTADO=2; }

if [[ $ESTADO -eq 0 ]]; then
    paso "1/2 corpus_manifest.json y CORPUS.md"
    correr "$PY" scripts/entrega_corpus.py manifiesto "${ARGS[@]}" --fecha "$FECHA" \
        ${LICENCIA:+--licencia "$LICENCIA"} ${ENLACE:+--enlace "$ENLACE"}
fi
if [[ $ESTADO -eq 0 ]]; then
    paso "2/2 comprimido entrega/corpus_${EQUIPO}.zip"
    correr "$PY" scripts/entrega_corpus.py empaquetar "${ARGS[@]}" --licencia-archivo LICENSE_CORPUS --salida entrega
fi

enviar_resumen entrega_corpus
exit "$ESTADO"
