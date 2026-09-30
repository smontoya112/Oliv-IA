#!/usr/bin/env bash
#SBATCH --job-name=scraper_proximidad
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err
#SBATCH --mail-type=ALL
#SBATCH --mail-user=s.montoya112@uniandes.edu.co
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=32G
#SBATCH --time=04:00:00
#
# Descarga las normas "vecinas": las que los documentos del corpus enlazan más de 2 veces
# (data/descubiertos.csv, columna veces_enlazada > 2) y que todavía no están en el corpus.
# Requiere haber corrido antes jobs/scrapper.sh (de ahí sale descubiertos.csv). Desde la raíz:
#
#     mkdir -p logs            # una sola vez
#     sbatch jobs/scraper_proximidad.sh
#     sbatch jobs/scraper_proximidad.sh --minimo 5    # otro umbral: veces_enlazada > 5
#
# Al terminar, run.py recalcula descubiertos.csv sin lo ya descargado: volver a lanzar el job
# avanza al siguiente anillo de normas. Los links quedan en data/enlaces_proximidad.txt, que
# jobs/scrapper.sh también carga, así el corpus completo los incluye.
#
# Salidas: logs/scraper_proximidad_<id>.out (avance) y .err (solo errores).
source "$SLURM_SUBMIT_DIR/jobs/_comun.sh"
preparar_entorno

# Único argumento propio: --minimo N. Lo demás se pasa a `run`.
MINIMO=2
ARGS=()
while [[ $# -gt 0 ]]; do
    if [[ "$1" == "--minimo" ]]; then MINIMO="$2"; shift 2; else ARGS+=("$1"); shift; fi
done

paso "1/4 links con veces_enlazada > $MINIMO -> data/enlaces_proximidad.txt"
correr uvpy -m src.descarga.proximidad --minimo "$MINIMO"
if [[ $ESTADO -eq 0 ]]; then
    paso "2/4 descarga de esos links"
    correr uvpy -m src.descarga.run --solo-enlaces --enlaces data/enlaces_proximidad.txt "${ARGS[@]}"
    paso "3/4 reintento de los que fallaron (2 pasadas)"
    correr uvpy -m src.descarga.run --solo-enlaces --enlaces data/enlaces_proximidad.txt --solo-fallidos "${ARGS[@]}"
    correr uvpy -m src.descarga.run --solo-enlaces --enlaces data/enlaces_proximidad.txt --solo-fallidos "${ARGS[@]}"
    paso "4/4 resumen del manifest"
    resumen_manifest
fi

enviar_resumen scraper_proximidad
exit "$ESTADO"
