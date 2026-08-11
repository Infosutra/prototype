#!/usr/bin/env bash
# Install / update Infosutra as a systemd service on the Raspberry Pi (option C).
#
# Run ON the Pi as user sarath (script will sudo for systemctl):
#   cd ~/work/Infosutra/DataInsightshub
#   ./scripts/install-systemd.sh
#
# Options:
#   --skip-build   skip frontend build (use existing dist/)
#   --no-start     install unit but do not start yet
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_NAME="infosutra"
UNIT_SRC="$ROOT_DIR/scripts/systemd/infosutra.service"
UNIT_DST="/etc/systemd/system/${SERVICE_NAME}.service"
EXPECTED_ROOT="/home/sarath/work/Infosutra"

SKIP_BUILD=0
NO_START=0
for arg in "$@"; do
  case "$arg" in
    --skip-build) SKIP_BUILD=1 ;;
    --no-start) NO_START=1 ;;
    -h|--help)
      sed -n '2,14p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown option: $arg" >&2
      exit 1
      ;;
  esac
done

if [[ "$(id -un)" != "sarath" ]]; then
  echo "Run this script as user sarath (current: $(id -un))." >&2
  exit 1
fi

if [[ "$ROOT_DIR" != "$EXPECTED_ROOT" ]]; then
  echo "Warning: install path is $ROOT_DIR"
  echo "         unit file expects $EXPECTED_ROOT"
  echo "Update scripts/systemd/infosutra.service WorkingDirectory/ExecStart if this is intentional."
  read -r -p "Continue anyway? [y/N] " reply
  case "${reply,,}" in
    y|yes) ;;
    *) echo "Cancelled."; exit 1 ;;
  esac
fi

chmod +x \
  "$ROOT_DIR/scripts/run-production.sh" \
  "$ROOT_DIR/scripts/build-frontend.sh" \
  "$ROOT_DIR/scripts/install-systemd.sh"

# Ensure uv
export PATH="${HOME}/.local/bin:${PATH}"
if ! command -v uv >/dev/null 2>&1; then
  echo "Installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="${HOME}/.local/bin:${PATH}"
fi

# Credentials
mkdir -p "$ROOT_DIR/.local" "$ROOT_DIR/data"
if [[ ! -f "$ROOT_DIR/.local/credentials.env" ]]; then
  umask 077
  printf 'KOBO_CREDENTIALS_ENCRYPTION_KEY=%s\n' \
    "$(openssl rand -base64 32)" > "$ROOT_DIR/.local/credentials.env"
  echo "Created $ROOT_DIR/.local/credentials.env"
  echo "If you already have data from your laptop, sync credentials.env instead or Kobo tokens won't decrypt."
fi

# Python deps
echo "Syncing Python dependencies..."
(cd "$ROOT_DIR/artifacts/api-python" && uv sync)

# Frontend production build
if (( SKIP_BUILD )); then
  echo "Skipping frontend build (--skip-build)."
else
  "$ROOT_DIR/scripts/build-frontend.sh"
fi

if [[ ! -f "$ROOT_DIR/artifacts/infosutra/dist/public/index.html" ]]; then
  echo "Frontend build missing. Run without --skip-build." >&2
  exit 1
fi

echo "Installing systemd unit → $UNIT_DST"
sudo cp "$UNIT_SRC" "$UNIT_DST"
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"

if (( NO_START )); then
  echo "Unit installed and enabled. Start later with: sudo systemctl start $SERVICE_NAME"
else
  echo "Starting $SERVICE_NAME..."
  sudo systemctl restart "$SERVICE_NAME"
  sleep 1
  sudo systemctl --no-pager --full status "$SERVICE_NAME" || true
fi

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo
echo "Done. Open: http://${IP:-<pi-ip>}:8080/"
echo "Logs:     journalctl -u $SERVICE_NAME -f"
echo "Restart:  sudo systemctl restart $SERVICE_NAME"
echo
echo "After syncing code from your laptop, rebuild UI + restart:"
echo "  ./scripts/build-frontend.sh && sudo systemctl restart $SERVICE_NAME"
