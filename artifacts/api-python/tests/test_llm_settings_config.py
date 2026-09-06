"""Unit tests for LLM config helpers derived from AppSettings."""

from __future__ import annotations

from types import SimpleNamespace

from app.integrations.llm.settings import (
    llm_compile_config_from_app_settings,
    llm_config_from_app_settings,
    llm_report_planner_config_from_app_settings,
)


def _settings(**overrides: object) -> SimpleNamespace:
    base = {
        "ai_provider": "openrouter",
        "ai_api_key": "sk-test",
        "ai_base_url": "https://openrouter.ai/api/v1",
        "ai_model": "deepseek/deepseek-v4-flash-0731",
        "ai_compile_model": "",
        "ai_report_planner_model": "",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_report_planner_uses_dedicated_model_when_set() -> None:
    settings = _settings(
        ai_report_planner_model="openai/gpt-4o-mini",
        ai_compile_model="some/other-compile-model",
        ai_model="deepseek/deepseek-v4-flash-0731",
    )
    assert (
        llm_report_planner_config_from_app_settings(settings).model
        == "openai/gpt-4o-mini"
    )


def test_report_planner_falls_back_to_ai_model_not_compile_model() -> None:
    settings = _settings(
        ai_report_planner_model="",
        ai_compile_model="compile/only-model",
        ai_model="deepseek/deepseek-v4-flash-0731",
    )
    planner = llm_report_planner_config_from_app_settings(settings)
    compile_cfg = llm_compile_config_from_app_settings(settings)
    default_cfg = llm_config_from_app_settings(settings)

    assert planner.model == "deepseek/deepseek-v4-flash-0731"
    assert planner.model == default_cfg.model
    assert planner.model != compile_cfg.model
    assert compile_cfg.model == "compile/only-model"


def test_report_planner_whitespace_treated_as_unset() -> None:
    settings = _settings(
        ai_report_planner_model="   ",
        ai_compile_model="compile/only-model",
        ai_model="deepseek/deepseek-v4-flash-0731",
    )
    assert (
        llm_report_planner_config_from_app_settings(settings).model
        == "deepseek/deepseek-v4-flash-0731"
    )
