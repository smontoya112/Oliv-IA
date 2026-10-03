#!/usr/bin/env bash
# Lanza en hypatia las 3 partes de la corrida EN PARALELO (un job con una GPU cada una) y un cuarto job,
# de CPU, que une las tres partes cuando terminan bien. NO es un job de Slurm: se corre en el nodo de login,
# desde la raíz del repo (solo verifica, divide las preguntas y hace sbatch):
#
#     bash jobs/lanzar_corrida.sh                         # data/test_992.jsonl
#     bash jobs/lanzar_corrida.sh data/sample_50.jsonl    # ensayo con la muestra (~17 preguntas por parte)
#     ESPERAR=<id de job> bash jobs/lanzar_corrida.sh     # las partes arrancan cuando ese job (p. ej. el índice)
#                                                         # termine bien; entonces no se verifica el índice ahora
#
# Qué hace:
#   1. verifica las preguntas, config/responder.json, el índice y los chunks que esa config usa
#   2. divide las preguntas en data/lote/<entrada>/parte_{1,2,3}.jsonl UNA sola vez (src.lote dividir, determinista,
#      repartido por formato); así los 3 jobs no se pisan al dividir
#   3. sbatch jobs/corrida.sh N  ->  corrida_p1, corrida_p2, corrida_p3  (logs/corrida_pN_<id>.out)
#   4. sbatch jobs/unir_corrida.sh con --dependency=afterok de las 3 -> data/lote/<entrada>/submissions.jsonl
# Si una parte se cae o se acaba el tiempo: relanzar SOLO esa (sbatch --job-name=corrida_pN jobs/corrida.sh N <entrada>);
# sigue donde iba, y la unión se hace a mano (comando al final de este mensaje) cuando las tres estén completas.
# La cola de hypatia limita las GPU por usuario (QOSMaxGRESPerUser): si no caben las tres, la última espera su turno.
#
# Variables: PYTHON (por defecto .venv-gpu/bin/python), ESPERAR (job previo), PARTES (por defecto 3, no cambiarlo
# sin cambiar jobs/corrida.sh), SBATCH_EXTRA (p. ej. "-A cuenta").
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 2
PREGUNTAS="${1:-data/test_992.jsonl}"
LOTE="data/lote/$(basename "$PREGUNTAS" .jsonl)"
PY="${PYTHON:-.venv-gpu/bin/python}"
PARTES="${PARTES:-3}"
ESPERAR="${ESPERAR:-}"
mkdir -p logs
fallo=0
falta() { echo "ERROR: falta $1" >&2; fallo=1; }

echo "== 1/4 verificando"
[[ -s "$PREGUNTAS" ]] || falta "$PREGUNTAS (cp <archivo recibido> data/test_992.jsonl)"
[[ -s config/responder.json ]] || falta config/responder.json
[[ -x "$PY" ]] || falta "$PY (hypatia: jobs/instalar_torch_gpu.sh + instalar_responder.sh)"
if [[ $fallo -eq 0 ]]; then
    IDX="$(PYTHONPATH=. "$PY" -c "import json; print(json.load(open('config/responder.json'))['indice'])")"
    echo "config: $(tr -d '\n ' < config/responder.json)"
    if [[ -z "$ESPERAR" ]]; then
        CHUNKS="$(PYTHONPATH=. "$PY" -c "import json,sys; print(json.load(open(sys.argv[1]+'/index_config.json'))['chunks'])" "$IDX" 2>/dev/null)"
        for f in "$IDX/faiss.index" "$IDX/index_config.json" "$IDX/chunk_ids.json" "${CHUNKS:-$IDX/chunks?}"; do
            [[ -s "$f" ]] || falta "$f (índice de config/responder.json: CORPUS=base sbatch jobs/chunking.sh y jobs/indice.sh)"
        done
        echo "índice $IDX · chunks ${CHUNKS:-?} · $(PYTHONPATH=. "$PY" -c "import json,sys; print(json.load(open(sys.argv[1]+'/index_config.json')).get('n_chunks','?'))" "$IDX") chunks"
    else
        echo "las partes esperan al job $ESPERAR (no se verifica $IDX ahora)"
    fi
fi
[[ $fallo -eq 0 ]] || exit 2

echo "== 2/4 dividiendo $PREGUNTAS en $PARTES partes"
PYTHONPATH=. "$PY" -m src.lote dividir --preguntas "$PREGUNTAS" --partes "$PARTES" --dir "$LOTE" || exit $?

echo "== 3/4 mandando las $PARTES partes"
DEP=(); [[ -n "$ESPERAR" ]] && DEP=(--dependency="afterok:$ESPERAR")
JOBS=()
for n in $(seq 1 "$PARTES"); do
    # shellcheck disable=SC2086
    J=$(sbatch --parsable ${SBATCH_EXTRA:-} --job-name="corrida_p$n" "${DEP[@]}" jobs/corrida.sh "$n" "$PREGUNTAS") \
        || { echo "ERROR: sbatch de la parte $n falló; las partes ya enviadas siguen en cola (scancel ${JOBS[*]:-})" >&2; exit 3; }
    JOBS+=("$J"); echo "  parte $n -> job $J"
done

echo "== 4/4 unión al terminar las $PARTES partes"
LISTA="$(IFS=:; echo "${JOBS[*]}")"
# shellcheck disable=SC2086
U=$(sbatch --parsable ${SBATCH_EXTRA:-} --dependency="afterok:$LISTA" --kill-on-invalid-dep=yes \
        jobs/unir_corrida.sh "$PREGUNTAS") && echo "  unión -> job $U (se cancela sola si una parte falla)"

echo
echo "seguimiento:   squeue -u \$USER -o '%.9i %.14j %.8T %.10M %R'"
echo "               tail -f logs/corrida_p1_${JOBS[0]}.out"
echo "al terminar:   $LOTE/submissions.jsonl   (si la unión no corrió: PYTHONPATH=. $PY -m src.lote unir --preguntas $PREGUNTAS --dir $LOTE --salida $LOTE/submissions.jsonl)"
