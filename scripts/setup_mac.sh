#!/usr/bin/env bash
# Instalación en macOS (Apple Silicon o Intel).
set -euo pipefail
cd "$(dirname "$0")/.."

if ! command -v brew >/dev/null; then
  echo "Instala Homebrew primero: https://brew.sh" && exit 1
fi
brew list python@3.12 >/dev/null 2>&1 || brew install python@3.12

PY="$(brew --prefix python@3.12)/bin/python3.12"
"$PY" -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

[ -f .env ] || { cp .env.example .env; echo "→ Edita .env y añade tu ANTHROPIC_API_KEY"; }
mkdir -p data/uploads
echo "✅ Listo. Ejecuta: make dev"
