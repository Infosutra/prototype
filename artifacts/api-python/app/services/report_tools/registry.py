"""Registry of semantic report data sources.

The planner may only reference tools registered here, and the executor may only
call tools registered here. This is the single choke point between generated
report specifications and the database.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from app.domain.report_spec.catalog import DataSourceDescriptor
from app.services.report_tools.context import ReportDataContext

logger = logging.getLogger(__name__)

ToolFn = Callable[[ReportDataContext, dict[str, Any]], Any]


class ReportToolError(Exception):
    """A data source could not produce data for this execution."""


@dataclass(frozen=True)
class ReportTool:
    descriptor: DataSourceDescriptor
    fn: ToolFn

    @property
    def id(self) -> str:
        return self.descriptor.id


_TOOLS: dict[str, ReportTool] = {}


def register(descriptor: DataSourceDescriptor) -> Callable[[ToolFn], ToolFn]:
    def decorator(fn: ToolFn) -> ToolFn:
        if descriptor.id in _TOOLS:
            raise ValueError(f"Duplicate report tool id: {descriptor.id}")
        _TOOLS[descriptor.id] = ReportTool(descriptor=descriptor, fn=fn)
        return fn

    return decorator


def get_tool(tool_id: str) -> ReportTool | None:
    _ensure_loaded()
    return _TOOLS.get(tool_id)


def all_tools() -> list[ReportTool]:
    _ensure_loaded()
    return [_TOOLS[key] for key in sorted(_TOOLS)]


def all_descriptors() -> list[DataSourceDescriptor]:
    return [tool.descriptor for tool in all_tools()]


def descriptors_by_id() -> dict[str, DataSourceDescriptor]:
    return {tool.id: tool.descriptor for tool in all_tools()}


def _apply_defaults(
    descriptor: DataSourceDescriptor, params: dict[str, Any] | None
) -> dict[str, Any]:
    resolved = dict(params or {})
    for param in descriptor.params:
        if param.name not in resolved and param.default is not None:
            resolved[param.name] = param.default
    return resolved


def call_tool(
    context: ReportDataContext, tool_id: str, params: dict[str, Any] | None = None
) -> Any:
    """Execute one registered tool. Raises ReportToolError for unknown ids."""
    tool = get_tool(tool_id)
    if tool is None:
        raise ReportToolError(f"Unknown data source '{tool_id}'")
    resolved = _apply_defaults(tool.descriptor, params)
    return tool.fn(context, resolved)


_loaded = False


def _ensure_loaded() -> None:
    """Import the tool modules once so their registrations run."""
    global _loaded
    if _loaded:
        return
    _loaded = True
    from app.services.report_tools import sources  # noqa: F401
