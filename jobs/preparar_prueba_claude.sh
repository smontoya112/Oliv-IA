#!/usr/bin/env bash
# Prepara ~/hackatron/prueba_claude en hypatia: un clon del repo en la rama prueba-claude con enlaces
# SOLO DE LECTURA a lo pesado del repo original (corpus, índice, entornos). El original no se toca:
# todo lo que se escriba (índice base, salidas, logs) cae en el clon. Se corre en el nodo de login
# (solo clona y crea enlaces):
#
#     bash jobs/preparar_prueba_claude.sh
#
# El código se sincroniza desde el portátil con `tar` + `scp` (el origen de verdad es la rama local).
set -euo pipefail
ORIG="${ORIG:-$HOME/hackatron/Oliv-IA2/Oliv-IA}"
DEST="${DEST:-$HOME/hackatron/prueba_claude}"
[[ -d "$ORIG/.git" ]] || { echo "ERROR: no encuentro $ORIG" >&2; exit 2; }
if [[ ! -d "$DEST/.git" ]]; then
    git clone -q "$ORIG" "$DEST"
fi
cd "$DEST"
git switch -c prueba-claude 2>/dev/null || git switch prueba-claude
mkdir -p logs data/processed data/exp experimentos/claude
enlazar() { [[ -e "$2" || -L "$2" ]] || { [[ -e "$1" ]] && ln -s "$1" "$2" || echo "AVISO: falta $1" >&2; }; }
for d in md raw index; do enlazar "$ORIG/data/$d" "data/$d"; done
for f in chunks.parquet articulos.parquet texto; do enlazar "$ORIG/data/processed/$f" "data/processed/$f"; done
for v in .venv-gpu .venv-gen; do enlazar "$ORIG/$v" "$v"; done
echo "clon: $DEST · rama $(git branch --show-current) · commit $(git log -1 --oneline)"
ls -la data | head -30
du -sh "$ORIG/data/index" 2>/dev/null | head -1
nvidia-smi -L 2>/dev/null | head -2 || true
