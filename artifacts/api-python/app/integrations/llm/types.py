"""Shared types for LLM provider plugins."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


ChatMessage = dict[str, str]

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"


@dataclass(frozen=True)
class LlmConfig:
    """Resolved provider configuration for a single completion request."""

    provider: str
    plugin_id: str
    api_key: str
    base_url: str
    model: str
    extra_headers: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CompletionParams:
    temperature: float = 0.3
    max_tokens: int = 2048
    timeout_seconds: float = 60.0
