#!/usr/bin/env bash
# Experimentos de la rama prueba-claude. NO es un job de Slurm: corre dentro de una asignación de GPU ya
# reservada (salloc/sbatch --wrap "sleep ...") con
#
#     srun --jobid=<ID> --overlap bash jobs/exp_claude.sh <subcomando> ...
#
# Subcomandos (todos escriben bajo data/exp/ y experimentos/claude/, nunca sobre data/index ni
# data/processed/chunks.parquet):
#   corpus_base                                   chunking sin rondas de proximidad + índice data/index_base
#   recuperar <nombre> <indice> [flags]           fase 6 sobre sample_50 -> data/exp/recuperacion/<nombre>.jsonl
#                                                 y su tabla (data/exp/recuperacion/<nombre>_eval.json)
#   contexto <nombre>                             pasajes de esa recuperación -> data/exp/contexto_<nombre>.json
#   bench <etiqueta> <modelo> <estrategia> <contexto> [formatos...]
#                                                 genera sample_50 -> data/exp/bench/<etiqueta>.jsonl
#   resumen <etiqueta>                            métricas -> experimentos/claude/<etiqueta>/metricas.json
#
# Variables útiles: OLIVIA_POLITICA_CERRADAS, OLIVIA_MAX_PENSAR, OLIVIA_FLASH_ATTN, INDICE (para bench: índice del
# catálogo de la fase 8; por defecto data/index). El HF_TOKEN se borra del entorno: los modelos públicos no lo necesitan.
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RAIZ" || exit 2
export SLURM_SUBMIT_DIR="$RAIZ" SLURM_JOB_NAME="${SLURM_JOB_NAME:-exp}" SLURM_JOB_ID="${SLURM_JOB_ID:-exp$$}"
source "$RAIZ/jobs/_comun.sh"
module load python 2>/dev/null || true
export PATH="$HOME/.local/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONWARNINGS=ignore
unset HF_TOKEN HUGGING_FACE_HUB_TOKEN
ulimit -c 0
cargar_cuda
cargar_gcc
PY="${PYTHON:-.venv-gpu/bin/python}"
py() { PYTHONPATH=. "$PY" "$@"; }
INDICE="${INDICE:-data/index}"
mkdir -p data/exp/recuperacion data/exp/bench logs experimentos/claude

cmd="${1:?uso: exp_claude.sh <subcomando> ...}"; shift
case "$cmd" in
  corpus_base)
    paso "chunking sin rondas de proximidad -> data/processed_base"
    py -m src.procesamiento.build --salida data/processed_base --excluir-origen ronda_01 ronda_02 ronda_03 ronda_04 || exit $?
    paso "índice -> data/index_base (bge-m3, GPU)"
    py -m src.indice.build --chunks data/processed_base/chunks.parquet --salida data/index_base || exit $?
    grep -E '"n_chunks"|sha256' data/index_base/index_config.json
    ;;
  recuperar)
    nombre="${1:?nombre}"; indice="${2:?indice}"; shift 2
    py -m src.recuperacion.pipeline --preguntas data/sample_50.jsonl --indice "$indice" \
        --salida "data/exp/recuperacion/${nombre}.jsonl" "$@" || exit $?
    py -m src.recuperacion.evaluar "data/exp/recuperacion/${nombre}.jsonl" \
        --salida "data/exp/recuperacion/${nombre}_eval.json" || exit $?
    grep -E '"(cuerpo|articulo|hit_doc)@10"|cobertura_opciones' "data/exp/recuperacion/${nombre}_eval.json" | head -8
    ;;
  contexto)
    nombre="${1:?nombre}"
    py -m src.generacion.contexto_prueba --modo recuperacion \
        --entrada "data/exp/recuperacion/${nombre}.jsonl" --salida "data/exp/contexto_${nombre}.json"
    ;;
  bench)
    etiqueta="${1:?etiqueta}"; modelo="${2:?modelo}"; estrategia="${3:?estrategia}"; contexto="${4:?contexto}"; shift 4
    formatos=("$@"); [[ ${#formatos[@]} -eq 0 ]] && formatos=(multiple_choice semi_open open_ended)
    nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv,noheader
    py -m src.generacion.bench --modelo "$modelo" --estrategia "$estrategia" --etiqueta "$etiqueta" \
        --contexto "data/exp/contexto_${contexto}.json" --salida data/exp/bench --csv data/exp/bench.csv \
        --catalogo "$INDICE" --formatos "${formatos[@]}"
    ;;
  resumen)
    etiqueta="${1:?etiqueta}"
    py -m src.analisis.resumen_corrida --submission "data/exp/bench/${etiqueta}.jsonl" \
        --salida "experimentos/claude/${etiqueta}/metricas.json" --csv data/exp/bench.csv --etiqueta "$etiqueta"
    ;;
  *) echo "subcomando desconocido: $cmd" >&2; exit 2 ;;
esac
