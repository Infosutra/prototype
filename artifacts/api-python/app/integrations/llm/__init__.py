"""LLM chat completions via pluggable providers."""

from __future__ import annotations

from collections.abc import Iterator

from app.integrations.llm.errors import LlmError
from app.integrations.llm.registry import get_plugin, register_plugin, resolve_plugin_id
from app.integrations.llm.settings import (
    llm_compile_config_from_app_settings,
    llm_config_from_app_settings,
)
from app.integrations.llm.types import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    ChatMessage,
    CompletionParams,
    CompletionResult,
    LlmConfig,
    StreamDone,
    TokenUsage,
)


def chat_completion(
    config: LlmConfig,
    messages: list[ChatMessage],
    *,
    temperature: float = 0.3,
    max_tokens: int = 2048,
    timeout_seconds: float = 60.0,
) -> str:
    return chat_completion_detailed(
        config,
        messages,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout_seconds=timeout_seconds,
    ).text


def chat_completion_detailed(
    config: LlmConfig,
    messages: list[ChatMessage],
    *,
    temperature: float = 0.3,
    max_tokens: int = 2048,
    timeout_seconds: float = 60.0,
) -> CompletionResult:
    plugin = get_plugin(config.plugin_id)
    params = CompletionParams(
        temperature=temperature,
        max_tokens=max_tokens,
        timeout_seconds=timeout_seconds,
    )
    if hasattr(plugin, "complete_detailed"):
        return plugin.complete_detailed(config, messages, params)
    started = __import__("time").perf_counter()
    text = plugin.complete(config, messages, params)
    latency_ms = (__import__("time").perf_counter() - started) * 1000.0
    return CompletionResult(
        text=text,
        model=config.model,
        provider=config.provider,
        latency_ms=latency_ms,
    )


def chat_completion_stream(
    config: LlmConfig,
    messages: list[ChatMessage],
    *,
    temperature: float = 0.3,
    max_tokens: int = 2048,
    timeout_seconds: float = 60.0,
) -> Iterator[str | StreamDone]:
    """Yield text deltas, then StreamDone with the full CompletionResult."""
    plugin = get_plugin(config.plugin_id)
    params = CompletionParams(
        temperature=temperature,
        max_tokens=max_tokens,
        timeout_seconds=timeout_seconds,
    )
    if hasattr(plugin, "stream_complete"):
        yield from plugin.stream_complete(config, messages, params)
        return
    # Fallback: non-streaming providers emit a single chunk.
    result = chat_completion_detailed(
        config,
        messages,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout_seconds=timeout_seconds,
    )
    if result.text:
        yield result.text
    yield StreamDone(result)


__all__ = [
    "ChatMessage",
    "CompletionParams",
    "CompletionResult",
    "StreamDone",
    "TokenUsage",
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "LlmConfig",
    "LlmError",
    "chat_completion",
    "chat_completion_detailed",
    "chat_completion_stream",
    "get_plugin",
    "llm_config_from_app_settings",
    "llm_compile_config_from_app_settings",
    "register_plugin",
    "resolve_plugin_id",
]
