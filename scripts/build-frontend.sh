#!/usr/bin/env bash
# Build the Infosutra frontend for production (static files served by FastAPI).
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCAL_DIR="$ROOT_DIR/.local"
NODE_VERSION="v24.18.0"

ensure_node() {
  local node_major=0
  if command -v node >/dev/null 2>&1; then
    node_major="$(node -p 'Number(process.versions.node.split(".")[0])' 2>/dev/null || echo 0)"
  fi
  if (( node_major >= 22 )); then
    return 0
  fi
  case "$(uname -m)" in
    x86_64) local node_arch="x64" ;;
    aarch64|arm64) local node_arch="arm64" ;;
    *)
      echo "Unsupported architecture: $(uname -m)" >&2
      exit 1
      ;;
  esac
  local node_dir="$LOCAL_DIR/node-${NODE_VERSION}-linux-${node_arch}"
  if [[ ! -x "$node_dir/bin/node" ]]; then
    mkdir -p "$LOCAL_DIR"
    local archive="$LOCAL_DIR/node-${NODE_VERSION}-linux-${node_arch}.tar.xz"
    echo "Downloading Node.js ${NODE_VERSION}..."
    curl -fsSL \
      "https://nodejs.org/dist/${NODE_VERSION}/node-${NODE_VERSION}-linux-${node_arch}.tar.xz" \
      -o "$archive"
    tar -xJf "$archive" -C "$LOCAL_DIR"
    rm -f "$archive"
  fi
  export PATH="$node_dir/bin:$PATH"
}

ensure_node
command -v corepack >/dev/null 2>&1 || {
  echo "corepack (Node) is required" >&2
  exit 1
}
corepack enable >/dev/null 2>&1 || true

cd "$ROOT_DIR"
echo "Installing frontend dependencies..."
corepack pnpm install --frozen-lockfile

echo "Building @workspace/infosutra..."
# Same-origin /api in production — no Vite proxy needed.
env BASE_PATH="/" \
  corepack pnpm --filter @workspace/infosutra build

OUT="$ROOT_DIR/artifacts/infosutra/dist/public"
if [[ ! -f "$OUT/index.html" ]]; then
  echo "Build failed: missing $OUT/index.html" >&2
  exit 1
fi
echo "Frontend built → $OUT"
