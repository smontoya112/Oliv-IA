#!/usr/bin/env bash
#SBATCH --job-name=chunking
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err
#SBATCH --mail-type=ALL
#SBATCH --mail-user=s.montoya112@uniandes.edu.co
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=16G
#SBATCH --time=02:00:00
#
# Limpieza y chunking de TODOS los data/md/*.md (src/procesamiento/build.py):
#     data/md/*.md  ->  data/processed/chunks.parquet, articulos.parquet,
#                       reporte_segmentacion.json y texto/<doc_id>.txt
# Hay que haber corrido antes jobs/scrapper.sh (de ahí salen los md). Desde la raíz:
#
#     mkdir -p logs            # una sola vez
#     sbatch jobs/chunking.sh
#     sbatch jobs/chunking.sh --doc ley_80_1993 codigo_civil   # solo esos doc_id (a build.py tal cual)
#     sbatch jobs/chunking.sh --excluir-origen ronda_03 ronda_04   # sin esas rondas de proximidad
#     CORPUS=base sbatch jobs/chunking.sh      # el corpus de config/responder.json: sin las rondas de
#                                              # proximidad (ronda_01..04) -> data/processed_base/
#                                              # (con las normas de las preguntas, origen preguntas_*)
#
# Nota: num_tokens solo se llena si el tokenizer de bge-m3 ya está en la caché de Hugging
# Face del nodo (build.py trabaja en modo offline); si no, queda vacío y no afecta el resto.
#
# Salidas: logs/chunking_<id>.out (avance y resultados) y logs/chunking_<id>.err (solo errores).
source "$SLURM_SUBMIT_DIR/jobs/_comun.sh"
preparar_entorno

# Intérprete: PYTHON si se da; en un clon ligero sin .venv (hypatia: enlaces a .venv-gpu) se usa .venv-gpu en vez
# de `uv run`, que intentaría instalar todo el proyecto.
if [[ -n "${PYTHON:-}" ]]; then uvpy() { PYTHONPATH=. "$PYTHON" "$@"; }
elif [[ ! -d .venv && -x .venv-gpu/bin/python ]]; then uvpy() { PYTHONPATH=. .venv-gpu/bin/python "$@"; }; fi

SALIDA="data/processed"
if [[ "${CORPUS:-}" == "base" ]]; then
    SALIDA="data/processed_base"
    set -- --salida "$SALIDA" --excluir-origen ronda_01 ronda_02 ronda_03 ronda_04 "$@"
fi
echo "salida: $SALIDA"

paso "0/2 verificando data/md"
N_MD=$(ls data/md/*.md 2>/dev/null | grep -vc '\.notas\.md$')
echo "documentos md: $N_MD"
if [[ "$N_MD" -eq 0 ]]; then
    echo "ERROR: no hay data/md/*.md (corran jobs/scrapper.sh o hagan git pull)" >&2
    ESTADO=2
fi

if [[ $ESTADO -eq 0 ]]; then
    paso "1/2 chunking de todos los md"
    correr uvpy -m src.procesamiento.build "$@"
    paso "2/2 resumen"
    uvpy - "$SALIDA" <<'PY'
import json, sys
r = json.load(open(sys.argv[1] + '/reporte_segmentacion.json', encoding='utf-8'))
t = r['total']
print('documentos:', len(r['documentos']))
print('chunks:', t['n_chunks'], '| sobre el límite:', len(t['sobre_limite']),
      '| duplicados exactos:', len(t['duplicados_exactos']), '| con residuos:', len(t['alerta_residuos']))
PY
fi

enviar_resumen chunking
exit "$ESTADO"
