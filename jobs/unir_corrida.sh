#!/usr/bin/env bash
#SBATCH --job-name=unir_corrida
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err
#SBATCH --mail-type=ALL
#SBATCH --mail-user=s.montoya112@uniandes.edu.co
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:20:00
#
# Une las partes de la corrida (data/lote/<entrada>/sub_N.jsonl) en un solo submissions.jsonl, ordenado por id,
# y lo valida contra el schema (src.lote unir). Lo manda jobs/lanzar_corrida.sh con --dependency=afterok de
# las tres partes; también se puede lanzar a mano cuando las tres estén completas:
#
#     sbatch jobs/unir_corrida.sh                         # data/test_992.jsonl
#     sbatch jobs/unir_corrida.sh data/sample_50.jsonl
#
# Salida: data/lote/<entrada>/submissions.jsonl (no se escribe en la raíz del repo para no pisar otro
# submissions.jsonl; copiarlo a donde se entregue). Termina con error si falta algún id o hay problemas de schema.
source "$SLURM_SUBMIT_DIR/jobs/_comun.sh"
preparar_entorno
PREGUNTAS="${1:-data/test_992.jsonl}"
LOTE="data/lote/$(basename "$PREGUNTAS" .jsonl)"
PY="${PYTHON:-.venv-gpu/bin/python}"
[[ -x "$PY" ]] || PY="python3"

paso "unión de $LOTE"
[[ -s "$PREGUNTAS" ]] || { echo "ERROR: falta $PREGUNTAS" >&2; ESTADO=2; }
if [[ $ESTADO -eq 0 ]]; then
    correr env PYTHONPATH=. "$PY" -m src.lote unir --preguntas "$PREGUNTAS" --dir "$LOTE" --salida "$LOTE/submissions.jsonl"
    ls -l "$LOTE"/sub_*.jsonl "$LOTE/submissions.jsonl" 2>/dev/null
    sha256sum "$LOTE/submissions.jsonl" 2>/dev/null | sed 's/^/  sha256 /'
fi

enviar_resumen unir_corrida
exit "$ESTADO"
