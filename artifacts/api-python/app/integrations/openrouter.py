"""OpenRouter chat completions client (OpenAI-compatible API)."""

from __future__ import annotations

from typing import Any

import httpx


class OpenRouterError(Exception):
    pass


DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"


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
    if not api_key.strip():
        raise OpenRouterError("OpenRouter API key is not configured")

    url = base_url.rstrip("/") + "/chat/completions"
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    headers = {
        "Authorization": f"Bearer {api_key.strip()}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://infosutra.local",
        "X-Title": "Infosutra DQA Daily",
    }
    try:
        response = httpx.post(url, json=payload, headers=headers, timeout=timeout_seconds)
    except httpx.HTTPError as exc:
        raise OpenRouterError(f"OpenRouter request failed: {exc}") from exc

    if response.status_code >= 400:
        detail = response.text[:500]
        raise OpenRouterError(f"OpenRouter HTTP {response.status_code}: {detail}")

    data = response.json()
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise OpenRouterError("Unexpected OpenRouter response shape") from exc
    text = str(content or "").strip()
    if not text:
        raise OpenRouterError("OpenRouter returned an empty completion")
    return text
