#!/usr/bin/env bash
#SBATCH --job-name=scraper_proximidad
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err
#SBATCH --mail-type=ALL
#SBATCH --mail-user=s.montoya112@uniandes.edu.co
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=32G
#SBATCH --time=12:00:00
#
# Enriquece el corpus de forma RECURSIVA: en cada ronda descarga TODAS las normas que figuran
# en data/descubiertos.csv (las que los documentos ya descargados enlazan y todavía no están en
# el corpus); al terminar la ronda, run.py recalcula descubiertos.csv con los enlaces de lo recién
# bajado y eso alimenta la ronda siguiente. Por defecto 4 rondas.
#
#     mkdir -p logs            # una sola vez
#     sbatch jobs/scraper_proximidad.sh                        # 4 rondas, todos los descubiertos
#     sbatch jobs/scraper_proximidad.sh --rondas 2             # solo 2 rondas
#     sbatch jobs/scraper_proximidad.sh --minimo 2             # solo los enlazados más de 2 veces
#     sbatch jobs/scraper_proximidad.sh --max-por-ronda 1500   # tope de links por ronda (los más enlazados)
#   Lo demás se pasa a `run` (p. ej. --sin-robots).
#
# Requiere haber corrido jobs/scrapper.sh (de ahí sale descubiertos.csv). Es REANUDABLE: lo que ya
# está en el manifest no se vuelve a pedir; si el job se corta por tiempo, se relanza igual y retoma.
# El ciclo se detiene antes si una ronda no encuentra links nuevos (convergió).
#
# Dónde queda todo:
#   data/proximidad/ronda_NN.txt     los links nuevos de cada ronda
#   data/enlaces_proximidad.txt      acumulado de todas las rondas (jobs/scrapper.sh también lo carga)
#   data/raw, data/md, data/corpus_manifest.json   igual que el resto del corpus; cada documento
#                                    nuevo lleva "origen": "ronda_NN" en el manifest
# Después hay que repetir jobs/chunking.sh y jobs/indice.sh para que el índice incluya lo nuevo.
#
# Salidas: logs/scraper_proximidad_<id>.out (avance) y .err (solo errores).
source "$SLURM_SUBMIT_DIR/jobs/_comun.sh"
preparar_entorno

RONDAS=4
MINIMO=0
MAXIMO=0
ARGS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --rondas)         RONDAS="$2"; shift 2 ;;
        --minimo)         MINIMO="$2"; shift 2 ;;
        --max-por-ronda)  MAXIMO="$2"; shift 2 ;;
        *)                ARGS+=("$1"); shift ;;
    esac
done

if [[ ! -s data/descubiertos.csv ]]; then
    echo "ERROR: falta data/descubiertos.csv: corran primero jobs/scrapper.sh" >&2
    ESTADO=2
fi
echo "rondas: $RONDAS · veces_enlazada > $MINIMO · tope por ronda: ${MAXIMO/#0/sin tope}"

RONDAS_HECHAS=0
for ((R = 1; R <= RONDAS && ESTADO == 0; R++)); do
    ARCHIVO="$(printf 'data/proximidad/ronda_%02d.txt' "$R")"
    paso "ronda $R/$RONDAS: links nuevos de descubiertos.csv"
    correr uvpy -m src.descarga.proximidad --ronda "$R" --minimo "$MINIMO" --max "$MAXIMO"
    [[ $ESTADO -ne 0 ]] && break
    N="$(grep -vc '^#' "$ARCHIVO" || true)"
    if [[ "${N:-0}" -eq 0 ]]; then
        echo "ronda $R: no hay links nuevos: el ciclo convergió, no hacen falta más rondas"
        break
    fi

    paso "ronda $R/$RONDAS: descargando $N links"
    correr uvpy -m src.descarga.run --solo-enlaces --enlaces "$ARCHIVO" "${ARGS[@]}"
    paso "ronda $R/$RONDAS: reintento de los que fallaron"
    correr uvpy -m src.descarga.run --solo-enlaces --enlaces "$ARCHIVO" --solo-fallidos "${ARGS[@]}"
    paso "ronda $R/$RONDAS: estado del corpus"
    resumen_manifest
    echo "descubiertos para la siguiente ronda: $(( $(wc -l < data/descubiertos.csv) - 1 ))"
    RONDAS_HECHAS=$R
done

paso "resumen final: $RONDAS_HECHAS ronda(s) completa(s)"
resumen_manifest
uvpy - <<'PY'
import json, collections
m = json.load(open('data/corpus_manifest.json', encoding='utf-8'))
c = collections.Counter((r.get('origen') or 'inicial') for r in m if r.get('estado') == 'ok')
print('documentos ok por origen:', dict(sorted(c.items())))
PY

enviar_resumen scraper_proximidad
exit "$ESTADO"
