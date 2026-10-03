#!/usr/bin/env bash
# Comando único de reproducción: responde las preguntas con el corpus y el índice congelados y deja el
# submissions.jsonl de la entrega. Desde la raíz del repo:
#
#     bash run.sh                          # las 992 preguntas de data/test_992.jsonl
#     PARTES=1 bash run.sh data/sample_50.jsonl   # las 50 de muestra (≈20 min con 1 GPU)
#
# Dónde corre:
#   * Con Slurm (hypatia): manda las partes como jobs de GPU en paralelo y un job final que las une
#     (jobs/lanzar_corrida.sh). Es asíncrono: sigan los jobs con `squeue -u $USER`.
#   * Sin Slurm (computador con GPU): corre las partes una tras otra y las une al final (jobs/corrida.sh en modo local).
# Resultado: data/lote/<entrada>/submissions.jsonl (cópienlo a submissions.jsonl para entregarlo).
#
# Variables:
#   PARTES=3           en cuántas partes se reparten las preguntas (una GPU por parte; la cola gpu de hypatia da 2 por usuario)
#   REHACER_INDICE=1   antes de responder, rehace chunking e índice del corpus base desde data/md
#                      (CORPUS=base de jobs/chunking.sh y jobs/indice.sh -> data/processed_base y data/index_base)
#   REHACER_CORPUS=1   además, vuelve a descargar el corpus (jobs/scrapper.sh y jobs/descargar_fuentes.sh); tarda horas
#   MODO=slurm|local   forzar el modo (por defecto: slurm si existe sbatch)
#   DRY_RUN=1          solo imprime lo que haría
#
# Requisitos: ver README.md (entorno .venv-gpu con torch cu118 y llama-cpp-python, GPU de 24 GB, modelos en la caché
# de Hugging Face, data/index_base + data/processed_base/chunks.parquet del enlace de "Corpus e índice").
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

PREGUNTAS="${1:-data/test_992.jsonl}"
NOMBRE="$(basename "$PREGUNTAS" .jsonl)"
LOTE="data/lote/$NOMBRE"
export PARTES="${PARTES:-3}"
REHACER_INDICE="${REHACER_INDICE:-0}"
REHACER_CORPUS="${REHACER_CORPUS:-0}"
DRY_RUN="${DRY_RUN:-0}"
PY="${PYTHON:-.venv-gpu/bin/python}"
if [[ -z "${MODO:-}" ]]; then command -v sbatch >/dev/null 2>&1 && MODO=slurm || MODO=local; fi
[[ "$REHACER_CORPUS" == "1" ]] && REHACER_INDICE=1

hacer() { if [[ "$DRY_RUN" == "1" ]]; then echo "[dry-run] $*"; else "$@"; fi; }

# enviar <args de sbatch>: manda el job con las variables de VARS (p. ej. CORPUS=base) y devuelve su id
# (en dry-run, un id ficticio).
VARS=""
enviar() {
    if [[ "$DRY_RUN" == "1" ]]; then echo "[dry-run] ${VARS:+$VARS }sbatch $*" >&2; echo "DRY$RANDOM"
    else env $VARS sbatch --parsable "$@"; fi
}

# ids_de <fuentes.json>: los doc_id que lista
ids_de() {
    local py="$PY"; [[ -x "$py" ]] || py=python3
    "$py" -c "import json,sys; print(*[o['doc_id'] for o in json.load(open(sys.argv[1], encoding='utf-8'))])" "$1"
}

echo "== reproducción: $PREGUNTAS · $PARTES partes · modo $MODO · rehacer índice=$REHACER_INDICE corpus=$REHACER_CORPUS"
if [[ "$DRY_RUN" != "1" ]]; then
    [[ -s "$PREGUNTAS" ]] || { echo "ERROR: falta $PREGUNTAS (copien el archivo de preguntas recibido a esa ruta)" >&2; exit 2; }
    [[ -x "$PY" || "$MODO" == "slurm" ]] || { echo "ERROR: falta $PY (entorno: jobs/preparar_local.sh o el README)" >&2; exit 2; }
fi

if [[ "$MODO" == "slurm" ]]; then
    hacer mkdir -p logs
    DEP=()
    if [[ "$REHACER_CORPUS" == "1" ]]; then
        # el scraper termina con errores en documentos que ya no existen: por eso afterany en los pasos de descarga
        VARS=""
        J=$(enviar jobs/scrapper.sh --enlaces data/enlaces.txt)
        VARS="REINDEXAR=0"
        J=$(enviar --dependency="afterany:$J" jobs/descargar_fuentes.sh data/enriquecimiento/test_992/fuentes.json)
        J=$(enviar --dependency="afterany:$J" jobs/descargar_fuentes.sh data/enriquecimiento/test_992/fuentes_alternativas.json)
        DEP=(--dependency="afterany:$J")
    fi
    if [[ "$REHACER_INDICE" == "1" ]]; then
        VARS="CORPUS=base"
        J1=$(enviar ${DEP[@]+"${DEP[@]}"} jobs/chunking.sh)
        J2=$(enviar --dependency="afterok:$J1" jobs/indice.sh)
        export ESPERAR="$J2"      # las partes arrancan al terminar el índice
        [[ "$DRY_RUN" == "1" ]] && echo "[dry-run] ESPERAR=$ESPERAR"
    fi
    hacer bash jobs/lanzar_corrida.sh "$PREGUNTAS"
    echo "== enviado. Al terminar la unión: $LOTE/submissions.jsonl  ->  cp $LOTE/submissions.jsonl submissions.jsonl"
else
    if [[ "$REHACER_CORPUS" == "1" ]]; then
        hacer env PYTHONPATH=. "$PY" -m src.descarga.seed_a_fuentes
        hacer env PYTHONPATH=. "$PY" -m src.descarga.run --enlaces data/enlaces.txt
        hacer env PYTHONPATH=. "$PY" -m src.descarga.run --enlaces data/enlaces.txt --solo-fallidos
        for f in fuentes fuentes_alternativas; do
            hacer env PYTHONPATH=. "$PY" -m src.descarga.run \
                --fuentes data/fuentes_seed.json data/fuentes_propias.json "data/enriquecimiento/test_992/$f.json" \
                --enlaces data/enlaces.txt --solo $(ids_de "data/enriquecimiento/test_992/$f.json")
        done
    fi
    if [[ "$REHACER_INDICE" == "1" ]]; then
        hacer env PYTHONPATH=. "$PY" -m src.procesamiento.build --salida data/processed_base \
            --excluir-origen ronda_01 ronda_02 ronda_03 ronda_04
        hacer env PYTHONPATH=. "$PY" -m src.indice.build --chunks data/processed_base/chunks.parquet --salida data/index_base
    fi
    for n in $(seq 1 "$PARTES"); do
        hacer bash jobs/corrida.sh "$n" "$PREGUNTAS"
    done
    hacer env PYTHONPATH=. "$PY" -m src.lote unir --preguntas "$PREGUNTAS" --dir "$LOTE" --salida "$LOTE/submissions.jsonl"
    echo "== listo: $LOTE/submissions.jsonl  ->  cp $LOTE/submissions.jsonl submissions.jsonl"
fi
