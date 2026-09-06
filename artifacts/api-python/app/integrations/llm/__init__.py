"""LLM access for the application, backed by LangChain."""

from __future__ import annotations

from app.integrations.llm.client import (
    chat_completion,
    chat_completion_detailed,
    chat_completion_stream,
    chat_model,
    chat_model_from_app_settings,
    message_text,
    to_lc_messages,
    token_usage,
)
from app.integrations.llm.errors import LlmError
from app.integrations.llm.settings import (
    llm_compile_config_from_app_settings,
    llm_config_from_app_settings,
    llm_report_planner_config_from_app_settings,
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

__all__ = [
    "ChatMessage",
    "CompletionParams",
    "CompletionResult",
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "LlmConfig",
    "LlmError",
    "StreamDone",
    "TokenUsage",
    "chat_completion",
    "chat_completion_detailed",
    "chat_completion_stream",
    "chat_model",
    "chat_model_from_app_settings",
    "llm_compile_config_from_app_settings",
    "llm_config_from_app_settings",
    "llm_report_planner_config_from_app_settings",
    "message_text",
    "to_lc_messages",
    "token_usage",
]
