#!/usr/bin/env bash
#SBATCH --job-name=descargar_fuentes
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err
#SBATCH --mail-type=ALL
#SBATCH --mail-user=s.montoya112@uniandes.edu.co
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=16G
#SBATCH --time=02:00:00
#
# Corre el scraper (src.descarga.run) con un fuentes.json y mete esos documentos al corpus
# (data/raw, data/md y data/corpus_manifest.json). Es lo que hace el paso 2 de jobs/enriquecer_corpus.sh,
# pero sin volver a extraer las normas de las preguntas: el fuentes.json que ya salió de ahí se usa tal cual.
#
#     mkdir -p logs                                                  # una sola vez
#     sbatch jobs/descargar_fuentes.sh                               # data/enriquecimiento/test_992/fuentes.json
#     sbatch jobs/descargar_fuentes.sh <otro fuentes.json>
#     REINDEXAR=0 sbatch jobs/descargar_fuentes.sh                   # solo descargar
#
# Si entró algo nuevo y REINDEXAR=1 (por defecto) encadena, con --dependency=afterok, el chunking y el índice
# del corpus que usa config/responder.json (CORPUS=base: data/processed_base -> data/index_base; ver
# jobs/chunking.sh y jobs/indice.sh). Reanudable: lo ya descargado queda en data/raw y no se baja de nuevo.
# Las fuentes antiguas (seed y propias) se cargan para no duplicar; --solo baja únicamente los doc_id del JSON.
# Variable PYTHON: intérprete con las dependencias de src.descarga (httpx...). Si no se da, se usa el primero de
# .venv/bin/python, .venv-gpu/bin/python que importe httpx; si ninguno, `uv run` como los demás jobs.
source "$SLURM_SUBMIT_DIR/jobs/_comun.sh"
preparar_entorno

FUENTES="${1:-data/enriquecimiento/test_992/fuentes.json}"
REINDEXAR="${REINDEXAR:-1}"
PY_DESCARGA=""
for p in "${PYTHON:-}" .venv/bin/python .venv-gpu/bin/python; do
    if [[ -n "$p" && -x "$p" ]] && PYTHONPATH=. "$p" -c "import httpx" 2>/dev/null; then PY_DESCARGA="$p"; break; fi
done
if [[ -n "$PY_DESCARGA" ]]; then py() { PYTHONPATH=. "$PY_DESCARGA" "$@"; }; else py() { uvpy "$@"; }; fi
echo "intérprete: ${PY_DESCARGA:-uv run}"

paso "0/3 verificando entradas"
for f in "$FUENTES" data/fuentes_seed.json data/fuentes_propias.json data/corpus_manifest.json; do
    [[ -s "$f" ]] || { echo "ERROR: falta $f" >&2; ESTADO=2; }
done

IDS=()
if [[ $ESTADO -eq 0 ]]; then
    mapfile -t IDS < <(py -c "import json,sys; print('\n'.join(o['doc_id'] for o in json.load(open(sys.argv[1], encoding='utf-8'))))" "$FUENTES")
    echo "fuentes: $FUENTES · ${#IDS[@]} documentos"
    [[ ${#IDS[@]} -gt 0 ]] || { echo "ERROR: $FUENTES no tiene documentos" >&2; ESTADO=2; }
fi

n_ok() { py -c "import json; print(sum(r.get('estado')=='ok' for r in json.load(open('data/corpus_manifest.json', encoding='utf-8'))))"; }
n_md() { ls data/md/*.md 2>/dev/null | grep -vc '\.notas\.md$'; }
ANTES=0; MD_ANTES=0
if [[ $ESTADO -eq 0 ]]; then
    ANTES=$(n_ok); MD_ANTES=$(n_md)
    FUENTES_ARGS=(--fuentes data/fuentes_seed.json data/fuentes_propias.json "$FUENTES")
    paso "1/3 descargando ${#IDS[@]} documentos"
    correr py -m src.descarga.run "${FUENTES_ARGS[@]}" --solo "${IDS[@]}"
    paso "2/3 reintentando los que fallaron (2 pasadas)"
    correr py -m src.descarga.run "${FUENTES_ARGS[@]}" --solo "${IDS[@]}" --solo-fallidos
    correr py -m src.descarga.run "${FUENTES_ARGS[@]}" --solo "${IDS[@]}" --solo-fallidos
fi

NUEVOS=0
if [[ $ESTADO -eq 0 ]]; then
    paso "3/3 resultado"
    NUEVOS=$(( $(n_md) - MD_ANTES ))
    echo "RESULTADO documentos md nuevos: $NUEVOS · ok en el manifest: $ANTES -> $(n_ok)"
    py - "${IDS[@]}" <<'PY'
import json, sys
m = {r["doc_id"]: r for r in json.load(open("data/corpus_manifest.json", encoding="utf-8"))}
ok = [d for d in sys.argv[1:] if m.get(d, {}).get("estado") == "ok"]
mal = [d for d in sys.argv[1:] if d not in ok]
print(f"RESULTADO del fuentes.json: {len(ok)} ok · {len(mal)} sin descargar")
for d in mal:
    print("  sin descargar:", d, "|", m.get(d, {}).get("error"))
PY
    if [[ $NUEVOS -gt 0 && "$REINDEXAR" == "1" ]]; then
        J1=$(env -u PYTHON CORPUS=base sbatch --parsable jobs/chunking.sh) \
            && J2=$(env -u PYTHON CORPUS=base sbatch --parsable --dependency=afterok:"$J1" jobs/indice.sh) \
            && echo "RESULTADO encadenados: chunking $J1 -> indice $J2 (CORPUS=base)" \
            || { echo "ERROR: no se pudieron encadenar el chunking y el índice (sbatch)" >&2; ESTADO=5; }
    else
        echo "sin reindexar (nuevos=$NUEVOS, REINDEXAR=$REINDEXAR)"
    fi
fi

enviar_resumen descargar_fuentes
exit "$ESTADO"
