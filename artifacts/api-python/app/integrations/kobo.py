from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

import httpx


class KoboApiError(Exception):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def normalize_kobo_server_url(value: str) -> str:
    raw = value.strip()
    try:
        # Ensure scheme for urlparse-like handling via httpx URL
        parsed = httpx.URL(raw if "://" in raw else f"https://{raw}")
    except Exception as exc:
        raise KoboApiError("Kobo server URL is invalid") from exc

    host = parsed.host or ""
    is_local = host in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and not is_local:
        raise KoboApiError("Kobo server URL must use HTTPS")

    return f"{parsed.scheme}://{host}".rstrip("/")


def get_asset_name(asset: dict[str, Any]) -> str:
    name = asset.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    if isinstance(name, dict):
        for value in name.values():
            if value:
                return str(value)
    return f"Kobo project {asset.get('uid', 'unknown')}"


def get_asset_status(asset: dict[str, Any]) -> str:
    if asset.get("is_archived") or asset.get("asset_type") == "archived":
        return "archived"
    if asset.get("deployment_status") == "deployed" or asset.get("deployment__active") is True:
        return "deployed"
    return "draft"


class KoboClient:
    def __init__(self, server_url: str, api_token: str, timeout: float = 30.0) -> None:
        if not api_token.strip():
            raise KoboApiError("Kobo API token is required")
        self.base_url = normalize_kobo_server_url(server_url)
        self._headers = {"Authorization": f"Token {api_token.strip()}"}
        self._timeout = timeout

    def _url(self, path: str) -> str:
        return urljoin(self.base_url + "/", path.lstrip("/"))

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        try:
            response = httpx.get(
                self._url(path),
                headers=self._headers,
                params=params,
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise KoboApiError(f"Kobo request failed: {exc}") from exc

        if response.status_code >= 400:
            raise KoboApiError(
                f"Kobo API error ({response.status_code}): {response.text[:300]}",
                status=response.status_code,
            )
        return response.json()

    def test_connection(self) -> None:
        self._get("/api/v2/assets/", params={"limit": 1})

    def list_assets(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        url_path = "/api/v2/assets/"
        params: dict[str, Any] | None = {"limit": 1000, "asset_type": "survey"}
        while True:
            payload = self._get(url_path, params=params) if params else self._get_absolute(url_path)
            if isinstance(payload, list):
                results.extend(payload)
                break
            batch = payload.get("results") or []
            results.extend(batch)
            next_url = payload.get("next")
            if not next_url:
                break
            url_path = next_url
            params = None
        return results

    def _get_absolute(self, url: str) -> Any:
        try:
            response = httpx.get(url, headers=self._headers, timeout=self._timeout)
        except httpx.HTTPError as exc:
            raise KoboApiError(f"Kobo request failed: {exc}") from exc
        if response.status_code >= 400:
            raise KoboApiError(
                f"Kobo API error ({response.status_code}): {response.text[:300]}",
                status=response.status_code,
            )
        return response.json()

    def get_asset(self, uid: str) -> dict[str, Any]:
        return self._get(f"/api/v2/assets/{uid}/")

    def list_submissions(
        self,
        asset_uid: str,
        *,
        modified_after: str | None = None,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        params: dict[str, Any] = {"limit": 1000}
        if modified_after:
            # Kobo submission payloads expose _submission_time; _date_modified is
            # often null, so watermark queries on that field silently return nothing.
            params["query"] = (
                '{"_submission_time": {"$gt": "' + modified_after + '"}}'
            )

        path = f"/api/v2/assets/{asset_uid}/data/"
        absolute: str | None = None
        while True:
            payload = (
                self._get_absolute(absolute)
                if absolute
                else self._get(path, params=params)
            )
            if isinstance(payload, list):
                results.extend(payload)
                break
            batch = payload.get("results") or []
            results.extend(batch)
            next_url = payload.get("next")
            if not next_url:
                break
            absolute = next_url
            params = {}
        return results

    def list_versions(self, asset_uid: str) -> list[dict[str, Any]]:
        payload = self._get(f"/api/v2/assets/{asset_uid}/versions/")
        if isinstance(payload, list):
            return payload
        return payload.get("results") or []
