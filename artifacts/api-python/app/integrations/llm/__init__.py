"""LLM chat completions via pluggable providers."""

from __future__ import annotations

from app.integrations.llm.errors import LlmError
from app.integrations.llm.registry import get_plugin, register_plugin, resolve_plugin_id
from app.integrations.llm.settings import llm_config_from_app_settings
from app.integrations.llm.types import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    ChatMessage,
    CompletionParams,
    LlmConfig,
)


def chat_completion(
    config: LlmConfig,
    messages: list[ChatMessage],
    *,
    temperature: float = 0.3,
    max_tokens: int = 2048,
    timeout_seconds: float = 60.0,
) -> str:
    plugin = get_plugin(config.plugin_id)
    params = CompletionParams(
        temperature=temperature,
        max_tokens=max_tokens,
        timeout_seconds=timeout_seconds,
    )
    return plugin.complete(config, messages, params)


__all__ = [
    "ChatMessage",
    "CompletionParams",
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "LlmConfig",
    "LlmError",
    "chat_completion",
    "get_plugin",
    "llm_config_from_app_settings",
    "register_plugin",
    "resolve_plugin_id",
]
