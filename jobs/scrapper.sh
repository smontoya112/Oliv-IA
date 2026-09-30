#!/usr/bin/env bash
#SBATCH --job-name=scrapper
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err
#SBATCH --mail-type=ALL
#SBATCH --mail-user=s.montoya112@uniandes.edu.co
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=32G
#SBATCH --time=04:00:00
#
# Descarga el corpus COMPLETO: data/seed_targets.json + data/fuentes_propias.json +
# data/enlaces.txt (+ data/enlaces_proximidad.txt si existe). Desde la raíz del repo:
#
#     mkdir -p logs            # una sola vez
#     sbatch jobs/scrapper.sh
#     sbatch jobs/scrapper.sh --forzar       # los argumentos van a `run` tal cual
#
# Salidas: logs/scrapper_<id>.out (avance y resultados) y logs/scrapper_<id>.err (solo errores).
# Es reanudable: lo ya descargado queda en data/raw y no se baja de nuevo.
source "$SLURM_SUBMIT_DIR/jobs/_comun.sh"
preparar_entorno
EXTRA="$*"

paso "1/4 seed -> data/fuentes_seed.json"
correr uvpy -m src.descarga.seed_a_fuentes
if [[ $ESTADO -eq 0 ]]; then
    paso "2/4 descarga del corpus (seed + fuentes_propias + enlaces)"
    correr uvpy -m src.descarga.run $EXTRA
    paso "3/4 reintento de los que fallaron (2 pasadas)"
    correr uvpy -m src.descarga.run --solo-fallidos $EXTRA
    correr uvpy -m src.descarga.run --solo-fallidos $EXTRA
    paso "4/4 resumen del manifest"
    resumen_manifest
fi

enviar_resumen scrapper
exit "$ESTADO"
