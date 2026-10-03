#!/usr/bin/env bash
#
# Prepara un computador Linux con GPU NVIDIA (fuera de hypatia) para correr una parte de la
# corrida ciega (jobs/corrida.sh 3). Hacerlo HOY: compila llama.cpp y baja ~14 GB de modelos.
#   1. revisa herramientas: nvidia-smi, nvcc (CUDA toolkit, para compilar llama.cpp), uv, git
#   2. crea .venv-gpu con las MISMAS versiones que hypatia (torch 2.7.1, transformers 4.57.6,
#      faiss-cpu 1.15.1, bm25s 0.3.11): así la recuperación da los mismos pasajes
#   3. compila llama-cpp-python con CUDA (misma versión que hypatia: LLAMA_CPP_VERSION)
#   4. revisa que estén el índice congelado y chunks.parquet (se copian de hypatia, no van en git)
#   5. prueba de punta a punta con una pregunta de la muestra (baja bge-m3, el reranker y el GGUF)
#
# Desde la raíz del repo (rama con src/lote.py), en el computador con GPU:
#     # índice y chunks desde hypatia (~2 GB; el mismo índice congelado que usan las partes 1 y 2):
#     rsync -avP <usuario>@<hypatia>:<repo>/data/index/ data/index/
#     rsync -avP <usuario>@<hypatia>:<repo>/data/processed/chunks.parquet data/processed/
#     bash jobs/preparar_local.sh
#
# Variables: LLAMA_CPP_VERSION (por defecto la de hypatia; verla allá con
#   `.venv-gpu/bin/python -c "import llama_cpp; print(llama_cpp.__version__)"`),
#   CUDA_ARCH (por defecto "native" = la GPU de este equipo), TORCH_INDEX (índice de ruedas de
#   torch si el driver es viejo, p. ej. https://download.pytorch.org/whl/cu118).
set -u
cd "$(dirname "${BASH_SOURCE[0]}")/.."
mkdir -p logs
LOG="logs/preparar_local_$(date +%m%d%H%M%S)"
exec > >(tee -a "$LOG.out") 2> >(tee -a "$LOG.err" >&2)
ESTADO=0
paso() { echo "== $*"; }
correr() { "$@" || { local c=$?; echo "ERROR: '$*' terminó con código $c" >&2; ESTADO=$c; }; }
LLAMA_CPP_VERSION="${LLAMA_CPP_VERSION:-0.3.36}"
CUDA_ARCH="${CUDA_ARCH:-native}"
PY=.venv-gpu/bin/python

paso "1/5 herramientas"
for h in nvidia-smi nvcc uv git cmake; do
    command -v "$h" >/dev/null || { echo "ERROR: falta $h en el PATH" >&2; ESTADO=2; }
done
command -v nvcc >/dev/null || echo "  (nvcc viene con el CUDA toolkit: sudo apt install nvidia-cuda-toolkit o el instalador de NVIDIA; también CUDACXX=/usr/local/cuda/bin/nvcc)" >&2
command -v uv >/dev/null || echo "  (uv: curl -LsSf https://astral.sh/uv/install.sh | sh)" >&2
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader 2>/dev/null
nvcc --version 2>/dev/null | tail -1
echo "commit: $(git log -1 --oneline 2>/dev/null)"

if [[ $ESTADO -eq 0 ]]; then
    paso "2/5 .venv-gpu con las versiones de hypatia"
    [[ -x $PY ]] || correr uv venv .venv-gpu --python 3.12
    TORCH_ARGS=(); [[ -n "${TORCH_INDEX:-}" ]] && TORCH_ARGS=(--index-url "$TORCH_INDEX")
    correr uv pip install --quiet --python $PY "${TORCH_ARGS[@]}" torch==2.7.1
    echo "torch==2.7.1" > .venv-gpu/constraints.txt
    correr uv pip install --quiet --python $PY -c .venv-gpu/constraints.txt \
        transformers==4.57.6 faiss-cpu==1.15.1 bm25s==0.3.11 ranx numpy pyarrow==25.0.1 \
        huggingface_hub PyStemmer pyyaml fastapi uvicorn
fi

if [[ $ESTADO -eq 0 ]]; then
    paso "3/5 llama-cpp-python $LLAMA_CPP_VERSION con CUDA (arquitectura $CUDA_ARCH); ~10-20 min"
    if $PY -c "import llama_cpp, sys; sys.exit(0 if llama_cpp.__version__ == '$LLAMA_CPP_VERSION' and llama_cpp.llama_supports_gpu_offload() else 1)" 2>/dev/null; then
        echo "ya está compilado con GPU"
    else
        CMAKE_ARGS="-DGGML_CUDA=on -DCMAKE_CUDA_ARCHITECTURES=$CUDA_ARCH" FORCE_CMAKE=1 \
        CMAKE_BUILD_PARALLEL_LEVEL="$(nproc)" \
            correr uv pip install --quiet --no-cache --reinstall-package llama-cpp-python \
                --python $PY "llama-cpp-python==$LLAMA_CPP_VERSION"
    fi
    correr $PY -c "
import sys, torch, llama_cpp
print('torch', torch.__version__, '| GPU torch:', torch.cuda.is_available())
print('llama-cpp-python', llama_cpp.__version__, '| GPU llama:', llama_cpp.llama_supports_gpu_offload())
sys.exit(0 if torch.cuda.is_available() and llama_cpp.llama_supports_gpu_offload() else 1)"
fi

paso "4/5 índice congelado y chunks (copiados de hypatia)"
for f in data/index/faiss.index data/index/index_config.json data/index/chunk_ids.json \
         data/processed/chunks.parquet; do
    [[ -s "$f" ]] || { echo "ERROR: falta $f (rsync desde hypatia, ver la cabecera)" >&2; ESTADO=2; }
done
[[ -d data/index/bm25 ]] || { echo "ERROR: falta data/index/bm25/" >&2; ESTADO=2; }
if [[ $ESTADO -eq 0 ]]; then
    correr $PY - <<'PY'
import hashlib, json
cfg = json.load(open("data/index/index_config.json", encoding="utf-8"))
def sha(r):
    h = hashlib.sha256()
    with open(r, "rb") as f:
        for b in iter(lambda: f.read(1 << 24), b""):
            h.update(b)
    return h.hexdigest()
ok = sha(cfg["chunks"]) == cfg["sha256_chunks"] and sha("data/index/faiss.index") == cfg["denso"]["sha256_faiss"]
print("sha256 de chunks.parquet y faiss.index:", "coinciden con index_config.json" if ok else "NO coinciden")
raise SystemExit(0 if ok else 1)
PY
fi

if [[ $ESTADO -eq 0 ]]; then
    paso "5/5 prueba de punta a punta (id 51 de la muestra; la primera vez baja los modelos)"
    PYTHONPATH=. correr $PY -m src.responder --id 51 --preguntas data/sample_50.jsonl
fi

echo "== fin: $([[ $ESTADO -eq 0 ]] && echo 'LISTO: mañana bash jobs/corrida.sh 3' || echo "FALLÓ (código $ESTADO), ver $LOG.err") · $(date '+%F %T')"
exit "$ESTADO"
