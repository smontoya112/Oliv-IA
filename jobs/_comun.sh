#!/usr/bin/env bash
# Funciones comunes de los jobs de Slurm (no se lanza solo). Cada job la carga con:
#     source "$SLURM_SUBMIT_DIR/jobs/_comun.sh"
#
# Convención de salidas de TODOS los jobs (hay que lanzarlos desde la raíz del repo y
# tener la carpeta logs/ creada: Slurm no crea carpetas):
#     logs/<job>_<id>.out   avance normal y resultados: lo que salió bien
#     logs/<job>_<id>.err   SOLO errores (vacío si todo fue bien)

MAIL_TO="${SLURM_JOB_MAIL_USER:-s.montoya112@uniandes.edu.co}"
ESTADO=0

preparar_entorno() {
    cd "${SLURM_SUBMIT_DIR:?lancen el job con sbatch desde la raíz del repo}"
    module load python 2>/dev/null || true
    export PATH="$HOME/.local/bin:$PATH"
    export PYTHONUNBUFFERED=1            # para poder seguir el .out con tail -f
    export PYTHONWARNINGS=ignore         # avisos internos de librerías (ranx, numba...) no son errores del job
    OUT="logs/${SLURM_JOB_NAME}_${SLURM_JOB_ID}.out"
    ERR="logs/${SLURM_JOB_NAME}_${SLURM_JOB_ID}.err"
    echo "Job ${SLURM_JOB_NAME} ${SLURM_JOB_ID} en $(hostname) · $(date '+%F %T')"
}

paso() { echo "== $*"; }

# Compilador C++ para llama.cpp. El gcc del sistema (8.x) no trae std::filesystem en la librería
# compartida y libggml.so queda con símbolos sin resolver. Si se define GCC_MODULE (un gcc >= 9 y
# <= 11, que son los que admite CUDA 11.8, p. ej. GCC_MODULE=gnu9/9.4.0) se carga y se agrega su
# lib64 al LD_LIBRARY_PATH: la librería queda enlazada a ESE libstdc++ y debe cargarse igual en
# tiempo de ejecución (servir.sh y los benchmarks llaman a esta función también).
cargar_gcc() {
    [[ -n "${GCC_MODULE:-}" ]] || return 0
    module load "$GCC_MODULE" || { echo "ERROR: no existe el módulo $GCC_MODULE" >&2; ESTADO=3; return 1; }
    local cxx lib
    cxx="$(command -v g++)"
    lib="$(dirname "$(dirname "$cxx")")/lib64"
    [[ -d "$lib" ]] && export LD_LIBRARY_PATH="$lib:${LD_LIBRARY_PATH:-}"
    export CC="$(command -v gcc)" CXX="$cxx" CUDAHOSTCXX="$cxx"
}

# CUDA 11.8 del módulo para compilar y para ejecutar llama.cpp. El módulo no siempre agrega
# lib64 a LD_LIBRARY_PATH y sin eso libllama.so no encuentra libcudart.so.11.0 al cargarse.
cargar_cuda() {
    module load cuda/11.8 || { echo "ERROR: no existe el módulo cuda/11.8" >&2; ESTADO=3; return 1; }
    local raiz="${CUDA_HOME:-$(dirname "$(dirname "$(command -v nvcc)")")}"
    export CUDA_HOME="$raiz" CUDACXX="$raiz/bin/nvcc"
    export LD_LIBRARY_PATH="$raiz/lib64:${LD_LIBRARY_PATH:-}"
}

# correr <comando...>: ejecuta y, si falla, lo escribe en stderr (.err) y recuerda el código.
correr() {
    "$@" || { local c=$?; echo "ERROR: '$*' terminó con código $c" >&2; ESTADO=$c; }
}

# uv en silencio: sus mensajes de instalación irían al .err y no son errores.
uvpy() { uv run --quiet python "$@"; }

enviar_resumen() {   # enviar_resumen "nombre del job"
    local nombre="$1" asunto cuerpo
    if [[ $ESTADO -ne 0 ]]; then
        asunto="[$nombre] FALLÓ (código $ESTADO)"
    elif [[ -s "$ERR" ]]; then
        asunto="[$nombre] Terminó con errores (ver .err)"
    else
        asunto="[$nombre] Terminó OK"
    fi
    echo "== fin: $asunto · $(date '+%F %T')"
    cuerpo="$(mktemp)"
    {
        echo "$asunto"
        echo "Nodo: $(hostname) · log: $PWD/$OUT · errores: $PWD/$ERR"
        echo
        grep -E 'documentos:|Listos:|links con|RESULTADO|n_chunks|✗|⚠' "$OUT" 2>/dev/null | head -60
        echo
        echo "--- errores (.err, primeras 40 líneas) ---"
        head -40 "$ERR" 2>/dev/null
    } > "$cuerpo"
    if command -v mail >/dev/null 2>&1; then mail -s "$asunto" "$MAIL_TO" < "$cuerpo"
    elif command -v mailx >/dev/null 2>&1; then mailx -s "$asunto" "$MAIL_TO" < "$cuerpo"
    elif command -v sendmail >/dev/null 2>&1; then
        { echo "To: $MAIL_TO"; echo "Subject: $asunto"; echo; cat "$cuerpo"; } | sendmail -t
    fi
    rm -f "$cuerpo"
}

resumen_manifest() {
    uvpy - <<'PY'
import json, collections
m = json.load(open('data/corpus_manifest.json', encoding='utf-8'))
c = collections.Counter(r.get('estado') for r in m)
print('documentos:', len(m), dict(c))
for r in m:
    if r.get('estado') != 'ok':
        print('  sin descargar:', r['doc_id'], '|', r.get('error'))
PY
}
