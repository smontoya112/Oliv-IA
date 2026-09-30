#!/usr/bin/env bash
#SBATCH --job-name=scrapper
#SBATCH --output=scrapper_%j.out
#SBATCH --mail-type=ALL
#SBATCH --mail-user=s.montoya112@uniandes.edu.co
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=32G
#SBATCH --time=04:00:00
#
# Descarga el corpus COMPLETO: las ~220 normas y sentencias de data/seed_targets.json
# + data/fuentes_propias.json + data/enlaces.txt. Se lanza con sbatch (no necesita tmux;
# el job sigue aunque cierres la sesión), desde la raíz del repo:
#
#     sbatch scrapper.sh
#     sbatch scrapper.sh --forzar                 # los argumentos van a `run` tal cual
#     sbatch --mem=64gb --time=12:00:00 --gres=gpu:1 -p gpu scrapper.sh   # variante con GPU
#     sbatch --mail-user=otro@uniandes.edu.co scrapper.sh                 # otro destinatario
#
#     squeue -u $USER                             # ver el job
#     tail -f scrapper_<jobid>.out           # seguir el log
#     scancel <jobid>                             # cancelarlo
#
# Correos: Slurm avisa al inicio, fin, fallo y límite de tiempo (líneas #SBATCH de arriba).
# Además, al terminar se manda un resumen con mail/mailx/sendmail si existe en el nodo.
#
# El log queda en la carpeta desde la que lanzas (Slurm no crea carpetas: por eso no
# usamos logs/). stdout y stderr van juntos en scrapper_<jobid>.out.
#
# Es reanudable: lo ya descargado queda en data/raw. Si se corta por tiempo, se relanza.
set -uo pipefail
cd "${SLURM_SUBMIT_DIR:-$(dirname "$0")}"
MAIL_TO="${SLURM_JOB_MAIL_USER:-s.montoya112@uniandes.edu.co}"
LOG="scrapper_${SLURM_JOB_ID:-local}.out"
EXTRA="$*"

# Como en los demás jobs: entorno de python y uv en el PATH del nodo de cómputo.
module load python 2>/dev/null || true
export PATH="$HOME/.local/bin:$PATH"

echo "Job ${SLURM_JOB_ID:-local} en $(hostname) · $(date '+%F %T')"
ESTADO=0

echo '== 1/4 seed -> data/fuentes_seed.json'
uv run python -m src.descarga.seed_a_fuentes || ESTADO=10

if [[ $ESTADO -eq 0 ]]; then
    echo '== 2/4 descarga de todo el corpus (seed + fuentes_propias + enlaces.txt)'
    uv run python -m src.descarga.run $EXTRA || ESTADO=$?
    echo '== 3/4 reintento de los que fallaron (2 pasadas)'
    uv run python -m src.descarga.run --solo-fallidos $EXTRA || ESTADO=$?
    uv run python -m src.descarga.run --solo-fallidos $EXTRA || ESTADO=$?
    echo '== 4/4 resumen del manifest'
    uv run python - <<'PY'
import json, collections
m = json.load(open('data/corpus_manifest.json', encoding='utf-8'))
c = collections.Counter(r.get('estado') for r in m)
print('documentos:', len(m), dict(c))
for r in m:
    if r.get('estado') != 'ok':
        print('  FALLO', r['doc_id'], '|', r.get('error'))
PY
fi
echo "== fin ($ESTADO). Revisen data/corpus_manifest.json y data/descubiertos.csv"

# --- correo final -----------------------------------------------------------------
if [[ $ESTADO -ne 0 ]]; then
    ASUNTO="[scrapper] FALLÓ el job (código $ESTADO)"
elif grep -q '^  FALLO' "$LOG" 2>/dev/null; then
    ASUNTO="[scrapper] Terminó con documentos fallidos"
else
    ASUNTO="[scrapper] Terminó OK: corpus completo descargado"
fi
CUERPO="$(mktemp)"
{
    echo "$ASUNTO"
    echo "Nodo: $(hostname) · fin: $(date '+%F %T') · log: $PWD/$LOG"
    echo
    grep -E 'documentos:|^  FALLO|Listos:|✗' "$LOG" 2>/dev/null | head -60
    echo
    echo "--- últimas 30 líneas del log ---"
    tail -30 "$LOG" 2>/dev/null
} > "$CUERPO"
for cmd in mail mailx; do
    if command -v $cmd >/dev/null 2>&1; then $cmd -s "$ASUNTO" "$MAIL_TO" < "$CUERPO"; break; fi
done || true
if ! command -v mail >/dev/null && ! command -v mailx >/dev/null && command -v sendmail >/dev/null; then
    { echo "To: $MAIL_TO"; echo "Subject: $ASUNTO"; echo; cat "$CUERPO"; } | sendmail -t
fi
rm -f "$CUERPO"
exit "$ESTADO"
