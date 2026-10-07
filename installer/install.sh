#!/usr/bin/env bash
# JobTracker AI · instalador para macOS
#
#   curl -fsSL https://github.com/Niick-pixel/Job/releases/latest/download/install.sh | bash
#
# Opciones:
#   --tarball FILE --manifest FILE   instala desde ficheros locales (lo usa el .pkg)
#   --non-interactive                no pregunta la API key
#
# Variables útiles: JOBTRACKER_HOME, JOBTRACKER_MANIFEST_URL, JOBTRACKER_PYTHON (forzar intérprete)
set -euo pipefail

MANIFEST_URL="${JOBTRACKER_MANIFEST_URL:-https://github.com/Niick-pixel/Job/releases/latest/download/manifest.json}"
UV_VERSION="0.8.0"
# SHA-256 publicados por Astral para uv ${UV_VERSION} (fijados: no se confía en lo que se descarga)
UV_SHA_aarch64_apple_darwin="5a5ca58e3999d4f440632da87a56f7030eaaa3a13d3896561eec5fd51cb9ad45"
UV_SHA_x86_64_apple_darwin="828917cad79aae8327811c59fcc625ff3861bfe21d2cbb77c206737d41117ff2"
UV_SHA_x86_64_unknown_linux_gnu="a7d74ee5c5ff3069b9d88236a05f293cc4e2809bad872f3a88a384489ba3675e"  # solo para CI
PYTHON_VERSION="3.12"

TARBALL="" MANIFEST="" INTERACTIVE=1
while [ $# -gt 0 ]; do
  case "$1" in
    --tarball) TARBALL="$2"; shift 2 ;;
    --manifest) MANIFEST="$2"; shift 2 ;;
    --non-interactive) INTERACTIVE=0; shift ;;
    *) echo "Opción desconocida: $1" >&2; exit 2 ;;
  esac
done

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
info() { printf '  → %s\n' "$*"; }
die()  { printf '\033[31m✖ %s\033[0m\n' "$*" >&2; exit 1; }

OS="$(uname -s)"
if [ "$OS" != "Darwin" ] && [ "${JOBTRACKER_ALLOW_NON_MAC:-0}" != "1" ]; then
  die "Este instalador es para macOS."
fi
if [ "$OS" = "Darwin" ]; then
  HOME_DIR="${JOBTRACKER_HOME:-$HOME/Library/Application Support/JobTrackerAI}"
else
  HOME_DIR="${JOBTRACKER_HOME:-$HOME/.local/share/jobtracker-ai}"
fi
export JOBTRACKER_HOME="$HOME_DIR"
mkdir -p "$HOME_DIR/tools"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

fetch() { curl -fsSL --retry 3 --connect-timeout 15 -o "$2" "$1"; }
sha256() { if command -v shasum >/dev/null; then shasum -a 256 "$1" | cut -d' ' -f1; else sha256sum "$1" | cut -d' ' -f1; fi; }

bold "💼 Instalando JobTracker AI"

# ── 1. Intérprete de Python ───────────────────────────────────
# Por defecto se usa un Python propio gestionado por uv dentro de la carpeta de la app:
# no depende de Homebrew ni del Python del sistema, y no necesita permisos de administrador.
PY="${JOBTRACKER_PYTHON:-}"
UV=""
if [ -z "$PY" ] && [ "${JOBTRACKER_NO_UV:-0}" != "1" ]; then
  ARCH="$(uname -m)"; [ "$ARCH" = "arm64" ] && ARCH="aarch64"
  if [ "$OS" = "Darwin" ]; then TRIPLE="${ARCH}-apple-darwin"; else TRIPLE="${ARCH}-unknown-linux-gnu"; fi
  VAR="UV_SHA_${TRIPLE//-/_}"
  EXPECTED="${!VAR:-}"
  UV="$HOME_DIR/tools/uv"
  if [ -n "$EXPECTED" ] && ! { [ -x "$UV" ] && "$UV" --version 2>/dev/null | grep -q "$UV_VERSION"; }; then
    info "Descargando uv $UV_VERSION ($TRIPLE)…"
    if fetch "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-${TRIPLE}.tar.gz" "$WORK/uv.tgz" \
       && [ "$(sha256 "$WORK/uv.tgz")" = "$EXPECTED" ]; then
      tar -xzf "$WORK/uv.tgz" -C "$WORK"
      install -m 755 "$WORK/uv-${TRIPLE}/uv" "$UV"
    else
      info "No se pudo obtener uv; se buscará un Python del sistema."
      UV=""
    fi
  fi
  if [ -n "$UV" ] && [ -x "$UV" ]; then
    export UV_PYTHON_INSTALL_DIR="$HOME_DIR/python" UV_PYTHON_PREFERENCE=only-managed
    info "Preparando Python $PYTHON_VERSION…"
    "$UV" python install --quiet "$PYTHON_VERSION"
    PY="$("$UV" python find "$PYTHON_VERSION")"
  else
    UV=""
  fi
fi
if [ -z "$PY" ]; then
  for cand in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$cand" >/dev/null && "$cand" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
      PY="$(command -v "$cand")"; break
    fi
  done
fi
[ -n "$PY" ] || die "Se necesita Python ≥ 3.10. Instálalo con 'brew install python@3.12' o desde python.org."
info "Python: $PY ($("$PY" -c 'import platform; print(platform.python_version())'))"

# ── 2. Release: manifiesto + paquete verificado ───────────────
if [ -z "$TARBALL" ]; then
  info "Consultando la última versión…"
  MANIFEST="$WORK/manifest.json"
  fetch "$MANIFEST_URL" "$MANIFEST" || die "No se pudo descargar el manifiesto ($MANIFEST_URL)"
  URL="$("$PY" -c 'import json,sys,urllib.parse as u; m=json.load(open(sys.argv[1])); print(u.urljoin(sys.argv[2], m["url"]))' "$MANIFEST" "$MANIFEST_URL")"
  TARBALL="$WORK/jobtracker-ai.tar.gz"
  info "Descargando $(basename "$URL")…"
  fetch "$URL" "$TARBALL" || die "No se pudo descargar el paquete"
fi
[ -f "$TARBALL" ] && [ -f "$MANIFEST" ] || die "Faltan el paquete o el manifiesto"
WANT="$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))["sha256"])' "$MANIFEST")"
[ "$(sha256 "$TARBALL")" = "$WANT" ] || die "El SHA-256 del paquete no coincide con el manifiesto"
info "Paquete verificado (SHA-256)"

mkdir -p "$WORK/src"
tar -xzf "$TARBALL" -C "$WORK/src"
SRC="$(find "$WORK/src" -mindepth 1 -maxdepth 1 -type d | head -n1)"

# ── 3. Instalación (firma, venv, health check, .app, servicios) ─
"$PY" "$SRC/installer/jobtracker.py" install \
  --tarball "$TARBALL" --manifest "$MANIFEST" --python "$PY" ${UV:+--uv "$UV"} \
  ${JOBTRACKER_MANIFEST_URL:+--manifest-url "$JOBTRACKER_MANIFEST_URL"} \
  ${JOBTRACKER_NO_START:+--no-start}

# ── 4. API key (solo si hay terminal) ─────────────────────────
ENV_FILE="$HOME_DIR/.env"
if [ "$INTERACTIVE" = "1" ] && [ -r /dev/tty ] && ! grep -q '^ANTHROPIC_API_KEY=sk-' "$ENV_FILE" 2>/dev/null; then
  printf '  🔑 Pega tu ANTHROPIC_API_KEY (Enter para hacerlo después): '
  read -rs KEY < /dev/tty || KEY=""
  echo
  if [ -n "$KEY" ]; then
    "$PY" "$HOME_DIR/current/installer/jobtracker.py" config api-key "$KEY" >/dev/null
    info "Clave guardada en $ENV_FILE (permisos 600)"
  fi
fi

echo
bold "✅ Listo"
echo "  • Abre «JobTracker AI» desde ~/Applications (o Spotlight)"
echo "  • CLI: ~/.local/bin/jobtracker status | update | rollback | logs | uninstall"
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) echo "  • Añade ~/.local/bin a tu PATH:  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.zshrc" ;; esac
echo "  • Las actualizaciones se comprueban solas cada 6 h (jobtracker config auto-update off para desactivarlo)"
