#!/usr/bin/env bash
# Reset LOCAL Infosutra SQLite only — preserves Settings, never contacts Kobo.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DB_PATH="${DATABASE_PATH:-$ROOT/data/infosutra.sqlite}"

echo "This will wipe LOCAL data at:"
echo "  $DB_PATH"
echo "Settings (Kobo/SMTP/etc.) will be preserved."
echo "KoboToolbox will NOT be contacted."
echo ""

export ALLOW_LOCAL_DB_RESET=1
export DATABASE_PATH="$DB_PATH"
export PATH="${HOME}/.local/bin:${PATH}"

cd "$ROOT/artifacts/api-python"
uv run python -m app.services.local_reset

echo ""
echo "Next steps (optional):"
echo "  1. Restart the API (./scripts/start-local.sh or your uvicorn process)"
echo "  2. Sync from Kobo in Settings / Projects — READ-ONLY pull from Kobo"
echo "  3. Forms will auto-attach to Sightsavers 2030 by UID"
