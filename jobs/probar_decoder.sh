#!/usr/bin/env bash
#SBATCH --job-name=probar_decoder
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err
#SBATCH --mail-type=ALL
#SBATCH --mail-user=s.montoya112@uniandes.edu.co
#SBATCH --partition=gpu
#SBATCH --gres=gpu:1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=01:30:00
#
# Diagnóstico corto del decoder (llama.cpp) en .venv-gpu: prueba combinaciones de atención
# flash (on/off) y de uso previo/posterior de torch en la MISMA GPU, cada una en un proceso
# aparte, y escribe una línea "RESULTADO ..." por combinación. Sirve para ubicar un aborto
# que solo aparece cuando torch y llama.cpp comparten el proceso. Requiere
# `sbatch jobs/instalar_responder.sh` hecho (la compilación) y el modelo en la caché de HF.
#
#     sbatch jobs/probar_decoder.sh
#     grep RESULTADO logs/probar_decoder_<jobid>.out
source "$SLURM_SUBMIT_DIR/jobs/_comun.sh"
preparar_entorno
cargar_cuda
cargar_gcc

[[ -x .venv-gpu/bin/python ]] || { echo "ERROR: falta .venv-gpu" >&2; ESTADO=2; }

probar() {   # probar <nombre> <FLASH 0|1> <TORCH ninguno|antes|despues>
    local nombre="$1"
    echo "-- $nombre (flash=$2, torch=$3)"
    # OLIVIA_LLAMA_VERBOSE=1: sin él, llama.cpp calla el MOTIVO del "CUDA error" que aborta el proceso
    OLIVIA_LLAMA_VERBOSE=1 FLASH="$2" TORCH="$3" PYTHONPATH=. .venv-gpu/bin/python - <<'PY'
import os, time
import torch
from src.generacion.motor import Motor
from src.responder import cargar_config

def usar_torch():
    x = torch.randn(2048, 2048, device="cuda", dtype=torch.float16)
    return float((x @ x).float().sum())

cfg = cargar_config()
if os.environ["TORCH"] == "antes":
    usar_torch()
t0 = time.time()
motor = Motor(cfg["modelo"], n_ctx=2048, flash_attn=os.environ["FLASH"] == "1")
print(f"  decoder cargado en {time.time() - t0:.0f} s")
if os.environ["TORCH"] == "despues":
    usar_torch()
esq = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}
msgs = [[{"role": "user", "content": "Responde en JSON: {\"ok\": true}"}]]
print("  generación:", motor.generar_lote(msgs, [esq], max_tokens=20)[0])
PY
    local c=$?
    if [[ $c -eq 0 ]]; then echo "RESULTADO $nombre: OK"
    else echo "RESULTADO $nombre: FALLÓ (código $c)"; echo "ERROR: variante $nombre abortó con código $c" >&2; fi
}

if [[ $ESTADO -eq 0 ]]; then
    paso "variantes (cada una en un proceso aparte)"
    probar "V1 solo decoder, flash on"          1 ninguno
    probar "V2 solo decoder, flash off"         0 ninguno
    probar "V3 torch antes, flash on"           1 antes
    probar "V4 torch antes, flash off"          0 antes
    probar "V5 torch despues, flash on"         1 despues
    probar "V6 torch despues, flash off"        0 despues
    paso "resumen"
    grep -h "^RESULTADO" "$OUT" 2>/dev/null || true
fi

# El job se considera correcto si corrió; el veredicto está en las líneas RESULTADO.
[[ $ESTADO -eq 0 ]] || true
enviar_resumen probar_decoder
exit 0
