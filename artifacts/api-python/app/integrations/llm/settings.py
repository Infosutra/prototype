"""Build LlmConfig from install settings."""

from __future__ import annotations

from app.db.models import AppSettings
from app.integrations.llm.types import DEFAULT_BASE_URL, DEFAULT_MODEL, LlmConfig

OPENROUTER_EXTRA_HEADERS = {
    "HTTP-Referer": "https://infosutra.local",
    "X-Title": "Infosutra",
}


def llm_config_from_app_settings(settings: AppSettings) -> LlmConfig:
    return _llm_config_from_app_settings(
        settings, model=(settings.ai_model or DEFAULT_MODEL).strip()
    )


def llm_compile_config_from_app_settings(settings: AppSettings) -> LlmConfig:
    """Config for DQA English→rule compilation (structured output)."""
    compile_model = (getattr(settings, "ai_compile_model", None) or "").strip()
    model = compile_model or (settings.ai_model or DEFAULT_MODEL).strip()
    return _llm_config_from_app_settings(settings, model=model)


def llm_plan_config_from_app_settings(settings: AppSettings) -> LlmConfig:
    """Config for free-form report planning (structured ReportSpec output).

    Uses ``ai_reporting_plan_model`` when set; otherwise ``ai_model`` directly.
    Does **not** fall back through ``ai_compile_model``.
    """
    planner_model = (getattr(settings, "ai_reporting_plan_model", None) or "").strip()
    model = planner_model or (settings.ai_model or DEFAULT_MODEL).strip()
    return _llm_config_from_app_settings(settings, model=model)


def _llm_config_from_app_settings(settings: AppSettings, *, model: str) -> LlmConfig:
    provider = (settings.ai_provider or "openrouter").strip().lower()
    extra_headers: dict[str, str] = {}
    if provider == "openrouter":
        extra_headers = dict(OPENROUTER_EXTRA_HEADERS)

    return LlmConfig(
        provider=provider,
        api_key=(settings.ai_api_key or "").strip(),
        base_url=(settings.ai_base_url or DEFAULT_BASE_URL).strip(),
        model=model,
        extra_headers=extra_headers,
    )
