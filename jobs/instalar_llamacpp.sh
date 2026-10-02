#!/usr/bin/env bash
#SBATCH --job-name=instalar_llamacpp
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err
#SBATCH --mail-type=ALL
#SBATCH --mail-user=s.montoya112@uniandes.edu.co
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --gres=gpu:1
#SBATCH --partition=gpu
#SBATCH --time=01:30:00
#
# Compila llama-cpp-python con CUDA 11.8 en .venv-gen (una sola vez, ~10-20 min). Hace falta
# porque los nodos GPU de hypatia (Quadro RTX 6000, driver CUDA 11.8) no corren vLLM, y las
# ruedas precompiladas de llama-cpp-python ya no traen CUDA 11.8. La COMPILACIÓN no necesita
# GPU, pero el paso 3/3 (prueba de importación) sí: libllama.so queda enlazada contra
# libcuda.so.1 (el driver de NVIDIA), que solo existe en nodos con GPU física. Por eso el job
# pide --gres=gpu:1 igual que jobs/recuperar.sh.
#
#     mkdir -p logs
#     sbatch jobs/instalar_llamacpp.sh
#
# Después: sbatch jobs/generacion_bench.sh
source "$SLURM_SUBMIT_DIR/jobs/_comun.sh"
preparar_entorno

paso "0/3 herramientas"
cargar_cuda
cargar_gcc
echo "nvcc: $(nvcc --version 2>/dev/null | tail -1)"
echo "gcc:  $(gcc --version 2>/dev/null | head -1)   (CUDA 11.8 admite gcc hasta la 11)"
# libllama.so necesita std::filesystem (GCC >= 9); la libstdc++ del sistema (gcc 8.5,
# /usr/lib64/libstdc++.so.6.0.25) NO trae ese símbolo, así que se usa la de gcc 9.3.0 que
# instala OpenHPC en hypatia. El Python de `uv` también trae su propia libstdc++ vieja
# empaquetada: sin esto, el dynamic linker la encuentra primero y falla igual al importar.
export LD_LIBRARY_PATH="/opt/ohpc/pub/compiler/gcc/9.3.0/lib64:${LD_LIBRARY_PATH:-}"

if [[ $ESTADO -eq 0 ]]; then
    paso "1/3 entorno .venv-gen"
    rm -rf .venv-gen
    correr uv venv .venv-gen --python 3.12
fi
if [[ $ESTADO -eq 0 ]]; then
    paso "2/3 compilando llama-cpp-python (CUDA, arquitectura 75 = Turing)"
    CMAKE_ARGS="-DGGML_CUDA=on -DCMAKE_CUDA_ARCHITECTURES=75 -DGGML_CUDA_NO_VMM=ON" FORCE_CMAKE=1 \
    CMAKE_BUILD_PARALLEL_LEVEL=4 \
        correr uv pip install --no-cache --quiet --python .venv-gen/bin/python llama-cpp-python huggingface_hub pyarrow
fi
if [[ $ESTADO -eq 0 ]]; then
    paso "3/3 prueba de importación"
    correr .venv-gen/bin/python -c "import llama_cpp; print('llama-cpp-python', llama_cpp.__version__, '| con GPU:', llama_cpp.llama_supports_gpu_offload())"
fi

enviar_resumen instalar_llamacpp
exit "$ESTADO"
