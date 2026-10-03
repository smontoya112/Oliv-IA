# Oliv-IA

Sistema RAG de derecho colombiano para la Hackathon 2026 (Uniandes, AI Week). Las demás
secciones del README (corpus e índice, reproducibilidad) siguen la plantilla de
`entregables/sabado/README_EQUIPO.md`.

## Interfaz y verificación en vivo

Todo corre en un nodo con GPU de Hypatia. Recuperación (fase 6) y generación (fase 7)
comparten un solo proceso y el entorno `.venv-gpu`.

**Preparación (una sola vez)**

```bash
mkdir -p logs
sbatch jobs/instalar_torch_gpu.sh      # torch para CUDA 11.8
sbatch jobs/instalar_responder.sh      # llama.cpp + FastAPI en ese entorno, y prueba de convivencia
```

**Interfaz web**

```bash
sbatch jobs/servir.sh                  # levanta src/api.py; PUERTO=8100 para otro puerto
tail -f logs/servir_<jobid>.out        # ahí salen el nodo y el comando del túnel
```

En otra terminal de tu computador abre el túnel que imprime el `.out`
(`ssh -L 8000:<nodo>:8000 <usuario>@<hypatia>`) y entra a http://localhost:8000. Cada respuesta
muestra el texto, las normas citadas (en naranja las que ningún pasaje respalda), las fuentes
recuperadas y un aviso si el sistema se abstuvo. La API es `POST /api/consulta` con
`{"pregunta": "...", "formato": opcional, "opciones": opcional}`; sin `formato` se deduce del
texto (con opciones A) B) C) es cerrada; un caso largo es abierta; el resto, semiabierta).

**Verificación en vivo (jurado)**

```bash
srun --mem=32gb --time=00:30:00 --gres=gpu:1 -p gpu --pty bash -i
module load cuda/11.8
PYTHONPATH=. .venv-gpu/bin/python -m src.responder --id 512
PYTHONPATH=. .venv-gpu/bin/python -m src.responder --id 512 --comparar submissions.jsonl
```

`--id` busca la pregunta en `data/test_992.jsonl` y luego en `data/sample_50.jsonl`.
`--comparar` regenera la respuesta y la contrasta con la línea de `submissions.jsonl`: normas
citadas, pasajes recuperados (y su orden) y respuesta. Sale con código 0 si coinciden las normas
y los pasajes. El modelo del decoder se cambia en `config/responder.json` (o con `OLIVIA_MODELO`).
