#!/usr/bin/env bash
# Production entrypoint for systemd: load secrets and run FastAPI (serves API + built UI).
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCAL_DIR="$ROOT_DIR/.local"
CREDENTIALS_FILE="$LOCAL_DIR/credentials.env"
API_DIR="$ROOT_DIR/artifacts/api-python"

export PATH="${HOME}/.local/bin:${LOCAL_DIR}/node-v24.18.0-linux-arm64/bin:${LOCAL_DIR}/node-v24.18.0-linux-x64/bin:${PATH}"

if [[ ! -f "$CREDENTIALS_FILE" ]]; then
  echo "Missing $CREDENTIALS_FILE — create it or sync from your laptop." >&2
  exit 1
fi

# shellcheck disable=SC1090
set -a
source "$CREDENTIALS_FILE"
set +a

export KOBO_CREDENTIALS_ENCRYPTION_KEY
export SECRET_KEY="${SECRET_KEY:-$KOBO_CREDENTIALS_ENCRYPTION_KEY}"
export DATABASE_PATH="${DATABASE_PATH:-$ROOT_DIR/data/infosutra.sqlite}"
export PORT="${PORT:-8080}"
export SERVE_FRONTEND=1

mkdir -p "$(dirname "$DATABASE_PATH")"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv not found on PATH. Install: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
  exit 1
fi

cd "$API_DIR"
# Ensure deps are present (cheap if already synced)
uv sync --frozen 2>/dev/null || uv sync

exec uv run uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
