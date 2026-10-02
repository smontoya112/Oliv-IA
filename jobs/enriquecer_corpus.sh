#!/usr/bin/env bash
#SBATCH --job-name=enriquecer_corpus
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err
#SBATCH --mail-type=ALL
#SBATCH --mail-user=s.montoya112@uniandes.edu.co
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=16G
#SBATCH --time=08:00:00
#
# Enriquece el corpus con las normas que nombran las PREGUNTAS (src/descarga/desde_preguntas.py):
#   1. extrae del enunciado las oraciones con "ley", "decreto", "sentencia", "código"... y sus
#      citas, y las compara con data/corpus_manifest.json
#   2. descarga las que faltan (Senado / relatoría de la Corte Constitucional) con src.descarga.run,
#      más 2 reintentos de las fallidas
#   3. vuelve a extraer para reportar lo que sigue faltando
#   4. si entró algo nuevo y REINDEXAR=1 (por defecto), encadena chunking -> índice (GPU) ->
#      recuperación de esas mismas preguntas, cada uno con --dependency=afterok del anterior
# No necesita GPU. Es reanudable: lo ya descargado queda en data/raw y no se baja de nuevo.
#
#     mkdir -p logs                                                  # una sola vez
#     sbatch jobs/enriquecer_corpus.sh data/test_992.jsonl           # el sábado, con las 992
#     sbatch jobs/enriquecer_corpus.sh data/sample_50.jsonl          # ensayo
#     sbatch jobs/enriquecer_corpus.sh data/test_992.jsonl --con-opciones   # también las opciones
#     REINDEXAR=0 sbatch jobs/enriquecer_corpus.sh data/test_992.jsonl      # solo extraer y bajar
#     CHUNKING_ARGS="--excluir-origen ronda_03 ronda_04" sbatch jobs/enriquecer_corpus.sh data/test_992.jsonl
#
# Salidas: data/enriquecimiento/<preguntas>/ (normas.json, fragmentos.jsonl, fuentes.json,
# pendientes.json -> normas sin URL automática, a buscar a mano) y despues/ (lo que sigue faltando).
source "$SLURM_SUBMIT_DIR/jobs/_comun.sh"
preparar_entorno

PREGUNTAS="${1:?uso: sbatch jobs/enriquecer_corpus.sh <preguntas.jsonl> [--con-opciones]}"
shift
OPCIONES=("$@")
NOMBRE="$(basename "$PREGUNTAS" .jsonl)"
DIR="data/enriquecimiento/${NOMBRE}"
REINDEXAR="${REINDEXAR:-1}"
CHUNKING_ARGS="${CHUNKING_ARGS:-}"
mkdir -p "$DIR"

n_ok() { uvpy -c "import json; print(sum(r.get('estado')=='ok' for r in json.load(open('data/corpus_manifest.json', encoding='utf-8'))))"; }

paso "0/4 verificando entradas"
for f in "$PREGUNTAS" data/corpus_manifest.json; do
    [[ -s "$f" ]] || { echo "ERROR: falta $f" >&2; ESTADO=2; }
done

if [[ $ESTADO -eq 0 ]]; then
    paso "1/4 normas nombradas en $PREGUNTAS"
    correr uvpy -m src.descarga.desde_preguntas --preguntas "$PREGUNTAS" --salida "$DIR" "${OPCIONES[@]}"
fi

ANTES=0
if [[ $ESTADO -eq 0 ]]; then
    mapfile -t IDS < <(grep -v '^\s*$' "$DIR/ids_a_descargar.txt" 2>/dev/null)
    ANTES=$(n_ok)
    if [[ ${#IDS[@]} -eq 0 ]]; then
        paso "2/4 no hay normas nuevas con URL automática para descargar"
    else
        paso "2/4 descargando ${#IDS[@]} normas que faltan"
        # Se cargan también las fuentes del corpus para no duplicar; --solo baja solo las nuevas.
        FUENTES=(--fuentes data/fuentes_seed.json data/fuentes_propias.json "$DIR/fuentes.json")
        correr uvpy -m src.descarga.run "${FUENTES[@]}" --solo "${IDS[@]}"
        correr uvpy -m src.descarga.run "${FUENTES[@]}" --solo "${IDS[@]}" --solo-fallidos
        correr uvpy -m src.descarga.run "${FUENTES[@]}" --solo "${IDS[@]}" --solo-fallidos
    fi
fi

NUEVOS=0
if [[ $ESTADO -eq 0 ]]; then
    paso "3/4 lo que sigue faltando"
    correr uvpy -m src.descarga.desde_preguntas --preguntas "$PREGUNTAS" --salida "$DIR/despues" "${OPCIONES[@]}"
    NUEVOS=$(( $(n_ok) - ANTES ))
    echo "RESULTADO documentos nuevos en el corpus: $NUEVOS"
    echo "RESULTADO pendientes a buscar a mano: $DIR/despues/pendientes.json"
fi

if [[ $ESTADO -eq 0 && $NUEVOS -gt 0 && "$REINDEXAR" == "1" ]]; then
    paso "4/4 encadenando chunking -> índice -> recuperación"
    # shellcheck disable=SC2086
    J1=$(sbatch --parsable jobs/chunking.sh $CHUNKING_ARGS) \
        && J2=$(sbatch --parsable --dependency=afterok:"$J1" jobs/indice.sh) \
        && J3=$(sbatch --parsable --dependency=afterok:"$J2" jobs/recuperar.sh "$PREGUNTAS") \
        && echo "RESULTADO encadenados: chunking $J1 -> indice $J2 -> recuperar $J3" \
        || { echo "ERROR: no se pudieron encadenar los jobs (sbatch)" >&2; ESTADO=5; }
else
    paso "4/4 sin reindexar (nuevos=$NUEVOS, REINDEXAR=$REINDEXAR)"
fi

resumen_manifest
enviar_resumen enriquecer_corpus
exit "$ESTADO"
