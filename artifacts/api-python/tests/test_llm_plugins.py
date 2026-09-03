"""Tests for pluggable LLM integration."""

from __future__ import annotations

import pytest

from app.integrations.llm import LlmConfig, resolve_plugin_id
from app.integrations.llm.registry import get_plugin


def test_resolve_plugin_id_openrouter() -> None:
    assert resolve_plugin_id("openrouter") == "openai_compat"


def test_resolve_plugin_id_openai() -> None:
    assert resolve_plugin_id("openai") == "openai_compat"


def test_resolve_plugin_id_unknown_defaults_to_openai_compat() -> None:
    assert resolve_plugin_id("some_future_vendor") == "openai_compat"


def test_get_plugin_openai_compat() -> None:
    plugin = get_plugin("openai_compat")
    assert plugin.plugin_id == "openai_compat"


def test_get_plugin_unknown_raises() -> None:
    with pytest.raises(Exception, match="Unknown LLM plugin"):
        get_plugin("nonexistent_plugin")


def test_llm_config_is_immutable() -> None:
    config = LlmConfig(
        provider="openrouter",
        plugin_id="openai_compat",
        api_key="sk-test",
        base_url="https://openrouter.ai/api/v1",
        model="test-model",
    )
    assert config.provider == "openrouter"


def test_deepseek_v4_payload_disables_reasoning() -> None:
    from app.integrations.llm.plugins.openai_compat import (
        _apply_provider_payload_tweaks,
        _model_prefers_no_reasoning,
    )

    assert _model_prefers_no_reasoning("deepseek/deepseek-v4-flash-0731")
    assert not _model_prefers_no_reasoning("openai/gpt-4o-mini")

    payload: dict = {"model": "deepseek/deepseek-v4-flash-0731"}
    _apply_provider_payload_tweaks(
        payload,
        LlmConfig(
            provider="openrouter",
            plugin_id="openai_compat",
            api_key="sk-test",
            base_url="https://openrouter.ai/api/v1",
            model="deepseek/deepseek-v4-flash-0731",
        ),
    )
    assert payload["reasoning"] == {"effort": "none"}
