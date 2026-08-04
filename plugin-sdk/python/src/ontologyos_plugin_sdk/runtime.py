"""Runtime contracts shared by connector, transform, widget, package, and model plugins."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, Mapping, Sequence, TypedDict


SDK_API_VERSION = 1


class PluginRequest(TypedDict):
    operation: str
    input: Dict[str, Any]


Handler = Callable[[Dict[str, Any]], Dict[str, Any]]


def _object_rows(records: Iterable[Mapping[str, Any]]) -> list[Dict[str, Any]]:
    rows = [dict(record) for record in records]
    if any(not all(isinstance(key, str) for key in row) for row in rows):
        raise TypeError("Plugin record keys must be strings")
    return rows


def dispatch(handlers: Mapping[str, Handler], request: PluginRequest) -> Dict[str, Any]:
    """Dispatch one declared operation and require an object result."""
    operation = str(request.get("operation") or "")
    if operation not in handlers:
        raise ValueError(f"Unsupported operation: {operation}")
    input_value = request.get("input") or {}
    if not isinstance(input_value, dict):
        raise TypeError("Plugin input must be an object")
    output = handlers[operation](input_value)
    if not isinstance(output, dict):
        raise TypeError("Plugin operation must return an object")
    return output


@dataclass(frozen=True)
class ConnectorResult:
    records: Sequence[Mapping[str, Any]]
    next_cursor: str | None = None
    watermark: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_output(self) -> Dict[str, Any]:
        return {
            "records": _object_rows(self.records),
            "next_cursor": self.next_cursor,
            "watermark": self.watermark,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class TransformResult:
    records: Sequence[Mapping[str, Any]]
    schema: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    warnings: Sequence[str] = field(default_factory=tuple)
    metrics: Mapping[str, int | float] = field(default_factory=dict)

    def to_output(self) -> Dict[str, Any]:
        return {
            "records": _object_rows(self.records),
            "schema": _object_rows(self.schema),
            "warnings": [str(value) for value in self.warnings],
            "metrics": dict(self.metrics),
        }


@dataclass(frozen=True)
class WidgetResult:
    widget_type: str
    title: str
    configuration_schema: Mapping[str, Any]
    data_contract: Mapping[str, Any]

    def to_output(self) -> Dict[str, Any]:
        return {
            "widget_type": self.widget_type,
            "title": self.title,
            "configuration_schema": dict(self.configuration_schema),
            "data_contract": dict(self.data_contract),
        }


@dataclass(frozen=True)
class OntologyPackageResult:
    package_id: str
    version: str
    resources: Sequence[Mapping[str, Any]]
    dependencies: Sequence[Mapping[str, Any]] = field(default_factory=tuple)

    def to_output(self) -> Dict[str, Any]:
        return {
            "package_id": self.package_id,
            "version": self.version,
            "resources": _object_rows(self.resources),
            "dependencies": _object_rows(self.dependencies),
        }


@dataclass(frozen=True)
class ModelInferenceResult:
    predictions: Sequence[Mapping[str, Any]]
    model_version: str
    usage: Mapping[str, int | float] = field(default_factory=dict)
    citations: Sequence[Mapping[str, Any]] = field(default_factory=tuple)

    def to_output(self) -> Dict[str, Any]:
        return {
            "predictions": _object_rows(self.predictions),
            "model_version": self.model_version,
            "usage": dict(self.usage),
            "citations": _object_rows(self.citations),
        }
