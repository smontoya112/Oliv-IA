#!/usr/bin/env bash
#SBATCH --job-name=indice
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err
#SBATCH --mail-type=ALL
#SBATCH --mail-user=s.montoya112@uniandes.edu.co
#SBATCH --partition=gpu
#SBATCH --gres=gpu:1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=02:00:00
#
# Fase 5 (src/indice): data/processed/chunks.parquet -> data/index/
#     faiss.index + embeddings.npy (bge-m3), bm25/, chunk_ids.json, index_config.json
#     y la evaluación de recuperación eval_recuperacion.json (Recall@10/@50 sobre sample_50).
# Necesita GPU: con ~60k chunks el encoding en CPU tarda horas. Desde la raíz del repo:
#
#     git pull                 # chunks.parquet y código al día
#     sbatch jobs/instalar_torch_gpu.sh   # UNA vez: torch para el driver CUDA 11.8 (.venv-gpu)
#     mkdir -p logs            # una sola vez
#     sinfo -s                 # ver el nombre de la partición con GPU; si no es "gpu":
#     sbatch -p <particion> jobs/indice.sh            # (-p en la línea de comandos manda)
#     sbatch jobs/indice.sh --solo denso             # argumentos extra van a src.indice.build
#     sbatch jobs/indice.sh --batch 64               # si la GPU se queda sin memoria
#   Si el cluster pide cuenta: sbatch -A <cuenta> jobs/indice.sh
#
# Qué devolver al equipo cuando termine (asunto del correo: "[indice] Terminó OK"):
#   * por git:   data/index/index_config.json, data/index/eval_recuperacion.json,
#                logs/indice_<id>.out y logs/indice_<id>.err
#   * por la carpeta compartida (no van a git, ~400 MB): data/index/faiss.index,
#                data/index/embeddings.npy, data/index/chunk_ids.json y la carpeta data/index/bm25/
#     El sha256 de faiss.index queda en index_config.json para verificar la copia.
#
# Salidas: logs/indice_<id>.out (avance y resultados) y logs/indice_<id>.err (solo errores).
source "$SLURM_SUBMIT_DIR/jobs/_comun.sh"
preparar_entorno

# Los nodos GPU de hypatia tienen driver CUDA 11.8: el torch del proyecto (CUDA 12) no ve la
# GPU. Si existe .venv-gpu (sbatch jobs/instalar_torch_gpu.sh) se usa ese entorno.
if [[ -x .venv-gpu/bin/python ]]; then
    echo "usando .venv-gpu (torch para CUDA 11.8)"
    uvpy() { PYTHONPATH=. .venv-gpu/bin/python "$@"; }
else
    echo "AVISO: no hay .venv-gpu; se usa el torch del proyecto (puede no ver la GPU)" >&2
fi

# Revisión fijada del modelo: debe coincidir con src/indice/encoder.py (REVISION).
MODELO="BAAI/bge-m3"
REVISION="5617a9f61b028005a4858fdac845db406aefb181"

paso "0/4 verificando chunks y GPU"
if [[ ! -s data/processed/chunks.parquet ]]; then
    echo "ERROR: no existe data/processed/chunks.parquet (git pull o sbatch jobs/chunking.sh)" >&2
    ESTADO=2
fi
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader || true
if [[ $ESTADO -eq 0 ]] && ! uvpy -c "import torch, sys; sys.exit(0 if torch.cuda.is_available() else 1)"; then
    echo "ERROR: torch no ve ninguna GPU en $(hostname); revisen --partition/--gres (no se corre en CPU)" >&2
    ESTADO=3
fi

if [[ $ESTADO -eq 0 ]]; then
    paso "1/4 descargando $MODELO@${REVISION:0:8} (si ya está en la caché de HF no baja nada)"
    correr uvpy - "$MODELO" "$REVISION" <<'PY'
import sys
from huggingface_hub import snapshot_download
ruta = snapshot_download(sys.argv[1], revision=sys.argv[2],
                         allow_patterns=["config.json", "pytorch_model.bin", "tokenizer*",
                                         "sentencepiece.bpe.model", "special_tokens_map.json"])
print("modelo en", ruta)
PY
fi

if [[ $ESTADO -eq 0 ]]; then
    paso "2/4 construyendo índices (BM25 + FAISS)"
    correr uvpy -m src.indice.build "$@"
fi

if [[ $ESTADO -eq 0 ]]; then
    paso "3/4 evaluando recuperación sobre data/sample_50.jsonl"
    correr uvpy -m src.indice.evaluar
fi

paso "4/4 resumen"
ls -lh data/index 2>/dev/null
grep -E '^(chunks:|textos únicos|FAISS|BM25|ítems:|RESULTADO|n_chunks)' "$OUT" 2>/dev/null | sed 's/^/  /'

enviar_resumen indice
exit "$ESTADO"
