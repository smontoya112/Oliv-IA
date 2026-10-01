#!/usr/bin/env bash
#SBATCH --job-name=instalar_torch_gpu
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err
#SBATCH --mail-type=ALL
#SBATCH --mail-user=s.montoya112@uniandes.edu.co
#SBATCH --partition=gpu
#SBATCH --gres=gpu:1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=00:40:00
#
# Crea .venv-gpu con PyTorch para CUDA 11.8. Los nodos GPU de hypatia tienen driver
# 520.61.05 (CUDA 11.8) y el torch del proyecto (PyPI, 2.14, CUDA 12) no ve la GPU con ese
# driver: torch.cuda.is_available() da False. PyTorch publicó ruedas cu118 hasta la 2.7.1.
# Lo usan jobs/indice.sh (pasos 5.2 y 5.5: encoder bge-m3 en GPU) y la fase 6 (reranker).
# Corre en un nodo GPU para poder comprobar al final que torch ve la tarjeta.
#
#     mkdir -p logs
#     sbatch jobs/instalar_torch_gpu.sh
source "$SLURM_SUBMIT_DIR/jobs/_comun.sh"
preparar_entorno

paso "1/4 entorno .venv-gpu (se recrea)"
rm -rf .venv-gpu
correr uv venv .venv-gpu --python 3.12

if [[ $ESTADO -eq 0 ]]; then
    paso "2/4 torch 2.7.1 + CUDA 11.8"
    correr uv pip install --quiet --python .venv-gpu/bin/python --index-url https://download.pytorch.org/whl/cu118 \
        torch==2.7.1
fi
if [[ $ESTADO -eq 0 ]]; then
    paso "3/4 resto de dependencias de src/indice (torch queda fijado en 2.7.1)"
    echo "torch==2.7.1" > .venv-gpu/constraints.txt     # si algo exigiera otro torch, falla en vez de cambiarlo
    correr uv pip install --quiet --python .venv-gpu/bin/python -c .venv-gpu/constraints.txt \
        "transformers>=4.56,<5" faiss-cpu bm25s ranx numpy pyarrow huggingface_hub PyStemmer pyyaml
fi
if [[ $ESTADO -eq 0 ]]; then
    paso "4/4 prueba: ¿torch ve la GPU?"
    nvidia-smi --query-gpu=name,driver_version --format=csv,noheader
    correr .venv-gpu/bin/python -c "
import torch, sys
print('torch', torch.__version__, '| cuda', torch.version.cuda, '| GPU visible:', torch.cuda.is_available())
sys.exit(0 if torch.cuda.is_available() else 1)"
fi

enviar_resumen instalar_torch_gpu
exit "$ESTADO"
