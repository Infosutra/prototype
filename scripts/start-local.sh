#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCAL_DIR="$ROOT_DIR/.local"
NODE_VERSION="v24.18.0"
API_PORT="${API_PORT:-8080}"
WEB_PORT="${WEB_PORT:-5173}"

mkdir -p "$LOCAL_DIR" "$ROOT_DIR/data"

node_major=0
if command -v node >/dev/null 2>&1; then
  node_major="$(node -p 'Number(process.versions.node.split(".")[0])' 2>/dev/null || echo 0)"
fi

if (( node_major < 22 )); then
  case "$(uname -m)" in
    x86_64) node_arch="x64" ;;
    aarch64|arm64) node_arch="arm64" ;;
    *)
      echo "Unsupported architecture: $(uname -m)" >&2
      exit 1
      ;;
  esac

  node_dir="$LOCAL_DIR/node-${NODE_VERSION}-linux-${node_arch}"
  if [[ ! -x "$node_dir/bin/node" ]]; then
    command -v curl >/dev/null 2>&1 || {
      echo "curl is required to download Node.js." >&2
      exit 1
    }
    archive="$LOCAL_DIR/node-${NODE_VERSION}-linux-${node_arch}.tar.xz"
    echo "Downloading Node.js ${NODE_VERSION}..."
    curl -fsSL \
      "https://nodejs.org/dist/${NODE_VERSION}/node-${NODE_VERSION}-linux-${node_arch}.tar.xz" \
      -o "$archive"
    tar -xJf "$archive" -C "$LOCAL_DIR"
    rm -f "$archive"
  fi
  export PATH="$node_dir/bin:$PATH"
fi

command -v corepack >/dev/null 2>&1 || {
  echo "Corepack is required but was not found." >&2
  exit 1
}
command -v openssl >/dev/null 2>&1 || {
  echo "OpenSSL is required to generate the local encryption key." >&2
  exit 1
}

# Ensure uv is available for the Python API
if ! command -v uv >/dev/null 2>&1; then
  echo "Installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
command -v uv >/dev/null 2>&1 || {
  echo "uv is required to run the Python API." >&2
  exit 1
}

credentials_file="$LOCAL_DIR/credentials.env"
if [[ ! -f "$credentials_file" ]]; then
  umask 077
  printf 'KOBO_CREDENTIALS_ENCRYPTION_KEY=%s\n' \
    "$(openssl rand -base64 32)" > "$credentials_file"
  echo "Created persistent credential encryption key in .local/credentials.env"
fi

# shellcheck disable=SC1090
source "$credentials_file"
export KOBO_CREDENTIALS_ENCRYPTION_KEY
export SECRET_KEY="${SECRET_KEY:-$KOBO_CREDENTIALS_ENCRYPTION_KEY}"
export DATABASE_PATH="$ROOT_DIR/data/infosutra.sqlite"
export PORT="$API_PORT"

cd "$ROOT_DIR"

# pnpm may report "Already up to date" while missing the current CPU's native
# optional deps (e.g. after copying node_modules between x86 and arm64).
arch="$(uname -m)"
needs_native_reinstall=0
case "$arch" in
  aarch64|arm64)
    if [[ -d node_modules ]] && ! compgen -G 'node_modules/.pnpm/@rollup+rollup-linux-arm64-gnu@*' >/dev/null; then
      needs_native_reinstall=1
    fi
    ;;
  x86_64)
    if [[ -d node_modules ]] && ! compgen -G 'node_modules/.pnpm/@rollup+rollup-linux-x64-gnu@*' >/dev/null; then
      needs_native_reinstall=1
    fi
    ;;
esac

if (( needs_native_reinstall )); then
  echo "Native Rollup binary for ${arch} is missing; clearing node_modules for a clean install..."
  find "$ROOT_DIR" -type d -name node_modules -prune -exec rm -rf {} +
fi

echo "Installing frontend dependencies..."
corepack enable >/dev/null 2>&1 || true
corepack pnpm install --frozen-lockfile

echo "Installing Python API dependencies..."
(cd "$ROOT_DIR/artifacts/api-python" && uv sync)

cleanup() {
  trap - EXIT INT TERM
  [[ -n "${API_PID:-}" ]] && kill -TERM -- "-$API_PID" 2>/dev/null || true
  [[ -n "${WEB_PID:-}" ]] && kill -TERM -- "-$WEB_PID" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "Starting API (FastAPI) at http://127.0.0.1:${API_PORT}"
# Job control so each bg job gets its own process group for Ctrl+C cleanup.
set -m
env \
  PYTHONUNBUFFERED=1 \
  PORT="$API_PORT" \
  DATABASE_PATH="$DATABASE_PATH" \
  SECRET_KEY="$SECRET_KEY" \
  KOBO_CREDENTIALS_ENCRYPTION_KEY="$KOBO_CREDENTIALS_ENCRYPTION_KEY" \
  SERVE_FRONTEND=0 \
  uv run --directory "$ROOT_DIR/artifacts/api-python" \
    python -u -m app.main &
API_PID=$!

echo "Starting dashboard at http://127.0.0.1:${WEB_PORT}"
env PORT="$WEB_PORT" BASE_PATH="/" API_URL="http://127.0.0.1:${API_PORT}" \
  corepack pnpm --filter @workspace/infosutra dev &
WEB_PID=$!

echo
echo "Open http://127.0.0.1:${WEB_PORT}/  (Vite — use this for local UI)"
echo "API only on http://127.0.0.1:${API_PORT}/api/"
echo "Press Ctrl+C to stop both services."

wait -n "$API_PID" "$WEB_PID"
