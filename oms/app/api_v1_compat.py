"""Add typed ``/api/v1`` aliases for legacy HTTP API routes.

The platform accumulated a broad unversioned API before ``/api/v1`` became the
public contract.  Re-declaring every endpoint by hand creates two implementations
that can drift.  This module instead clones FastAPI's route contract after the
application is fully assembled.  Both paths call the same endpoint with the same
validation, dependencies, response model, status code, and streaming behavior.

Explicit ``/api/v1`` routes always win.  Browser pages, authentication callbacks,
health probes, metrics, and framework documentation remain deliberately
unversioned because they are deployment surfaces rather than product APIs.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, Iterable, Iterator, List, Set, Tuple

from fastapi import FastAPI
from fastapi.routing import APIRoute


VERSION_PREFIX = "/api/v1"
EXCLUDED_EXACT_PATHS = {
    "/",
    "/api/v1",
    "/metrics",
    "/openapi.json",
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
    "/workspace",
}
EXCLUDED_PREFIXES = (
    "/api/v1/",
    "/auth/",
    "/health/",
    "/react/",
    "/ui/",
    "/workspace/",
)
_PATH_PARAMETER = re.compile(r"\{[^{}]+\}")


def route_shape(path: str) -> str:
    """Normalize parameter names so semantically identical routes collide."""
    return _PATH_PARAMETER.sub("{}", path)


def iter_assembled_api_routes(routes: Iterable[Any]) -> Iterator[Any]:
    """Yield effective APIRoutes across flattened and nested FastAPI routers.

    FastAPI 0.141 can retain included routers as private route branches while
    older supported releases flatten them into the application. Effective route
    contexts expose the fully prefixed contract and intentionally mirror the
    APIRoute fields this adapter clones.
    """
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
            continue
        effective_contexts = getattr(route, "effective_route_contexts", None)
        if not callable(effective_contexts):
            continue
        for context in effective_contexts():
            if isinstance(getattr(context, "original_route", None), APIRoute):
                yield context


def is_eligible_legacy_route(route: Any) -> bool:
    path = route.path
    if path in EXCLUDED_EXACT_PATHS:
        return False
    if any(path.startswith(prefix) for prefix in EXCLUDED_PREFIXES):
        return False
    return path.startswith("/")


def _operation_id(route: APIRoute, method: str, alias_path: str) -> str:
    digest = hashlib.sha256(f"{method} {alias_path}".encode("utf-8")).hexdigest()[:10]
    safe_name = re.sub(r"[^a-zA-Z0-9_]+", "_", route.name or "route").strip("_")
    return f"api_v1_compat_{safe_name}_{method.lower()}_{digest}"


def handler_id(route: Any) -> str:
    module = str(getattr(route.endpoint, "__module__", "unknown")).split(".")[-1]
    name = str(getattr(route.endpoint, "__name__", route.name or "handler"))
    return f"{module}.py:{name}"


def _clone_route(
    app: FastAPI,
    source: Any,
    *,
    alias_path: str,
    methods: Set[str],
) -> APIRoute:
    method_label = "_".join(sorted(methods)).lower()
    method_for_id = "_".join(sorted(methods))
    extra = dict(source.openapi_extra or {})
    extra.update({
        "x-ontologyos-compatibility-source": source.path,
        "x-ontologyos-compatibility-handler": handler_id(source),
        "x-ontologyos-version": "v1",
    })
    tags = list(source.tags or [])
    if "api-v1-compatibility" not in tags:
        tags.append("api-v1-compatibility")
    return APIRoute(
        alias_path,
        source.endpoint,
        response_model=source.response_model,
        status_code=source.status_code,
        tags=tags,
        dependencies=source.dependencies,
        summary=source.summary,
        description=source.description,
        response_description=source.response_description,
        responses=source.responses,
        deprecated=source.deprecated,
        name=f"api_v1_compat_{source.name}_{method_label}",
        methods=methods,
        operation_id=_operation_id(source, method_for_id, alias_path),
        response_model_include=source.response_model_include,
        response_model_exclude=source.response_model_exclude,
        response_model_by_alias=source.response_model_by_alias,
        response_model_exclude_unset=source.response_model_exclude_unset,
        response_model_exclude_defaults=source.response_model_exclude_defaults,
        response_model_exclude_none=source.response_model_exclude_none,
        include_in_schema=source.include_in_schema,
        response_class=source.response_class,
        dependency_overrides_provider=app,
        callbacks=source.callbacks,
        openapi_extra=extra,
        generate_unique_id_function=source.generate_unique_id_function,
        strict_content_type=source.strict_content_type,
    )


def _manifest_payload(app: FastAPI) -> Dict[str, Any]:
    rows = list(getattr(app.state, "api_v1_compatibility", []))
    return {
        "version": "v1",
        "strategy": "same-handler-typed-alias",
        "aliases": rows,
        "summary": {
            "aliases": len(rows),
            "methods": sum(len(row["methods"]) for row in rows),
            "schema_visible": sum(1 for row in rows if row["include_in_schema"]),
            "authoritative_v1_collisions": len(getattr(app.state, "api_v1_authoritative", [])),
        },
        "authoritative_v1": list(getattr(app.state, "api_v1_authoritative", [])),
        "excluded_surfaces": {
            "exact": sorted(EXCLUDED_EXACT_PATHS),
            "prefixes": list(EXCLUDED_PREFIXES),
        },
    }


def install_api_v1_compatibility(app: FastAPI) -> Dict[str, int]:
    """Install one additive typed alias for every eligible legacy route.

    Installation is idempotent.  Route shape and method collisions are skipped
    because an explicitly implemented v1 route is authoritative.
    """
    if getattr(app.state, "api_v1_compatibility_installed", False):
        return dict(getattr(app.state, "api_v1_compatibility_summary", {}))

    source_routes = list(iter_assembled_api_routes(list(app.routes)))
    occupied: Set[Tuple[str, str]] = set()
    for route in source_routes:
        for method in route.methods or set():
            occupied.add((method.upper(), route_shape(route.path)))

    aliases: List[Dict[str, Any]] = []
    authoritative: List[Dict[str, Any]] = []
    for source in source_routes:
        if not is_eligible_legacy_route(source):
            continue
        alias_path = VERSION_PREFIX + source.path
        requested_methods = {method.upper() for method in (source.methods or set())}
        available_methods = {
            method for method in requested_methods
            if (method, route_shape(alias_path)) not in occupied
        }
        blocked_methods = sorted(requested_methods - available_methods)
        if blocked_methods:
            authoritative.append({
                "source_handler": handler_id(source),
                "source_path": source.path,
                "v1_path": alias_path,
                "methods": blocked_methods,
            })
        if not available_methods:
            continue

        alias = _clone_route(
            app,
            source,
            alias_path=alias_path,
            methods=available_methods,
        )
        app.router.routes.append(alias)
        for method in available_methods:
            occupied.add((method, route_shape(alias_path)))
        aliases.append({
            "source_handler": handler_id(source),
            "source_path": source.path,
            "v1_path": alias_path,
            "methods": sorted(available_methods),
            "include_in_schema": bool(source.include_in_schema),
            "operation_id": alias.operation_id,
        })

    app.state.api_v1_compatibility = aliases
    app.state.api_v1_authoritative = authoritative
    app.state.api_v1_compatibility_installed = True
    summary = {
        "aliases": len(aliases),
        "methods": sum(len(row["methods"]) for row in aliases),
        "authoritative_v1_collisions": len(authoritative),
    }
    app.state.api_v1_compatibility_summary = summary

    app.add_api_route(
        "/api/v1/compatibility/manifest",
        lambda: _manifest_payload(app),
        methods=["GET"],
        tags=["api-v1"],
        summary="Inspect additive API v1 compatibility coverage",
        operation_id="get_api_v1_compatibility_manifest",
    )
    app.openapi_schema = None
    return summary
