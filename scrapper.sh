#!/usr/bin/env bash
# Descarga el corpus COMPLETO en un nodo del clúster: las ~220 normas y sentencias de
# data/seed_targets.json (rama corpus) + data/fuentes_propias.json + data/enlaces.txt.
#
# Uso, desde la raíz del repo en hypatia (dentro de tmux o con nohup, porque dura horas):
#     tmux new -s scrapper
#     bash scrapper.sh            # pide RAM (CPU) y corre
#     bash scrapper.sh --gpu      # pide GPU; el scraper no la usa, solo por si la necesitan
#     bash scrapper.sh --forzar   # cualquier otro argumento se pasa a `run` tal cual
#     MAIL_TO=otro@uniandes.edu.co bash scrapper.sh    # cambiar el destinatario
#
# Correos a MAIL_TO:
#   - Slurm avisa solo (--mail-type): inicio, fin, fallo y límite de tiempo del job.
#   - Este script, al terminar, manda un resumen (documentos ok/con error y el final del
#     log) con el comando `mail`, `mailx` o `sendmail`, el que exista en el nodo de login.
#
# Es reanudable: lo ya descargado queda en data/raw y no se vuelve a bajar. Si el job se
# corta por tiempo, basta volver a lanzar el script.
set -uo pipefail
cd "$(dirname "$0")"
mkdir -p logs

MAIL_TO="${MAIL_TO:-s.montoya112@uniandes.edu.co}"
AVISOS=(--mail-user="$MAIL_TO" --mail-type=BEGIN,END,FAIL,TIME_LIMIT)

RECURSOS=(--mem=32gb --time=04:00:00)                    # srun --mem=32gb --time=04:00:00 --pty bash -i
if [[ "${1:-}" == "--gpu" ]]; then
    RECURSOS=(--mem=64gb --time=12:00:00 --gres=gpu:1 -p gpu)   # srun --mem=64gb --time=12:00:00 --gres=gpu:1 -p gpu --pty bash -i
    shift
fi
EXTRA="$*"

LOG="logs/scrapper_$(date +%Y%m%d_%H%M%S).log"
echo "Recursos: ${RECURSOS[*]} · avisos a $MAIL_TO · log: $LOG"

enviar_correo() {   # enviar_correo "asunto" archivo_con_cuerpo
    local asunto="$1" cuerpo="$2"
    if command -v mail >/dev/null 2>&1; then
        mail -s "$asunto" "$MAIL_TO" < "$cuerpo"
    elif command -v mailx >/dev/null 2>&1; then
        mailx -s "$asunto" "$MAIL_TO" < "$cuerpo"
    elif command -v sendmail >/dev/null 2>&1; then
        { echo "To: $MAIL_TO"; echo "Subject: $asunto"; echo; cat "$cuerpo"; } | sendmail -t
    else
        echo "(no hay mail/mailx/sendmail en este nodo; solo llegarán los avisos de Slurm)"
        return 1
    fi
}

# Igual que los srun con --pty bash -i, pero en vez de una shell interactiva
# ejecuta el trabajo y termina solo.
srun "${RECURSOS[@]}" "${AVISOS[@]}" bash -c "
    set -uo pipefail
    cd '$PWD'
    echo '== 1/4 seed -> data/fuentes_seed.json'
    uv run python -m src.descarga.seed_a_fuentes || exit 10
    echo '== 2/4 descarga de todo el corpus (seed + fuentes_propias + enlaces.txt)'
    uv run python -m src.descarga.run $EXTRA
    echo '== 3/4 reintento de los que fallaron (2 pasadas)'
    uv run python -m src.descarga.run --solo-fallidos $EXTRA
    uv run python -m src.descarga.run --solo-fallidos $EXTRA
    echo '== 4/4 resumen del manifest'
    uv run python -c \"
import json, collections
m = json.load(open('data/corpus_manifest.json', encoding='utf-8'))
c = collections.Counter(r.get('estado') for r in m)
print('documentos:', len(m), dict(c))
for r in m:
    if r.get('estado') != 'ok': print('  FALLO', r['doc_id'], '|', r.get('error'))
\"
    echo '== listo. Revisen data/corpus_manifest.json, data/descubiertos.csv y data/fuentes_pendientes.json'
" 2>&1 | tee "$LOG"
ESTADO=${PIPESTATUS[0]}

# --- correo final -----------------------------------------------------------------
if [[ $ESTADO -ne 0 ]]; then
    ASUNTO="[scrapper] FALLÓ el job (código $ESTADO)"
elif grep -q '^  FALLO' "$LOG"; then
    ASUNTO="[scrapper] Terminó con documentos fallidos"
else
    ASUNTO="[scrapper] Terminó OK: corpus completo descargado"
fi
CUERPO="$(mktemp)"
{
    echo "$ASUNTO"
    echo "Nodo: $(hostname) · fin: $(date '+%F %T') · log: $PWD/$LOG"
    echo
    grep -E 'documentos:|^  FALLO|Listos:|✗' "$LOG" | head -60
    echo
    echo "--- últimas 30 líneas del log ---"
    tail -30 "$LOG"
} > "$CUERPO"
enviar_correo "$ASUNTO" "$CUERPO" && echo "Correo enviado a $MAIL_TO"
rm -f "$CUERPO"
exit "$ESTADO"
