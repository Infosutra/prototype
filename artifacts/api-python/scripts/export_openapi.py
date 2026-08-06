#!/usr/bin/env python3
"""Export OpenAPI spec from FastAPI app to lib/api-spec/openapi.yaml.

Import-only — no server and no database required.

Paths are rewritten without the `/api` prefix and `servers` is set to `/api`
so Orval's `baseUrl: "/api"` produces `/api/...` (not `/api/api/...`).
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]  # Data-Insights-Hub
OUT = ROOT / "lib" / "api-spec" / "openapi.yaml"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app  # noqa: E402


HEADER = (
    "# GENERATED FILE — do not edit by hand.\n"
    "# Source of truth: FastAPI app (artifacts/api-python).\n"
    "# Regenerate with: pnpm run api:spec\n"
)


def _strip_api_prefix(spec: dict) -> dict:
    """Match the historical hand-written contract: paths relative to /api."""
    paths = spec.get("paths") or {}
    rewritten: dict = {}
    for path, item in paths.items():
        if path == "/api" or path.startswith("/api/"):
            new_path = path[4:] or "/"
        else:
            new_path = path
        rewritten[new_path] = item
    spec["paths"] = rewritten
    spec["servers"] = [{"url": "/api", "description": "Base API path"}]
    # Keep Orval title stable for generated import paths.
    info = spec.setdefault("info", {})
    info["title"] = "Api"
    return spec


def main() -> None:
    spec = _strip_api_prefix(app.openapi())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    body = yaml.safe_dump(spec, sort_keys=False, allow_unicode=True)
    OUT.write_text(HEADER + body, encoding="utf-8")
    paths = len(spec.get("paths") or {})
    print(f"Wrote {OUT} ({paths} paths)")


if __name__ == "__main__":
    main()
