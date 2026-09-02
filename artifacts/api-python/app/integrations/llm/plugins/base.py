"""LLM provider plugin protocol."""

from __future__ import annotations

from typing import Protocol

from app.integrations.llm.types import ChatMessage, CompletionParams, LlmConfig


class LlmProviderPlugin(Protocol):
    """Contract for LLM backends. Add a new module + registry entry to support another vendor."""

    plugin_id: str

    def complete(
        self,
        config: LlmConfig,
        messages: list[ChatMessage],
        params: CompletionParams,
    ) -> str: ...
