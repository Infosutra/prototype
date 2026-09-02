"""OpenAI-compatible chat/completions API (OpenRouter, OpenAI, Azure, many proxies)."""

from __future__ import annotations

import time
from typing import Any

import httpx

from app.integrations.llm.errors import LlmError
from app.integrations.llm.types import ChatMessage, CompletionParams, CompletionResult, LlmConfig, TokenUsage


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
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LlmError("Unexpected LLM response shape") from exc

        text = str(content or "").strip()
        if not text:
            raise LlmError("LLM returned an empty completion")

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


openai_compat_plugin = OpenAiCompatPlugin()
