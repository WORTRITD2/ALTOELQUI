#!/usr/bin/env bash
# Genera la configuración del cliente y las reglas de proxy hacia la API.
# Variable de entorno esperada en Netlify:
#   API_URL = https://mi-api-de-obra.onrender.com   (sin barra final)
set -euo pipefail

API_URL="${API_URL:-}"

cat > frontend/config.js <<'JS'
// Generado en el build. Mismo origen: Netlify hace de proxy hacia la API.
window.CONFIG = { API_URL: "" };
JS

{
  if [ -n "$API_URL" ]; then
    printf '/api/*  %s/api/:splat  200\n' "${API_URL%/}"
  else
    echo "⚠  API_URL no configurada: la app se publicará sin backend." >&2
  fi
  printf '/*  /index.html  200\n'
} > frontend/_redirects

echo "Publicando frontend/ con API_URL='${API_URL:-<no configurada>}'"
