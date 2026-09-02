"""Register and resolve LLM provider plugins."""

from __future__ import annotations

from app.integrations.llm.errors import LlmError
from app.integrations.llm.plugins.base import LlmProviderPlugin
from app.integrations.llm.plugins.openai_compat import openai_compat_plugin

_PLUGINS: dict[str, LlmProviderPlugin] = {
    openai_compat_plugin.plugin_id: openai_compat_plugin,
}

# Settings `ai_provider` value → plugin id. Extend when adding plugins.
PROVIDER_PLUGIN_MAP: dict[str, str] = {
    "openrouter": "openai_compat",
    "openai": "openai_compat",
    "azure": "openai_compat",
    "azure_openai": "openai_compat",
    "custom": "openai_compat",
}

DEFAULT_PLUGIN_ID = "openai_compat"


def register_plugin(plugin: LlmProviderPlugin) -> None:
    _PLUGINS[plugin.plugin_id] = plugin


def resolve_plugin_id(provider: str) -> str:
    normalized = (provider or "openrouter").strip().lower()
    return PROVIDER_PLUGIN_MAP.get(normalized, DEFAULT_PLUGIN_ID)


def get_plugin(plugin_id: str) -> LlmProviderPlugin:
    plugin = _PLUGINS.get(plugin_id)
    if plugin is None:
        raise LlmError(f"Unknown LLM plugin: {plugin_id}")
    return plugin
