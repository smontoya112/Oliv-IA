#!/usr/bin/env bash
#SBATCH --job-name=corrida
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err
#SBATCH --mail-type=ALL
#SBATCH --mail-user=s.montoya112@uniandes.edu.co
#SBATCH --partition=gpu
#SBATCH --gres=gpu:1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=05:00:00
#
# Corrida ciega del sábado, repartida en 3 partes (src/lote.py). Una parte = un job con una GPU:
# lo normal es lanzar las tres a la vez con `bash jobs/lanzar_corrida.sh` (divide una sola vez, manda los
# 3 jobs en paralelo y un cuarto, de CPU, que une las partes al terminar). Este script corre UNA parte:
#   0. verifica índice y chunks (los de config/responder.json), entorno (.venv-gpu con llama_cpp) y GPU
#   1. divide la entrada en data/lote/<entrada>/parte_{1,2,3}.jsonl (determinista: en cada máquina sale igual;
#      si ya está dividida con el mismo archivo, no hace nada). Con jobs paralelos la división debe existir
#      ANTES de que arranquen (el lanzador la hace): dos jobs dividiendo a la vez podrían pisarse.
#   2. responde su parte -> data/lote/<entrada>/sub_N.jsonl, con checkpoint: si se cae o se acaba el tiempo,
#      relanzar el MISMO comando y sigue donde iba
#   3. resumen (líneas RESULTADO) y correo
# Con la estrategia y el corpus de config/responder.json (hoy razonada + data/index_base) una parte de 331
# preguntas tarda ~2 h (≈19 s por pregunta: cerradas ~23 s, semiabiertas ~14 s, abiertas ~53 s).
#
#     mkdir -p logs                                         # una sola vez
#     cp <archivo recibido> data/test_992.jsonl             # el MISMO archivo en todas las máquinas
#     bash jobs/lanzar_corrida.sh                           # hypatia: las 3 partes en paralelo (+ unión)
#     sbatch jobs/corrida.sh 2                              # o una sola parte (p. ej. para relanzarla)
#     bash jobs/corrida.sh 3                                # computador con GPU, sin Slurm (jobs/preparar_local.sh antes)
#     tail -f logs/corrida_p1_<id>.out
#
#   Prueba con la muestra (cada parte ~17 preguntas):
#     bash jobs/lanzar_corrida.sh data/sample_50.jsonl
#
# Si las partes corrieron en máquinas distintas: traer los sub_N.jsonl a data/lote/test_992/ de una sola y unir
# (valida contra el schema y lista los ids que faltan por parte):
#     scp <usuario>@<máquina>:<repo>/data/lote/test_992/sub_3.jsonl data/lote/test_992/
#     PYTHONPATH=. .venv-gpu/bin/python -m src.lote unir --preguntas data/test_992.jsonl \
#         --dir data/lote/test_992 --salida submissions.jsonl
#
# Verificación en vivo: data/lote/test_992/division.json dice en qué parte quedó cada id; regenerar con
# `python -m src.responder --id N --comparar submissions.jsonl` en la MISMA máquina que lo corrió.
#
# Variables: PYTHON (por defecto .venv-gpu/bin/python), OLIVIA_MODELO / OLIVIA_INDICE / OLIVIA_ESTRATEGIA /
# OLIVIA_ABIERTAS (sobrescriben config/responder.json), GCC_MODULE (igual que en jobs/servir.sh).

PARTE="${1:-${SLURM_ARRAY_TASK_ID:-}}"
PREGUNTAS="${2:-data/test_992.jsonl}"
LOTE="data/lote/$(basename "$PREGUNTAS" .jsonl)"     # una carpeta por entrada: la prueba no pisa la real

if [[ -z "${SLURM_JOB_ID:-}" ]]; then
    # Sin Slurm (computador con GPU): mismos logs que un job, también en pantalla.
    export SLURM_SUBMIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    export SLURM_JOB_NAME=corrida SLURM_JOB_ID="local$(date +%m%d%H%M%S)"
    LOCAL=1
    mkdir -p "$SLURM_SUBMIT_DIR/logs"
    exec > >(tee -a "$SLURM_SUBMIT_DIR/logs/corrida_${SLURM_JOB_ID}.out") \
        2> >(tee -a "$SLURM_SUBMIT_DIR/logs/corrida_${SLURM_JOB_ID}.err" >&2)
fi
source "$SLURM_SUBMIT_DIR/jobs/_comun.sh"
preparar_entorno
unset HF_TOKEN HUGGING_FACE_HUB_TOKEN    # los modelos son públicos y están en la caché: no hace falta token
ulimit -c 0      # sin core dumps: si ggml aborta, se ve su error y no el backtrace de gdb
if [[ -z "${LOCAL:-}" ]]; then
    cargar_cuda
    cargar_gcc
fi
PY="${PYTHON:-.venv-gpu/bin/python}"
py() { PYTHONPATH=. "$PY" "$@"; }

paso "0/3 verificando parte, entrada, índice, entorno y GPU"
[[ "$PARTE" =~ ^[1-3]$ ]] || { echo "ERROR: falta el número de parte (1, 2 o 3): sbatch jobs/corrida.sh N" >&2; ESTADO=2; }
# el índice y los chunks son los de config/responder.json (hoy data/index_base): se validan ESOS
IDX="$(py -c "import json; print(json.load(open('config/responder.json'))['indice'])" 2>/dev/null)"; IDX="${IDX:-data/index}"
CHUNKS="$(py -c "import json,sys; print(json.load(open(sys.argv[1]+'/index_config.json'))['chunks'])" "$IDX" 2>/dev/null)"
for f in "$PREGUNTAS" "$IDX/faiss.index" "$IDX/index_config.json" "$IDX/chunk_ids.json" \
         "${CHUNKS:-data/processed/chunks.parquet}" config/responder.json; do
    [[ -s "$f" ]] || { echo "ERROR: falta $f" >&2; ESTADO=2; }
done
echo "índice $IDX · chunks ${CHUNKS:-?} · config $(tr -d '\n ' < config/responder.json)"
[[ -x "$PY" ]] || { echo "ERROR: falta $PY (hypatia: jobs/instalar_torch_gpu.sh + instalar_responder.sh; PC: jobs/preparar_local.sh)" >&2; ESTADO=2; }
echo "parte $PARTE · entrada $PREGUNTAS · $(hostname) · commit $(git log -1 --oneline 2>/dev/null)"
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader || true
if [[ $ESTADO -eq 0 ]] && ! py -c "
import sys, torch, llama_cpp
ok = torch.cuda.is_available() and llama_cpp.llama_supports_gpu_offload()
print('torch', torch.__version__, '| GPU torch:', torch.cuda.is_available(),
      '| llama-cpp-python', llama_cpp.__version__, '| GPU llama:', llama_cpp.llama_supports_gpu_offload())
sys.exit(0 if ok else 1)"; then
    echo "ERROR: torch o llama.cpp no ven la GPU en $(hostname)" >&2
    ESTADO=3
fi

if [[ $ESTADO -eq 0 ]]; then
    paso "1/3 división de $PREGUNTAS en 3 partes"
    correr py -m src.lote dividir --preguntas "$PREGUNTAS" --partes 3 --dir "$LOTE"
fi

if [[ $ESTADO -eq 0 ]]; then
    paso "2/3 respondiendo la parte $PARTE (checkpoint en $LOTE/sub_${PARTE}.jsonl)"
    correr py -m src.lote correr --parte "$PARTE" --dir "$LOTE"
fi

paso "3/3 resumen"
ls -lh "$LOTE" 2>/dev/null
grep -E 'RESULTADO' "$OUT" 2>/dev/null | sed 's/^/  /'

enviar_resumen "corrida parte $PARTE"
exit "$ESTADO"
