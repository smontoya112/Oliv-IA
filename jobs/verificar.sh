#!/usr/bin/env bash
#SBATCH --job-name=verificar
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err
#SBATCH --mail-type=ALL
#SBATCH --mail-user=s.montoya112@uniandes.edu.co
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=24G
#SBATCH --time=03:00:00
#
# Fase 8 (src/verificacion): valida la verificación de citas y la abstención sobre las
# predicciones YA generadas por el paso 7 (data/processed/bench_generacion/<modelo>.jsonl),
# sin regenerar. No necesita GPU. Corre en Hypatia porque el catálogo (chunks.parquet) no
# carga en Windows.
#   1. instala jsonschema en .venv-gen (si existe y no lo tiene)
#   2. aplica la fase 8 con catálogo: respalda citas con el corpus, reordena el top 10,
#      decide abstención y valida el schema -> data/processed/verificacion/<modelo>.jsonl
#   3. evalúa (determinista) antes y después
#   4. barrido opcional del umbral de abstención (UMBRALES="-2 0 2")
#   5. RAGAS opcional (RAGAS=1; ~30 min por entrega, requiere OPENROUTER_API_KEY)
#   6. tabla comparativa -> data/processed/verificacion/comparacion.csv (líneas RESULTADO)
#
#     mkdir -p logs                                              # una sola vez
#     sbatch jobs/verificar.sh                                   # los 3 modelos
#     sbatch jobs/verificar.sh qwen3-8b                          # uno o varios
#     UMBRALES="-2 0 2" RAGAS=1 sbatch jobs/verificar.sh llama-3.1-8b
source "$SLURM_SUBMIT_DIR/jobs/_comun.sh"
preparar_entorno

MODELOS=("$@"); [[ ${#MODELOS[@]} -eq 0 ]] && MODELOS=(llama-3.1-8b qwen3-8b salamandra-7b)
UMBRALES="${UMBRALES:-}"
RAGAS="${RAGAS:-0}"
RECUPERACION="data/recuperacion/sample_50.jsonl"
DIR="data/processed/verificacion"
mkdir -p "$DIR"
# jsonschema no está en pyproject (uv lock no corre en Windows): --with lo agrega solo aquí.
uvv() { uv run --quiet --with jsonschema python "$@"; }
ENTREGAS=()     # "nombre|ruta" de cada entrega a evaluar

paso "0/6 verificando entradas"
for f in "$RECUPERACION" data/index/index_config.json data/processed/chunks.parquet; do
    [[ -s "$f" ]] || { echo "ERROR: falta $f" >&2; ESTADO=2; }
done
for m in "${MODELOS[@]}"; do
    [[ -s "data/processed/bench_generacion/$m.jsonl" ]] \
        || { echo "ERROR: falta data/processed/bench_generacion/$m.jsonl (sbatch jobs/generacion_bench.sh $m)" >&2; ESTADO=2; }
done
if [[ $ESTADO -eq 0 && "$RAGAS" == "1" ]]; then
    if [[ -z "${OPENROUTER_API_KEY:-}" ]] && ! grep -qs '^OPENROUTER_API_KEY=' .env scripts/.env; then
        echo "ERROR: RAGAS=1 pero falta OPENROUTER_API_KEY (variable de entorno o .env / scripts/.env)" >&2
        ESTADO=3
    elif ! curl -s -o /dev/null --max-time 15 https://openrouter.ai/api/v1/models; then
        echo "ERROR: RAGAS=1 pero no hay conectividad a openrouter.ai desde $(hostname)" >&2
        ESTADO=4
    fi
fi

if [[ $ESTADO -eq 0 ]]; then
    paso "1/6 jsonschema en .venv-gen"
    if [[ -x .venv-gen/bin/python ]]; then
        if .venv-gen/bin/python -c "import jsonschema" 2>/dev/null; then
            echo ".venv-gen ya tiene jsonschema"
        else
            correr uv pip install --quiet --python .venv-gen/bin/python jsonschema
        fi
    else
        echo "(no hay .venv-gen: se omite)"
    fi
fi

if [[ $ESTADO -eq 0 ]]; then
    paso "2/6 fase 8 con catálogo y 3/6 evaluación antes/después"
    for m in "${MODELOS[@]}"; do
        echo "-- $m"
        correr uvv -m src.verificacion.aplicar --generacion "data/processed/bench_generacion/$m.jsonl" \
            --recuperacion "$RECUPERACION" --catalogo data/index --salida "$DIR/$m.jsonl"
        ENTREGAS+=("${m}_antes|data/processed/bench_generacion/$m.jsonl" "${m}_despues|$DIR/$m.jsonl")
        for u in $UMBRALES; do
            echo "-- $m, umbral $u"
            correr uvv -m src.verificacion.aplicar --generacion "data/processed/bench_generacion/$m.jsonl" \
                --recuperacion "$RECUPERACION" --catalogo data/index --umbral "$u" \
                --salida "$DIR/${m}_u${u}.jsonl"
            ENTREGAS+=("${m}_u${u}|$DIR/${m}_u${u}.jsonl")
        done
    done
    for e in "${ENTREGAS[@]}"; do
        nombre="${e%%|*}"; ruta="${e#*|}"
        [[ -s "$ruta" ]] && correr uvv scripts/evaluate.py --submission "$ruta" --out "$DIR/eval_${nombre}.json" >/dev/null
    done
    [[ -n "$UMBRALES" ]] && paso "4/6 barrido de umbral: $UMBRALES" || paso "4/6 sin barrido de umbral (UMBRALES vacío)"
fi

if [[ $ESTADO -eq 0 && "$RAGAS" == "1" ]]; then
    paso "5/6 RAGAS (juez por API, encoder en CPU)"
    correr uv pip install --quiet -r scripts/requirements-evaluador.txt
    # --no-sync: no deshacer el tope de langchain-community (ver jobs/evaluar_ragas.sh).
    for e in "${ENTREGAS[@]}"; do
        nombre="${e%%|*}"; ruta="${e#*|}"
        [[ "$nombre" == *_antes ]] && continue          # la línea base ya tiene su ragas del paso 7
        [[ -s "$ruta" ]] && correr uv run --quiet --no-sync python jobs/ragas_con_timeout.py \
            --submission "$ruta" --split sample --ragas --out "$DIR/ragas_${nombre}.json" >/dev/null
    done
else
    paso "5/6 sin RAGAS (RAGAS=1 para correrlo)"
fi

paso "6/6 comparación"
uvv - "$DIR" <<'PY'
import csv, json, sys
from pathlib import Path

d = Path(sys.argv[1])
campos = ["entrega", "cerradas_acc", "citas_indice", "tasa_sin_respaldo", "abstencion_calib",
          "ragas", "total_sin_ragas"]
filas = []
for ev in sorted(d.glob("eval_*.json")):
    nombre = ev.stem[len("eval_"):]
    r = json.loads(ev.read_text(encoding="utf-8"))
    rg = d / f"ragas_{nombre}.json"
    if not rg.exists() and nombre.endswith("_antes"):       # ragas del paso 7 (jobs/evaluar_ragas.sh)
        rg = Path("data/processed") / f"ragas_{nombre[:-len('_antes')]}.json"
    ragas = json.loads(rg.read_text(encoding="utf-8")) if rg.exists() else {}
    corr = ragas.get("correccion_ragas", {}).get("correctness")
    total = r["total_automatico"]["obtenidos"]          # sin RAGAS: comparable entre filas
    filas.append({"entrega": nombre, "cerradas_acc": round(r["cerradas"]["accuracy"], 3),
                  "citas_indice": r["citas"]["indice"],
                  "tasa_sin_respaldo": r["citas"]["tasa_sin_respaldo"],
                  "abstencion_calib": r["abstencion"]["calibracion"],
                  "ragas": corr, "total_sin_ragas": total})
with (d / "comparacion.csv").open("w", encoding="utf-8", newline="") as f:
    w = csv.DictWriter(f, campos)
    w.writeheader()
    w.writerows(filas)
print("RESULTADO " + " | ".join(campos))
for x in filas:
    print("RESULTADO " + " | ".join(str(x[c]) for c in campos))
PY

enviar_resumen verificar
exit "$ESTADO"
