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
# Variables: PYTHON (por defecto .venv-gpu/bin/python), ESPERAR (job previo), PARTES (por defecto 3; con solo 2 GPU
# libres para el usuario, PARTES=2 reparte mejor: cada parte tarda ~1,5 veces más pero no queda ninguna esperando),
# SBATCH_EXTRA (p. ej. "-A cuenta").
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

export PARTES      # lo lee jobs/corrida.sh
# La cola gpu limita las GPU por usuario (QOS): si no caben todas las partes a la vez, las últimas esperan su turno
# y la corrida tarda más. Con PARTES=2 y 2 GPU libres el reparto es el que menos tarda.
LIM="$(sacctmgr -n -P show qos gpu format=MaxTRESPU 2>/dev/null | grep -o 'gres/gpu=[0-9]*' | head -1 | cut -d= -f2)"
USO="$(squeue -h -u "$USER" -p gpu -t RUNNING -o '%b' 2>/dev/null | grep -c gpu)"
if [[ -n "$LIM" ]] && (( USO + PARTES > LIM )); then
    echo "AVISO: la cola gpu permite $LIM GPU por usuario y ya usas $USO (squeue -u \$USER): de las $PARTES partes solo" \
         "caben $(( LIM > USO ? LIM - USO : 0 )) a la vez y el resto espera. Liberen GPU (scancel de lo que no haga falta) o usen PARTES=$(( LIM > USO ? LIM - USO : 1 ))."
fi

echo "== 2/4 dividiendo $PREGUNTAS en $PARTES partes"
FORZAR=()
if [[ -s "$LOTE/division.json" ]]; then       # otra división previa (p. ej. con otro número de partes)
    PREV="$(PYTHONPATH=. "$PY" -c "import json,sys; print(json.load(open(sys.argv[1]))['partes'])" "$LOTE/division.json")"
    if [[ "$PREV" != "$PARTES" ]]; then
        if compgen -G "$LOTE/sub_*.jsonl" >/dev/null; then
            echo "ERROR: $LOTE ya tiene avance dividido en $PREV partes; seguir con PARTES=$PREV o mover $LOTE" >&2; exit 2
        fi
        echo "la división previa era de $PREV partes y no hay avance: se rehace"; FORZAR=(--forzar)
    fi
fi
PYTHONPATH=. "$PY" -m src.lote dividir --preguntas "$PREGUNTAS" --partes "$PARTES" --dir "$LOTE" ${FORZAR[@]+"${FORZAR[@]}"} || exit $?

echo "== 3/4 mandando las $PARTES partes"
DEP=(); [[ -n "$ESPERAR" ]] && DEP=(--dependency="afterok:$ESPERAR")
JOBS=()
for n in $(seq 1 "$PARTES"); do
    # shellcheck disable=SC2086
    J=$(sbatch --parsable ${SBATCH_EXTRA:-} --job-name="corrida_p$n" ${DEP[@]+"${DEP[@]}"} jobs/corrida.sh "$n" "$PREGUNTAS") \
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
