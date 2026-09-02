"""Build LlmConfig from install settings."""

from __future__ import annotations

from app.db.models import AppSettings
from app.integrations.llm.registry import resolve_plugin_id
from app.integrations.llm.types import DEFAULT_BASE_URL, DEFAULT_MODEL, LlmConfig

OPENROUTER_EXTRA_HEADERS = {
    "HTTP-Referer": "https://infosutra.local",
    "X-Title": "Infosutra",
}


def llm_config_from_app_settings(settings: AppSettings) -> LlmConfig:
    provider = (settings.ai_provider or "openrouter").strip().lower()
    plugin_id = resolve_plugin_id(provider)
    extra_headers: dict[str, str] = {}
    if provider == "openrouter":
        extra_headers = dict(OPENROUTER_EXTRA_HEADERS)

    return LlmConfig(
        provider=provider,
        plugin_id=plugin_id,
        api_key=(settings.ai_api_key or "").strip(),
        base_url=(settings.ai_base_url or DEFAULT_BASE_URL).strip(),
        model=(settings.ai_model or DEFAULT_MODEL).strip(),
        extra_headers=extra_headers,
    )
