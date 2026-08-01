#!/usr/bin/env bash
# Levanta la aplicación completa en este computador.
#   ./iniciar.sh
set -euo pipefail
cd "$(dirname "$0")/backend"

if [ ! -d .venv ]; then
  echo "→ Creando entorno de Python…"
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

echo "→ Instalando dependencias…"
pip install -q -r requirements.txt

if [ ! -f obra.db ]; then
  echo "→ Cargando la obra de referencia desde la plantilla…"
  python seed.py
fi

echo
echo "──────────────────────────────────────────────"
echo "  Abre en el navegador:  http://127.0.0.1:8000"
echo "  Para detener: Ctrl+C"
echo "──────────────────────────────────────────────"
echo
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
