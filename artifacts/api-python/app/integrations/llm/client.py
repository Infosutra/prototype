"""LangChain-backed chat model access.

All LLM traffic goes through `ChatOpenAI` against an OpenAI-compatible endpoint
(OpenRouter by default), configured from install settings. The `CompletionResult` /
`TokenUsage` shapes are preserved so existing auditing and SSE streaming keep working.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from app.integrations.llm.errors import LlmError
from app.integrations.llm.types import (
    ChatMessage,
    CompletionParams,
    CompletionResult,
    LlmConfig,
    StreamDone,
    TokenUsage,
)


def _model_prefers_no_reasoning(model: str) -> bool:
    """DeepSeek V4 (and similar) default to thinking that can exhaust max_tokens."""
    mid = (model or "").strip().lower()
    return "deepseek-v4" in mid or "deepseek-reasoner" in mid


def _extra_body(config: LlmConfig) -> dict[str, Any] | None:
    """Provider-specific request shaping for reliable structured outputs.

    Reasoning tokens share the max_tokens budget with content, so models that think
    by default can return empty content. Turning thinking off keeps JSON replies whole.
    """
    if _model_prefers_no_reasoning(config.model):
        return {"reasoning": {"effort": "none"}}
    return None


def _empty_completion_message(
    *, finish_reason: str | None, reasoning_chars: int, max_tokens: int
) -> str:
    if reasoning_chars > 0:
        return (
            "LLM returned empty content after reasoning "
            f"({reasoning_chars} chars, finish_reason={finish_reason or 'unknown'}). "
            "Thinking likely consumed the token budget — disable reasoning or raise max tokens."
        )
    if finish_reason == "length":
        return (
            f"LLM hit max_tokens ({max_tokens}) before producing content. "
            "Raise AI max tokens in Settings."
        )
    return "LLM returned an empty completion"


_ROLE_TYPES = {
    "system": SystemMessage,
    "user": HumanMessage,
    "human": HumanMessage,
    "assistant": AIMessage,
    "ai": AIMessage,
}


def to_lc_messages(messages: list[ChatMessage]) -> list[BaseMessage]:
    out: list[BaseMessage] = []
    for message in messages:
        role = str(message.get("role") or "user").strip().lower()
        message_type = _ROLE_TYPES.get(role, HumanMessage)
        out.append(message_type(content=str(message.get("content") or "")))
    return out


def chat_model(
    config: LlmConfig,
    params: CompletionParams | None = None,
    *,
    streaming: bool = False,
):
    """Build a configured `ChatOpenAI` for this provider config."""
    from langchain_openai import ChatOpenAI

    if not (config.api_key or "").strip():
        raise LlmError("LLM API key is not configured")
    params = params or CompletionParams()

    kwargs: dict[str, Any] = {
        "model": config.model,
        "api_key": config.api_key.strip(),
        "base_url": config.base_url.rstrip("/"),
        "temperature": params.temperature,
        "max_tokens": params.max_tokens,
        "timeout": params.timeout_seconds,
        # Retries are handled by the calling flow (which also records attempts).
        "max_retries": 0,
    }
    if config.extra_headers:
        kwargs["default_headers"] = dict(config.extra_headers)
    extra = _extra_body(config)
    if extra:
        kwargs["extra_body"] = extra
    if streaming:
        kwargs["stream_usage"] = True
    try:
        return ChatOpenAI(**kwargs)
    except Exception as exc:  # noqa: BLE001 — surface configuration problems as LlmError
        raise LlmError(f"Could not build chat model: {exc}") from exc


def chat_model_from_app_settings(settings, *, purpose: str = "default", streaming: bool = False):
    """Chat model for install settings. `purpose` selects the configured model."""
    from app.integrations.llm.settings import (
        llm_compile_config_from_app_settings,
        llm_config_from_app_settings,
    )

    config = (
        llm_compile_config_from_app_settings(settings)
        if purpose == "compile"
        else llm_config_from_app_settings(settings)
    )
    params = CompletionParams(
        temperature=float(getattr(settings, "ai_temperature", None) or 0.3),
        max_tokens=int(getattr(settings, "ai_max_tokens", None) or 2048),
        timeout_seconds=float(getattr(settings, "ai_timeout_seconds", None) or 60.0),
    )
    return chat_model(config, params, streaming=streaming)


def message_text(message: Any) -> tuple[str, int]:
    """Extract text plus the size of any reasoning content from a LangChain message."""
    content = getattr(message, "content", None)
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
        text = "".join(parts)
    else:
        text = ""
    extra = getattr(message, "additional_kwargs", None) or {}
    reasoning = extra.get("reasoning_content") or extra.get("reasoning")
    return text.strip(), len(str(reasoning or ""))


def token_usage(message: Any) -> tuple[TokenUsage, dict[str, Any]]:
    raw = getattr(message, "usage_metadata", None) or {}
    prompt_tokens = int(raw.get("input_tokens") or 0)
    completion_tokens = int(raw.get("output_tokens") or 0)
    total = int(raw.get("total_tokens") or prompt_tokens + completion_tokens)
    return (
        TokenUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total,
        ),
        dict(raw),
    )


def _result_from_message(
    message: Any, config: LlmConfig, *, latency_ms: float, max_tokens: int
) -> CompletionResult:
    text, reasoning_chars = message_text(message)
    metadata = getattr(message, "response_metadata", None) or {}
    if not text:
        raise LlmError(
            _empty_completion_message(
                finish_reason=str(metadata.get("finish_reason") or "") or None,
                reasoning_chars=reasoning_chars,
                max_tokens=max_tokens,
            )
        )
    usage, raw_usage = token_usage(message)
    return CompletionResult(
        text=text,
        model=str(metadata.get("model_name") or config.model),
        provider=config.provider,
        latency_ms=latency_ms,
        usage=usage,
        request_id=getattr(message, "id", None),
        raw_usage=raw_usage,
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
    params = CompletionParams(
        temperature=temperature, max_tokens=max_tokens, timeout_seconds=timeout_seconds
    )
    model = chat_model(config, params)
    started = time.perf_counter()
    try:
        message = model.invoke(to_lc_messages(messages))
    except LlmError:
        raise
    except Exception as exc:  # noqa: BLE001 — provider/transport failures
        raise LlmError(f"LLM request failed: {exc}") from exc
    latency_ms = (time.perf_counter() - started) * 1000.0
    return _result_from_message(message, config, latency_ms=latency_ms, max_tokens=max_tokens)


def chat_completion_stream(
    config: LlmConfig,
    messages: list[ChatMessage],
    *,
    temperature: float = 0.3,
    max_tokens: int = 2048,
    timeout_seconds: float = 60.0,
) -> Iterator[str | StreamDone]:
    """Yield text deltas, then StreamDone with the full CompletionResult."""
    params = CompletionParams(
        temperature=temperature, max_tokens=max_tokens, timeout_seconds=timeout_seconds
    )
    model = chat_model(config, params, streaming=True)
    started = time.perf_counter()
    accumulated: Any = None
    parts: list[str] = []
    try:
        for chunk in model.stream(to_lc_messages(messages)):
            accumulated = chunk if accumulated is None else accumulated + chunk
            piece, _ = message_text(chunk)
            if piece:
                parts.append(piece)
                yield piece
    except LlmError:
        raise
    except Exception as exc:  # noqa: BLE001 — provider/transport failures
        raise LlmError(f"LLM request failed: {exc}") from exc

    latency_ms = (time.perf_counter() - started) * 1000.0
    if accumulated is None:
        raise LlmError("LLM returned an empty completion")
    result = _result_from_message(
        accumulated, config, latency_ms=latency_ms, max_tokens=max_tokens
    )
    if result.text != "".join(parts).strip():
        result = CompletionResult(
            text="".join(parts).strip() or result.text,
            model=result.model,
            provider=result.provider,
            latency_ms=result.latency_ms,
            usage=result.usage,
            request_id=result.request_id,
            raw_usage=result.raw_usage,
        )
    yield StreamDone(result)
