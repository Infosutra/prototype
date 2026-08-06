# Infosutra API (Python)

FastAPI backend for the Infosutra dashboard.

## Run locally

```bash
# from repo root (preferred)
./scripts/start-local.sh

# or manually
cd artifacts/api-python
uv sync
export DATABASE_PATH=../../data/infosutra.sqlite
export SECRET_KEY=...   # or KOBO_CREDENTIALS_ENCRYPTION_KEY
export PORT=8080
uv run uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```

Fresh SQLite is created automatically. Configure Kobo in Settings, then Sync.
