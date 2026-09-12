# Infosutra API (Python)

FastAPI backend for the Infosutra dashboard.

## Run locally

```bash
# from repo root (preferred — Vite UI + API)
./scripts/start-local.sh

# API only (production-style: serves built UI when SERVE_FRONTEND=1)
cd artifacts/api-python
uv sync
export DATABASE_PATH=../../data/infosutra.sqlite
export SECRET_KEY=...   # or KOBO_CREDENTIALS_ENCRYPTION_KEY
export PORT=8080
uv run python -m app.main
```

Use `python -m app.main` (or the `infosutra-api` console script). That entrypoint configures structured JSON logging on stdout before uvicorn starts. Do not launch with raw `uvicorn app.main:app` unless you call `setup_logging()` yourself.

On the Pi under systemd, logs are JSON lines in the journal:

```bash
journalctl -u infosutra -f
```

Fresh SQLite is created automatically. Configure Kobo in study settings, then Sync.

Study sync overlaps Kobo HTTP across forms (default 4 workers), then serializes
SQLite writes. Override with `KOBO_SYNC_CONCURRENCY` (1–8; use `1` for sequential).
