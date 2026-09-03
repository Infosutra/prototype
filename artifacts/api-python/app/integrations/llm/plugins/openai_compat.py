"""OpenAI-compatible chat/completions API (OpenRouter, OpenAI, Azure, many proxies)."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from typing import Any

import httpx

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


def _apply_provider_payload_tweaks(payload: dict[str, Any], config: LlmConfig) -> None:
    """Provider-specific request shaping for reliable structured outputs."""
    # Disable thinking for structured compile JSON. Reasoning tokens share max_tokens
    # with content; DeepSeek V4 often returns empty content when the budget is spent
    # on reasoning_content alone.
    if _model_prefers_no_reasoning(config.model):
        payload["reasoning"] = {"effort": "none"}


def _empty_completion_message(
    *,
    finish_reason: str | None,
    reasoning_chars: int,
    max_tokens: int,
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


def _message_text(message: dict[str, Any]) -> tuple[str, int]:
    content = message.get("content")
    reasoning = message.get("reasoning_content") or message.get("reasoning")
    reasoning_chars = len(str(reasoning or ""))
    text = str(content or "").strip()
    return text, reasoning_chars


class OpenAiCompatPlugin:
    plugin_id = "openai_compat"

    def complete(
        self,
        config: LlmConfig,
        messages: list[ChatMessage],
        params: CompletionParams,
    ) -> str:
        return self.complete_detailed(config, messages, params).text

    def complete_detailed(
        self,
        config: LlmConfig,
        messages: list[ChatMessage],
        params: CompletionParams,
    ) -> CompletionResult:
        if not config.api_key.strip():
            raise LlmError("LLM API key is not configured")

        url = config.base_url.rstrip("/") + "/chat/completions"
        payload: dict[str, Any] = {
            "model": config.model,
            "messages": messages,
            "temperature": params.temperature,
            "max_tokens": params.max_tokens,
        }
        _apply_provider_payload_tweaks(payload, config)
        headers = {
            "Authorization": f"Bearer {config.api_key.strip()}",
            "Content-Type": "application/json",
            **config.extra_headers,
        }
        started = time.perf_counter()
        try:
            response = httpx.post(
                url,
                json=payload,
                headers=headers,
                timeout=params.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise LlmError(f"LLM request failed: {exc}") from exc
        latency_ms = (time.perf_counter() - started) * 1000.0

        if response.status_code >= 400:
            detail = response.text[:500]
            raise LlmError(f"LLM HTTP {response.status_code}: {detail}")

        data = response.json()
        try:
            choice0 = data["choices"][0]
            message = choice0.get("message") if isinstance(choice0, dict) else None
            if not isinstance(message, dict):
                raise KeyError("message")
            finish_reason = choice0.get("finish_reason") if isinstance(choice0, dict) else None
        except (KeyError, IndexError, TypeError) as exc:
            raise LlmError("Unexpected LLM response shape") from exc

        text, reasoning_chars = _message_text(message)
        if not text:
            raise LlmError(
                _empty_completion_message(
                    finish_reason=str(finish_reason) if finish_reason else None,
                    reasoning_chars=reasoning_chars,
                    max_tokens=params.max_tokens,
                )
            )

        usage_raw = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        prompt_tokens = int(usage_raw.get("prompt_tokens") or 0)
        completion_tokens = int(usage_raw.get("completion_tokens") or 0)
        total_tokens = int(usage_raw.get("total_tokens") or prompt_tokens + completion_tokens)
        request_id = response.headers.get("x-request-id") or data.get("id")

        return CompletionResult(
            text=text,
            model=str(data.get("model") or config.model),
            provider=config.provider,
            latency_ms=latency_ms,
            usage=TokenUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
            ),
            request_id=str(request_id) if request_id else None,
            raw_usage=dict(usage_raw),
        )

    def stream_complete(
        self,
        config: LlmConfig,
        messages: list[ChatMessage],
        params: CompletionParams,
    ) -> Iterator[str | StreamDone]:
        """Yield text deltas, then a final StreamDone with CompletionResult."""
        if not config.api_key.strip():
            raise LlmError("LLM API key is not configured")

        url = config.base_url.rstrip("/") + "/chat/completions"
        payload: dict[str, Any] = {
            "model": config.model,
            "messages": messages,
            "temperature": params.temperature,
            "max_tokens": params.max_tokens,
            "stream": True,
        }
        _apply_provider_payload_tweaks(payload, config)
        # Best-effort: some providers ignore unknown keys; include usage when supported.
        payload["stream_options"] = {"include_usage": True}
        headers = {
            "Authorization": f"Bearer {config.api_key.strip()}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            **config.extra_headers,
        }
        started = time.perf_counter()
        text_parts: list[str] = []
        reasoning_chars = 0
        finish_reason: str | None = None
        model_name = config.model
        request_id: str | None = None
        usage_raw: dict[str, Any] = {}

        try:
            with httpx.stream(
                "POST",
                url,
                json=payload,
                headers=headers,
                timeout=httpx.Timeout(params.timeout_seconds, connect=30.0),
            ) as response:
                if response.status_code >= 400:
                    detail = response.read().decode("utf-8", errors="replace")[:500]
                    raise LlmError(f"LLM HTTP {response.status_code}: {detail}")

                for line in response.iter_lines():
                    if not line:
                        continue
                    if line.startswith(":"):
                        continue
                    if not line.startswith("data:"):
                        continue
                    data_str = line[5:].strip()
                    if not data_str or data_str == "[DONE]":
                        if data_str == "[DONE]":
                            break
                        continue
                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(data, dict):
                        continue
                    if data.get("id") and not request_id:
                        request_id = str(data.get("id"))
                    if data.get("model"):
                        model_name = str(data.get("model"))
                    if isinstance(data.get("usage"), dict):
                        usage_raw = dict(data["usage"])
                    choices = data.get("choices")
                    if not isinstance(choices, list) or not choices:
                        continue
                    choice0 = choices[0] if isinstance(choices[0], dict) else {}
                    if choice0.get("finish_reason"):
                        finish_reason = str(choice0.get("finish_reason"))
                    delta = choice0.get("delta") if isinstance(choice0.get("delta"), dict) else {}
                    reasoning_piece = delta.get("reasoning_content") or delta.get("reasoning")
                    if reasoning_piece:
                        reasoning_chars += len(str(reasoning_piece))
                    piece = delta.get("content")
                    if piece:
                        text = str(piece)
                        text_parts.append(text)
                        yield text
        except LlmError:
            raise
        except httpx.HTTPError as exc:
            raise LlmError(f"LLM request failed: {exc}") from exc

        latency_ms = (time.perf_counter() - started) * 1000.0
        text = "".join(text_parts).strip()
        if not text:
            raise LlmError(
                _empty_completion_message(
                    finish_reason=finish_reason,
                    reasoning_chars=reasoning_chars,
                    max_tokens=params.max_tokens,
                )
            )

        prompt_tokens = int(usage_raw.get("prompt_tokens") or 0)
        completion_tokens = int(usage_raw.get("completion_tokens") or 0)
        total_tokens = int(usage_raw.get("total_tokens") or prompt_tokens + completion_tokens)

        yield StreamDone(
            CompletionResult(
                text=text,
                model=model_name,
                provider=config.provider,
                latency_ms=latency_ms,
                usage=TokenUsage(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                ),
                request_id=request_id,
                raw_usage=dict(usage_raw),
            )
        )


openai_compat_plugin = OpenAiCompatPlugin()
