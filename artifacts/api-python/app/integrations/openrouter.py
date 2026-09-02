"""Backward-compatible shim — prefer app.integrations.llm."""

from __future__ import annotations

import warnings

from app.integrations.llm import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    LlmError,
    chat_completion as _chat_completion,
)
from app.integrations.llm.types import LlmConfig

OpenRouterError = LlmError


def chat_completion(
    *,
    api_key: str,
    messages: list[dict[str, str]],
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE_URL,
    temperature: float = 0.3,
    max_tokens: int = 2048,
    timeout_seconds: float = 60.0,
) -> str:
    warnings.warn(
        "app.integrations.openrouter.chat_completion is deprecated; use app.integrations.llm",
        DeprecationWarning,
        stacklevel=2,
    )
    config = LlmConfig(
        provider="openrouter",
        plugin_id="openai_compat",
        api_key=api_key,
        base_url=base_url,
        model=model,
        extra_headers={
            "HTTP-Referer": "https://infosutra.local",
            "X-Title": "Infosutra DQA Daily",
        },
    )
    return _chat_completion(
        config,
        messages,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout_seconds=timeout_seconds,
    )
