"""Tests for the LangChain-backed LLM façade."""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.integrations.llm import (
    CompletionParams,
    LlmConfig,
    LlmError,
    chat_completion_detailed,
    chat_model,
    message_text,
    to_lc_messages,
    token_usage,
)
from app.integrations.llm.client import _empty_completion_message, _extra_body


def _config(model: str = "test/model", api_key: str = "sk-test") -> LlmConfig:
    return LlmConfig(
        provider="openrouter",
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
        model=model,
        extra_headers={"X-Title": "Infosutra"},
    )


def test_to_lc_messages_maps_roles() -> None:
    messages = to_lc_messages(
        [
            {"role": "system", "content": "be brief"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
    )
    assert [type(m) for m in messages] == [SystemMessage, HumanMessage, AIMessage]
    assert messages[1].content == "hello"


def test_unknown_role_becomes_human_message() -> None:
    messages = to_lc_messages([{"role": "tool", "content": "x"}])
    assert isinstance(messages[0], HumanMessage)


def test_chat_model_requires_api_key() -> None:
    with pytest.raises(LlmError, match="API key is not configured"):
        chat_model(_config(api_key=""))


def test_chat_model_applies_settings() -> None:
    model = chat_model(
        _config(), CompletionParams(temperature=0.7, max_tokens=1234, timeout_seconds=42.0)
    )
    assert model.model_name == "test/model"
    assert model.temperature == 0.7
    assert model.max_tokens == 1234
    assert model.max_retries == 0


def test_reasoning_disabled_for_deepseek_v4() -> None:
    assert _extra_body(_config("deepseek/deepseek-v4-flash-0731")) == {
        "reasoning": {"effort": "none"}
    }
    assert _extra_body(_config("openai/gpt-4o-mini")) is None


def test_message_text_handles_string_and_block_content() -> None:
    text, reasoning = message_text(AIMessage(content="plain"))
    assert (text, reasoning) == ("plain", 0)

    blocks = AIMessage(content=[{"type": "text", "text": "a"}, {"type": "text", "text": "b"}])
    text, _ = message_text(blocks)
    assert text == "ab"


def test_message_text_reports_reasoning_length() -> None:
    message = AIMessage(content="", additional_kwargs={"reasoning_content": "12345"})
    text, reasoning = message_text(message)
    assert text == ""
    assert reasoning == 5


def test_token_usage_from_usage_metadata() -> None:
    message = AIMessage(
        content="ok",
        usage_metadata={"input_tokens": 10, "output_tokens": 4, "total_tokens": 14},
    )
    usage, raw = token_usage(message)
    assert (usage.prompt_tokens, usage.completion_tokens, usage.total_tokens) == (10, 4, 14)
    assert raw["input_tokens"] == 10


def test_token_usage_defaults_to_zero() -> None:
    usage, raw = token_usage(AIMessage(content="ok"))
    assert usage.total_tokens == 0
    assert raw == {}


def test_completion_result_carries_telemetry(monkeypatch: pytest.MonkeyPatch) -> None:
    reply = AIMessage(
        content="the answer",
        response_metadata={"model_name": "resolved/model", "finish_reason": "stop"},
        usage_metadata={"input_tokens": 7, "output_tokens": 3, "total_tokens": 10},
        id="run-1",
    )

    class _Model:
        def invoke(self, _messages):
            return reply

    monkeypatch.setattr("app.integrations.llm.client.chat_model", lambda *a, **k: _Model())
    result = chat_completion_detailed(_config(), [{"role": "user", "content": "q"}])
    assert result.text == "the answer"
    assert result.model == "resolved/model"
    assert result.provider == "openrouter"
    assert result.usage.prompt_tokens == 7
    assert result.request_id == "run-1"
    assert result.latency_ms >= 0


def test_empty_completion_raises_actionable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Model:
        def invoke(self, _messages):
            return AIMessage(content="", response_metadata={"finish_reason": "length"})

    monkeypatch.setattr("app.integrations.llm.client.chat_model", lambda *a, **k: _Model())
    with pytest.raises(LlmError, match="max_tokens"):
        chat_completion_detailed(_config(), [{"role": "user", "content": "q"}], max_tokens=64)


def test_provider_failure_becomes_llm_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Model:
        def invoke(self, _messages):
            raise RuntimeError("connection reset")

    monkeypatch.setattr("app.integrations.llm.client.chat_model", lambda *a, **k: _Model())
    with pytest.raises(LlmError, match="connection reset"):
        chat_completion_detailed(_config(), [{"role": "user", "content": "q"}])


def test_empty_completion_message_prefers_reasoning_explanation() -> None:
    assert "Thinking likely consumed" in _empty_completion_message(
        finish_reason="stop", reasoning_chars=500, max_tokens=2048
    )
    assert "empty completion" in _empty_completion_message(
        finish_reason="stop", reasoning_chars=0, max_tokens=2048
    )
