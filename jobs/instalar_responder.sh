#!/usr/bin/env bash
#SBATCH --job-name=instalar_responder
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
# Deja .venv-gpu listo para responder en UN solo proceso (recuperación + generación):
#   - compila llama-cpp-python con CUDA 11.8 (arquitectura 75 = Turing) dentro de .venv-gpu,
#   - instala fastapi y uvicorn (src/api.py),
#   - prueba que torch y llama.cpp conviven en el mismo proceso y la misma GPU.
# No toca .venv-gen (el de la fase 7 por lotes). Requiere .venv-gpu: primero
# `sbatch jobs/instalar_torch_gpu.sh`. La prueba final baja el modelo de generación
# (config/responder.json, ~9 GB) la primera vez, así que necesita internet o la caché de HF.
#
#     mkdir -p logs
#     sbatch jobs/instalar_responder.sh
source "$SLURM_SUBMIT_DIR/jobs/_comun.sh"
preparar_entorno

paso "0/4 herramientas"
if [[ ! -x .venv-gpu/bin/python ]]; then
    echo "ERROR: no existe .venv-gpu: corran primero sbatch jobs/instalar_torch_gpu.sh" >&2
    ESTADO=2
fi
cargar_cuda
echo "CUDA_HOME: $CUDA_HOME"
echo "nvcc: $(nvcc --version 2>/dev/null | tail -1)"
echo "gcc:  $(gcc --version 2>/dev/null | head -1)   (CUDA 11.8 admite gcc hasta la 11)"
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader || true

if [[ $ESTADO -eq 0 ]]; then
    paso "1/4 compilando llama-cpp-python (CUDA) en .venv-gpu; ~10-20 min (sin caché de uv)"
    CMAKE_ARGS="-DGGML_CUDA=on -DCMAKE_CUDA_ARCHITECTURES=75" FORCE_CMAKE=1 \
    CMAKE_BUILD_PARALLEL_LEVEL=4 \
        correr uv pip install --quiet --no-cache --reinstall-package llama-cpp-python \
            --python .venv-gpu/bin/python llama-cpp-python
fi
if [[ $ESTADO -eq 0 ]]; then
    paso "2/4 fastapi y uvicorn"
    correr uv pip install --quiet --python .venv-gpu/bin/python -c .venv-gpu/constraints.txt \
        fastapi uvicorn
fi
if [[ $ESTADO -eq 0 ]]; then
    paso "3/4 dependencias de la librería compilada y prueba de importación (torch y llama_cpp juntos)"
    LIBLLAMA="$(find .venv-gpu -name 'libllama.so*' | head -1)"
    echo "libllama: ${LIBLLAMA:-NO ENCONTRADA}"
    [[ -n "$LIBLLAMA" ]] && { ldd "$LIBLLAMA" | grep -i "cud\|cublas\|not found" || true; }
    correr .venv-gpu/bin/python -c "
import torch, llama_cpp
print('torch', torch.__version__, '| GPU visible:', torch.cuda.is_available())
print('llama-cpp-python', llama_cpp.__version__, '| con GPU:', llama_cpp.llama_supports_gpu_offload())
import fastapi, uvicorn
print('fastapi', fastapi.__version__)"
fi
if [[ $ESTADO -eq 0 ]]; then
    paso "4/4 prueba de convivencia: decoder en la GPU + torch en el mismo proceso"
    PYTHONPATH=. correr .venv-gpu/bin/python - <<'PY'
import torch, time
from src.responder import cargar_config
from src.generacion.motor import Motor
cfg = cargar_config()
t0 = time.time()
motor = Motor(cfg["modelo"], n_ctx=cfg["n_ctx"])          # llama.cpp (CUDA)
print(f"decoder {cfg['modelo']} cargado en {time.time() - t0:.0f} s")
x = torch.randn(4096, 4096, device="cuda", dtype=torch.float16)  # torch (CUDA) en el mismo proceso
y = (x @ x).float().sum().item()
print("torch operando con el decoder cargado: ok", round(y) is not None)
msgs = [[{"role": "user", "content": "Responde en JSON: {\"ok\": true}"}]]
esq = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}
print("generación:", motor.generar_lote(msgs, [esq], max_tokens=20)[0])
print("memoria GPU usada (GB):", round(torch.cuda.memory_allocated() / 1e9, 2),
      "| total:", round(torch.cuda.get_device_properties(0).total_memory / 1e9, 1))
PY
fi

enviar_resumen instalar_responder
exit "$ESTADO"
