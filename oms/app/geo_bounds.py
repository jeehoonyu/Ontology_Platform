"""Derive an object's geographic extent from its properties.

Kept apart from both `models` and `runtime` so the model can maintain the
columns without importing the runtime, which imports the model. The geometry
functions themselves live in `runtime`; this defers that import to call time.

There is exactly one rule and everything depends on it: **the bounds a query
filters on must be the bounds the Python pass would compute for the same row.**
`spatial_query_objects` uses these columns as a plain conjunction and treats a
NULL as "no geometry, cannot match" -- so a row whose bounds are stale or
missing is a row silently absent from a map. That is why this is derived in one
place, on every write, rather than at each of the twenty-eight sites that assign
to `properties`.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

# [west, south, east, north], matching `runtime.geometry_bbox`.
Bounds = Tuple[float, float, float, float]


def bounds_of(properties: Optional[Dict[str, Any]]) -> Optional[Bounds]:
    """The bounding box of whatever geometry these properties carry.

    Returns None when there is none, which is the same condition under which
    `spatial_query_objects` skips a row.
    """
    if not isinstance(properties, dict) or not properties:
        return None

    from . import runtime  # deferred: runtime imports models, models imports this

    geometry = runtime.extract_geometry(properties)
    if not geometry:
        return None
    box = runtime.geometry_bbox(geometry)
    if not box or len(box) != 4:
        return None
    try:
        west, south, east, north = (float(value) for value in box)
    except (TypeError, ValueError):
        return None
    # A NaN would compare false against every bound and quietly drop the row,
    # which is the failure this module exists to prevent. Treat it as no
    # geometry so the row is at least excluded honestly.
    if any(value != value for value in (west, south, east, north)):
        return None
    return west, south, east, north
