"""OpenAI-compatible chat/completions API (OpenRouter, OpenAI, Azure, many proxies)."""

from __future__ import annotations

from typing import Any

import httpx

from app.integrations.llm.errors import LlmError
from app.integrations.llm.types import ChatMessage, CompletionParams, LlmConfig


class OpenAiCompatPlugin:
    plugin_id = "openai_compat"

    def complete(
        self,
        config: LlmConfig,
        messages: list[ChatMessage],
        params: CompletionParams,
    ) -> str:
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
        try:
            response = httpx.post(
                url,
                json=payload,
                headers=headers,
                timeout=params.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise LlmError(f"LLM request failed: {exc}") from exc

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
        return text


openai_compat_plugin = OpenAiCompatPlugin()
