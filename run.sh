#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$ROOT_DIR/.venv"
ENV_FILE="$ROOT_DIR/.env"

info() { echo "[screeny] $*"; }

if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
  info "Do not run as root. Re-run as your normal user."
  exit 1
fi

info "Installing system packages"
sudo apt update
sudo apt install -y libmagic1 python3-pygame ddcutil i2c-tools

info "Ensuring i2c-dev is loaded"
sudo modprobe i2c-dev || true

if [[ ! -f "$ENV_FILE" ]]; then
  info "Writing default .env"
  cat > "$ENV_FILE" <<'EOF'
BIND_HOST=0.0.0.0
BIND_PORT=5000
DATA_DIR=/opt/screeny/data
DDCUTIL_PATH=/usr/bin/ddcutil
DDC_TARGET=auto
DDC_TIMEOUT_MS=2000
DDC_RETRY_COUNT=1
DDC_COALESCE_MS=75
DISABLE_DPMS=1
SERVER_URL=http://127.0.0.1:5000
EOF
fi

info "Creating data directory"
sudo mkdir -p /opt/screeny/data
sudo chown -R "$USER":"$USER" /opt/screeny

info "Setting up virtualenv"
python3 -m venv --system-site-packages "$VENV_DIR"
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
python -m pip install --upgrade pip
pip install -r "$ROOT_DIR/requirements.txt"

info "Checking DDC availability"
if ! command -v ddcutil >/dev/null 2>&1; then
  info "ddcutil not found. Install it or adjust DDCUTIL_PATH."
else
  if ! ddcutil detect --brief >/tmp/screeny-ddc-detect.txt 2>&1; then
    info "ddcutil detect failed. Output:"
    cat /tmp/screeny-ddc-detect.txt
  else
    info "ddcutil detect output:"
    cat /tmp/screeny-ddc-detect.txt
  fi
fi

info "Starting services (web + renderer)"
export $(grep -v '^#' "$ENV_FILE" | xargs -d '\n')

info "Installing desktop autostart for renderer (Option A)"
AUTOSTART_DIR="$HOME/.config/autostart"
mkdir -p "$AUTOSTART_DIR"
cat > "$AUTOSTART_DIR/screeny.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Screeny Renderer
Exec=$VENV_DIR/bin/python -m renderer.main
X-GNOME-Autostart-enabled=true
EOF

info "Launching web API"
python -m hdmi_control.app &
WEB_PID=$!

info "Launching renderer"
python -m renderer.main &
RENDER_PID=$!

cleanup() {
  info "Stopping..."
  kill "$WEB_PID" "$RENDER_PID" 2>/dev/null || true
  wait "$WEB_PID" "$RENDER_PID" 2>/dev/null || true
}

trap cleanup INT TERM

info "Running. Web PID=$WEB_PID Renderer PID=$RENDER_PID"
info "Open http://127.0.0.1:5000"
wait $WEB_PID $RENDER_PID
