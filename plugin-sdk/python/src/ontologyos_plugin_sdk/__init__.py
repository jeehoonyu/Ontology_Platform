"""Typed, dependency-free helpers for OntologyOS sandbox extensions."""

from .runtime import (
    SDK_API_VERSION,
    ConnectorResult,
    ModelInferenceResult,
    OntologyPackageResult,
    PluginRequest,
    TransformResult,
    WidgetResult,
    dispatch,
)

__all__ = [
    "SDK_API_VERSION",
    "ConnectorResult",
    "ModelInferenceResult",
    "OntologyPackageResult",
    "PluginRequest",
    "TransformResult",
    "WidgetResult",
    "dispatch",
]
