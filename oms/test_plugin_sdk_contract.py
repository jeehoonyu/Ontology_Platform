"""Verify the dependency-free SDK contracts used inside plugin sandboxes."""
from __future__ import annotations

import sys
from pathlib import Path


root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "plugin-sdk" / "python" / "src"))

from ontologyos_plugin_sdk import (  # noqa: E402
    SDK_API_VERSION,
    ConnectorResult,
    ModelInferenceResult,
    OntologyPackageResult,
    TransformResult,
    WidgetResult,
    dispatch,
)


assert SDK_API_VERSION == 1
assert ConnectorResult(records=[{"id": "a"}], next_cursor="2").to_output()["records"] == [{"id": "a"}]
assert TransformResult(records=[{"value": 2}], metrics={"rows": 1}).to_output()["metrics"]["rows"] == 1
assert WidgetResult("metric", "Risk", {"type": "object"}, {"type": "number"}).to_output()["widget_type"] == "metric"
assert OntologyPackageResult("asset-reliability", "1.0.0", [{"kind": "object_type"}]).to_output()["version"] == "1.0.0"
assert ModelInferenceResult([{"score": 0.8}], "model-1", citations=[{"id": "evidence-1"}]).to_output()["citations"] == [{"id": "evidence-1"}]
assert dispatch({"double": lambda value: {"value": value["value"] * 2}}, {"operation": "double", "input": {"value": 4}}) == {"value": 8}

try:
    dispatch({}, {"operation": "missing", "input": {}})
    raise AssertionError("Unknown operations must be rejected")
except ValueError:
    pass

try:
    ConnectorResult(records=[{1: "invalid"}]).to_output()  # type: ignore[dict-item]
    raise AssertionError("Non-string record keys must be rejected")
except TypeError:
    pass

print("Plugin SDK contracts verified for connector, transform, widget, ontology package, and model provider results.")
