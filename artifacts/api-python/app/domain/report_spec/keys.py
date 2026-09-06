"""Stable keys identifying one resolved data source payload within an execution."""

from __future__ import annotations

from typing import Any

from app.domain.report_spec.spec import DataBound, NarrativeComponent


def data_key(data_source: str, params: dict[str, Any] | None = None) -> str:
    """Key for a (source, params) pair so two components sharing them share one fetch."""
    if not params:
        return data_source
    pairs = "&".join(f"{name}={params[name]}" for name in sorted(params))
    return f"{data_source}?{pairs}"


def component_data_key(component: Any) -> str | None:
    if isinstance(component, NarrativeComponent):
        return None
    if isinstance(component, DataBound):
        return data_key(component.data_source, component.params)
    return None


def required_data_keys(spec: Any) -> list[tuple[str, str, dict[str, Any]]]:
    """Return unique (key, data_source, params) triples the specification needs."""
    seen: set[str] = set()
    out: list[tuple[str, str, dict[str, Any]]] = []
    for _section, component in spec.iter_components():
        if isinstance(component, NarrativeComponent):
            for source_id in component.data_sources:
                key = data_key(source_id, None)
                if key not in seen:
                    seen.add(key)
                    out.append((key, source_id, {}))
            continue
        if isinstance(component, DataBound):
            key = data_key(component.data_source, component.params)
            if key not in seen:
                seen.add(key)
                out.append((key, component.data_source, dict(component.params or {})))
    return out
