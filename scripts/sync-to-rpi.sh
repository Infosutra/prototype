#!/usr/bin/env bash
# Sync Infosutra source to the Raspberry Pi (excludes installable packages).
#
# Usage:
#   ./scripts/sync-to-rpi.sh              # 2 prompts: sync choice + advanced?
#   ./scripts/sync-to-rpi.sh --with-db     # code + audio + SQLite only (leaves data/reports/)
#   ./scripts/sync-to-rpi.sh --with-data   # code + audio + full data/
#   ./scripts/sync-to-rpi.sh --no-audio    # skip data/audio/ (recordings + transcripts)
#   ./scripts/sync-to-rpi.sh --dry-run
#   ./scripts/sync-to-rpi.sh --no-deploy   # sync only; skip remote build/restart
#   ./scripts/sync-to-rpi.sh --yes        # for cron (deploys unless --no-deploy)
#
# Cron example:
#   0 * * * * /path/to/scripts/sync-to-rpi.sh --yes >>/tmp/infosutra-rpi-sync.log 2>&1

set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

RPI_USER="${RPI_USER:-sarath}"
RPI_HOST="${RPI_HOST:-192.168.1.253}"
RPI_PATH="${RPI_PATH:-~/work/Infosutra}"

WITH_DATA=0
WITH_DB=0
WITH_AUDIO=1
DRY_RUN=0
SYNC_CREDS=1
DEPLOY=1 # after live sync: build frontend + restart systemd on Pi
HAD_FLAGS=0

ask_yes_no() {
  local prompt="$1"
  local default="${2:-n}" # y|n
  local reply
  if [[ "$default" == "y" ]]; then
    read -r -p "$prompt [Y/n] " reply || true
    reply="${reply:-y}"
  else
    read -r -p "$prompt [y/N] " reply || true
    reply="${reply:-n}"
  fi
  case "${reply,,}" in
    y|yes) return 0 ;;
    *) return 1 ;;
  esac
}

print_help() {
  sed -n '2,15p' "$0"
}

apply_sync_choice() {
  local choice="$1"
  case "$choice" in
    1)
      WITH_DATA=0
      WITH_DB=0
      WITH_AUDIO=0
      DRY_RUN=0
      ;;
    2)
      WITH_DATA=0
      WITH_DB=1
      WITH_AUDIO=1
      DRY_RUN=0
      ;;
    3)
      WITH_DATA=1
      WITH_DB=0
      WITH_AUDIO=1
      DRY_RUN=0
      ;;
    4)
      WITH_DATA=0
      WITH_DB=0
      DRY_RUN=1
      ;;
    5|q|Q)
      echo "Cancelled."
      exit 0
      ;;
    *)
      echo "Invalid choice: $choice" >&2
      exit 1
      ;;
  esac
}

sync_sqlite_db() {
  local db_dir="${ROOT_DIR}/data"
  local remote_db="${RPI_USER}@${RPI_HOST}:${RPI_PATH%/}/data/"
  local found=0

  echo "Syncing SQLite database (infosutra.sqlite)"
  for pattern in infosutra.sqlite infosutra.sqlite-wal infosutra.sqlite-shm; do
    if [[ -f "${db_dir}/${pattern}" ]]; then
      found=1
      rsync -avh --progress "${RSYNC_DRY[@]}" \
        "${db_dir}/${pattern}" \
        "${remote_db}"
    fi
  done

  if (( ! found )); then
    echo "Skipped SQLite DB (no local infosutra.sqlite found)."
  fi
}

remote_deploy() {
  local remote_root="${RPI_PATH%/}"
  echo
  echo "Deploying on Pi (build frontend + restart infosutra)..."
  # -t so sudo can prompt for a password if needed
  ssh -t "${RPI_USER}@${RPI_HOST}" \
    "cd ${remote_root} && chmod +x scripts/build-frontend.sh scripts/run-production.sh && ./scripts/build-frontend.sh && sudo systemctl restart infosutra && sudo systemctl --no-pager --full status infosutra"
  echo "Deploy finished."
}

for arg in "$@"; do
  HAD_FLAGS=1
  case "$arg" in
    --with-data) WITH_DATA=1; WITH_DB=0; WITH_AUDIO=1 ;;
    --with-db) WITH_DB=1; WITH_AUDIO=1 ;;
    --no-audio) WITH_AUDIO=0 ;;
    --with-audio) WITH_AUDIO=1 ;;
    --dry-run) DRY_RUN=1 ;;
    --no-creds) SYNC_CREDS=0 ;;
    --no-deploy) DEPLOY=0 ;;
    --deploy) DEPLOY=1 ;;
    --yes|-y) ;; # accepted for cron
    --interactive|-i) HAD_FLAGS=0 ;; # force interactive menu
    -h|--help)
      print_help
      exit 0
      ;;
    *)
      echo "Unknown option: $arg" >&2
      echo "Use --with-db, --with-data, --with-audio, --no-audio, --dry-run, --no-creds, --no-deploy, --deploy, --yes, or --help" >&2
      exit 1
      ;;
  esac
done

if (( ! HAD_FLAGS )) && [[ -t 0 ]]; then
  echo "Infosutra → Raspberry Pi sync"
  echo "  ${RPI_USER}@${RPI_HOST}:${RPI_PATH}"
  echo
  echo "What do you want to sync?"
  echo "  1) Code deploy only (no recordings on Pi dashboard)"
  echo "  2) Code + audio + SQLite DB (default — shows recordings on Pi)"
  echo "  3) Code + audio + full data/"
  echo "  4) Dry run"
  echo "  5) Cancel"
  read -r -p "Choice [2]: " choice
  apply_sync_choice "${choice:-2}"

  if ask_yes_no "Advanced options?" "n"; then
    echo
    read -r -p "  User  [${RPI_USER}]: " input && RPI_USER="${input:-$RPI_USER}"
    read -r -p "  Host  [${RPI_HOST}]: " input && RPI_HOST="${input:-$RPI_HOST}"
    read -r -p "  Path  [${RPI_PATH}]: " input && RPI_PATH="${input:-$RPI_PATH}"

    if (( DRY_RUN )) && ask_yes_no "  Include full data/ in dry-run listing?" "n"; then
      WITH_DATA=1
      WITH_DB=0
      WITH_AUDIO=1
    elif (( DRY_RUN )) && ask_yes_no "  Include SQLite DB in dry-run listing?" "n"; then
      WITH_DB=1
      WITH_AUDIO=1
    elif (( DRY_RUN )) && ask_yes_no "  Include data/audio/ in dry-run listing?" "y"; then
      WITH_AUDIO=1
    elif (( DRY_RUN )); then
      WITH_AUDIO=0
    fi

    if (( ! DRY_RUN )) && ask_yes_no "  Sync data/audio/ (recordings + transcripts)?" "y"; then
      WITH_AUDIO=1
    elif (( ! DRY_RUN )); then
      WITH_AUDIO=0
    fi

    if (( ! DRY_RUN )) && (( ! WITH_DATA )) && ask_yes_no "  Sync SQLite DB (infosutra.sqlite)?" "n"; then
      WITH_DB=1
    fi

    if [[ -f "${ROOT_DIR}/.local/credentials.env" ]]; then
      if ask_yes_no "  Sync credentials.env?" "y"; then
        SYNC_CREDS=1
      else
        SYNC_CREDS=0
      fi
    else
      SYNC_CREDS=0
      echo "  (no local credentials.env found)"
    fi

    if (( ! DRY_RUN )); then
      if ask_yes_no "  Rebuild UI & restart infosutra on Pi after sync?" "y"; then
        DEPLOY=1
      else
        DEPLOY=0
      fi
    fi
  fi
elif (( ! HAD_FLAGS )) && [[ ! -t 0 ]]; then
  echo "Non-interactive shell with no flags — refusing to guess." >&2
  echo "Pass --yes (and optional --with-db / --with-data / --dry-run / --no-deploy) for cron." >&2
  exit 1
fi

REMOTE="${RPI_USER}@${RPI_HOST}:${RPI_PATH%/}/"
RSYNC_DRY=()
if (( DRY_RUN )); then
  RSYNC_DRY=(--dry-run)
  DEPLOY=0
  echo "DRY RUN — no files will be written on the Pi."
fi

echo "Syncing ${ROOT_DIR}/ → ${REMOTE}"

# Ensure remote dirs exist (skip for dry-run to avoid side effects)
if (( ! DRY_RUN )); then
  ssh "${RPI_USER}@${RPI_HOST}" "mkdir -p '${RPI_PATH%/}/.local' '${RPI_PATH%/}/data' '${RPI_PATH%/}/data/audio'"
fi

rsync -avh --delete --progress "${RSYNC_DRY[@]}" \
  --exclude '.git/' \
  --exclude 'node_modules/' \
  --exclude '**/node_modules/' \
  --exclude '.venv/' \
  --exclude '**/.venv/' \
  --exclude '.local/' \
  --exclude '**/__pycache__/' \
  --exclude '**/*.pyc' \
  --exclude '**/dist/' \
  --exclude '**/*.tsbuildinfo' \
  --exclude '.cache/' \
  --exclude '/data/***' \
  --exclude '/artifacts/mockup-sandbox/***' \
  --exclude '/.agents/***' \
  --exclude '/.cursor/***' \
  --exclude 'replit.md' \
  --exclude '.replit' \
  --exclude '.replitignore' \
  --exclude '*.log' \
  "${ROOT_DIR}/" \
  "${REMOTE}"

if (( SYNC_CREDS )) && [[ -f "${ROOT_DIR}/.local/credentials.env" ]]; then
  echo "Syncing credentials.env"
  rsync -avh "${RSYNC_DRY[@]}" \
    "${ROOT_DIR}/.local/credentials.env" \
    "${RPI_USER}@${RPI_HOST}:${RPI_PATH%/}/.local/"
elif (( ! SYNC_CREDS )); then
  echo "Skipped credentials.env."
else
  echo "Note: no .local/credentials.env on this machine (Pi will generate its own on first start)."
fi

if (( WITH_AUDIO )) && (( ! WITH_DATA )); then
  if [[ -d "${ROOT_DIR}/data/audio" ]]; then
    echo "Syncing data/audio/ (recordings + transcripts)"
    rsync -avh --delete --progress "${RSYNC_DRY[@]}" \
      "${ROOT_DIR}/data/audio/" \
      "${RPI_USER}@${RPI_HOST}:${RPI_PATH%/}/data/audio/"
  else
    echo "Skipped data/audio/ (no local data/audio directory)."
  fi
elif (( WITH_AUDIO )) && (( WITH_DATA )); then
  echo "data/audio/ will be included in full data/ sync."
elif (( ! WITH_AUDIO )); then
  echo "Skipped data/audio/."
fi

if (( WITH_DATA )); then
  echo "Syncing data/ (SQLite + reports + all data)"
  rsync -avh --delete --progress "${RSYNC_DRY[@]}" \
    "${ROOT_DIR}/data/" \
    "${RPI_USER}@${RPI_HOST}:${RPI_PATH%/}/data/"
elif (( WITH_DB )); then
  sync_sqlite_db
else
  echo "Skipped SQLite DB and other data/."
fi

if (( WITH_AUDIO )) && (( ! WITH_DB )) && (( ! WITH_DATA )) && (( ! DRY_RUN )); then
  echo
  echo "Note: audio files were synced but not infosutra.sqlite."
  echo "      The Pi dashboard lists recordings from the database — re-run with option 2 or --with-db."
fi

echo
if (( DRY_RUN )); then
  echo "Dry run complete — nothing was written."
elif (( DEPLOY )); then
  remote_deploy
  echo "Done. UI + API should be live on http://${RPI_HOST}:8080/"
else
  echo "Done (sync only; deploy skipped)."
  echo "To deploy manually on the Pi:"
  echo "  cd ${RPI_PATH%/} && ./scripts/build-frontend.sh && sudo systemctl restart infosutra"
fi
