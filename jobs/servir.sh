#!/usr/bin/env bash
#SBATCH --job-name=servir
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err
#SBATCH --mail-type=ALL
#SBATCH --mail-user=s.montoya112@uniandes.edu.co
#SBATCH --partition=gpu
#SBATCH --gres=gpu:1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=04:00:00
#
# Levanta la interfaz (src/api.py) en un nodo con GPU: la página en "/" y POST /api/consulta.
# Los modelos (recuperación + decoder) se cargan al arrancar; el .out dice "listo" cuando se
# puede consultar. Requiere data/index/ (jobs/indice.sh) y haber corrido
# `sbatch jobs/instalar_responder.sh`. Desde la raíz del repo:
#
#     mkdir -p logs
#     sbatch jobs/servir.sh                  # puerto 8000; PUERTO=8100 sbatch jobs/servir.sh
#     tail -f logs/servir_<jobid>.out        # ahí aparece el nodo y el comando del túnel
#
# Para abrirla desde tu computador, en OTRA terminal local, el túnel SSH que imprime el .out:
#     ssh -L 8000:<nodo>:8000 <usuario>@<dirección de hypatia>
# y luego http://localhost:8000 en el navegador. Para parar: scancel <jobid>.
#
# Salidas: logs/servir_<id>.out (avance y consultas) y logs/servir_<id>.err (solo errores).
source "$SLURM_SUBMIT_DIR/jobs/_comun.sh"
preparar_entorno
cargar_cuda
cargar_gcc

PUERTO="${PUERTO:-8000}"
IDX="$(python3 -c "import json; print(json.load(open('config/responder.json'))['indice'])" 2>/dev/null)"; IDX="${IDX:-data/index}"
for f in "$IDX/faiss.index" "$IDX/index_config.json" config/responder.json; do
    [[ -s "$f" ]] || { echo "ERROR: falta $f" >&2; ESTADO=2; }
done
[[ -x .venv-gpu/bin/python ]] || { echo "ERROR: falta .venv-gpu (sbatch jobs/instalar_torch_gpu.sh)" >&2; ESTADO=2; }
if [[ $ESTADO -eq 0 ]] && ! .venv-gpu/bin/python -c "import llama_cpp, fastapi, uvicorn" 2>/dev/null; then
    echo "ERROR: .venv-gpu no tiene llama_cpp/fastapi: corran sbatch jobs/instalar_responder.sh" >&2
    ESTADO=4
fi

if [[ $ESTADO -eq 0 ]]; then
    NODO="$(hostname)"
    paso "interfaz en el nodo $NODO, puerto $PUERTO"
    echo "túnel (en tu computador):  ssh -L ${PUERTO}:${NODO}:${PUERTO} <usuario>@<dirección de hypatia>"
    echo "luego abre:                http://localhost:${PUERTO}"
    echo "(carga los modelos al arrancar; espera la línea 'listo')"
    PYTHONPATH=. correr .venv-gpu/bin/python -m src.api --host 0.0.0.0 --port "$PUERTO"
fi

enviar_resumen servir
exit "$ESTADO"
