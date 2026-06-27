"""
GIS geometry operations & network routing (deep-fidelity pass 7, Map/GIS).

Deepens the Map/GIS tool beyond storage/feature-export with the documented spatial
operations: distance, centroid, area, bounding box, buffer, and shortest-path
**routing** over an ontology object+link network with haversine edge weights.
Additive; deterministic; reuses runtime geo helpers.
"""
import heapq
import math
import time
import uuid
from typing import Optional, List, Any, Dict, Tuple

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import String, Integer, JSON
from sqlalchemy.orm import Mapped, mapped_column, Session
from pydantic import BaseModel, ConfigDict, Field

from .database import Base, get_db
from . import models, runtime

router = APIRouter(tags=["gis_ops"])


# ---------------------------------------------------------------------------
# SQLAlchemy models (prefix: Gis / gis_)
# ---------------------------------------------------------------------------
class GisDisplay(Base):
    """Per-layer cartographic display: symbol + value-driven style rules."""
    __tablename__ = "gis_displays"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    layer_id: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str] = mapped_column(String)
    symbol: Mapped[str] = mapped_column(String, default="circle")
    style_rules: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[int] = mapped_column(Integer)


def _positions(geometry: Any) -> List[Tuple[float, float]]:
    return list(runtime._iter_positions(geometry.get("coordinates") if isinstance(geometry, dict) else geometry))


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class DistanceRequest(BaseModel):
    from_: List[float] = Field(alias="from")
    to: List[float]
    model_config = {"populate_by_name": True}


class GeometryRequest(BaseModel):
    geometry: Dict[str, Any]


class BufferRequest(BaseModel):
    point: List[float]      # [lon, lat]
    radius_m: float
    segments: int = 16


class RouteRequest(BaseModel):
    object_type_id: str
    start_object_id: str
    end_object_id: str
    link_type_id: Optional[str] = None
    geometry_field: str = "geometry"


# --- Per-layer displays ----------------------------------------------------
class GisDisplayCreate(BaseModel):
    id: Optional[str] = None
    layer_id: str
    name: str
    symbol: str = "circle"
    style_rules: Dict[str, Any] = Field(default_factory=dict)


class GisDisplayRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    layer_id: str
    name: str
    symbol: str
    style_rules: Dict[str, Any]
    created_at: int


# --- Value-based styling ---------------------------------------------------
class StyleStop(BaseModel):
    value: Optional[Any] = None          # exact-match value (categorical)
    max: Optional[float] = None          # graduated upper bound (<=)
    color: Optional[str] = None
    size: Optional[float] = None


class StyleEvaluateRequest(BaseModel):
    field: str
    stops: List[StyleStop]
    features: Optional[List[Dict[str, Any]]] = None
    object_type_id: Optional[str] = None
    geometry_field: str = "geometry"
    default_color: Optional[str] = None
    default_size: Optional[float] = None


# --- Temporal spatial query ------------------------------------------------
class TemporalSpatialQueryRequest(BaseModel):
    object_type_id: str
    geometry_field: str = "geometry"
    time_field: str
    start_ms: int
    end_ms: int
    near: Optional[Dict[str, Any]] = None
    radius_meters: Optional[float] = None
    bbox: Optional[List[float]] = None
    polygon: Optional[Dict[str, Any]] = None
    filters: Optional[Dict[str, Any]] = None
    limit: int = 100


# ---------------------------------------------------------------------------
# Geometry operations
# ---------------------------------------------------------------------------
@router.post("/gis/ops/distance")
def distance(body: DistanceRequest):
    d = runtime.haversine_distance_meters((body.from_[0], body.from_[1]), (body.to[0], body.to[1]))
    return {"meters": round(d, 3), "kilometers": round(d / 1000, 4)}


@router.post("/gis/ops/centroid")
def centroid(body: GeometryRequest):
    pts = _positions(body.geometry)
    if not pts:
        raise HTTPException(status_code=422, detail="geometry has no coordinates")
    lon = sum(p[0] for p in pts) / len(pts)
    lat = sum(p[1] for p in pts) / len(pts)
    return {"centroid": [round(lon, 6), round(lat, 6)], "vertices": len(pts)}


@router.post("/gis/ops/bbox")
def bbox(body: GeometryRequest):
    pts = _positions(body.geometry)
    if not pts:
        raise HTTPException(status_code=422, detail="geometry has no coordinates")
    lons = [p[0] for p in pts]
    lats = [p[1] for p in pts]
    return {"bbox": [min(lons), min(lats), max(lons), max(lats)]}


@router.post("/gis/ops/area")
def area(body: GeometryRequest):
    """Approximate polygon area in m^2 via a local equirectangular projection + shoelace."""
    geom = body.geometry
    if geom.get("type") != "Polygon":
        raise HTTPException(status_code=422, detail="area requires a Polygon geometry")
    ring = geom.get("coordinates", [[]])[0]
    if len(ring) < 4:
        raise HTTPException(status_code=422, detail="polygon ring needs >= 4 positions")
    mean_lat = math.radians(sum(p[1] for p in ring) / len(ring))
    mx = 111320.0 * math.cos(mean_lat)
    my = 110540.0
    xy = [(p[0] * mx, p[1] * my) for p in ring]
    s = 0.0
    for i in range(len(xy) - 1):
        s += xy[i][0] * xy[i + 1][1] - xy[i + 1][0] * xy[i][1]
    return {"area_m2": round(abs(s) / 2.0, 2)}


@router.post("/gis/ops/buffer")
def buffer(body: BufferRequest):
    """Approximate a circular buffer polygon around a point."""
    lon, lat = body.point[0], body.point[1]
    lat_rad = math.radians(lat)
    ring = []
    for i in range(body.segments + 1):
        theta = 2 * math.pi * i / body.segments
        dlat = (body.radius_m * math.cos(theta)) / 110540.0
        dlon = (body.radius_m * math.sin(theta)) / (111320.0 * math.cos(lat_rad) or 1e-9)
        ring.append([round(lon + dlon, 6), round(lat + dlat, 6)])
    return {"type": "Polygon", "coordinates": [ring]}


# ---------------------------------------------------------------------------
# Network routing (shortest path over object+link graph)
# ---------------------------------------------------------------------------
@router.post("/gis/route")
def route(body: RouteRequest, db: Session = Depends(get_db)):
    objs = {
        o.id: o for o in db.query(models.ObjectInstance)
        .filter(models.ObjectInstance.object_type_id == body.object_type_id).all()
    }
    if body.start_object_id not in objs or body.end_object_id not in objs:
        raise HTTPException(status_code=404, detail="start/end object not found in object type")

    def coord(oid: str):
        g = (objs[oid].properties or {}).get(body.geometry_field)
        if isinstance(g, dict) and g.get("type") == "Point":
            return tuple(g.get("coordinates", [None, None]))
        return None

    link_q = db.query(models.LinkInstance)
    if body.link_type_id:
        link_q = link_q.filter(models.LinkInstance.link_type_id == body.link_type_id)
    adjacency: Dict[str, List[Tuple[str, float]]] = {oid: [] for oid in objs}
    edges = 0
    for link in link_q.all():
        a, b = link.source_object_id, link.target_object_id
        if a in objs and b in objs and coord(a) and coord(b):
            w = runtime.haversine_distance_meters(coord(a), coord(b))
            adjacency[a].append((b, w))
            adjacency[b].append((a, w))  # treat links as bidirectional for routing
            edges += 1

    # Dijkstra
    dist = {oid: math.inf for oid in objs}
    prev: Dict[str, Optional[str]] = {oid: None for oid in objs}
    dist[body.start_object_id] = 0.0
    pq: List[Tuple[float, str]] = [(0.0, body.start_object_id)]
    while pq:
        d, node = heapq.heappop(pq)
        if d > dist[node]:
            continue
        if node == body.end_object_id:
            break
        for nbr, w in adjacency[node]:
            nd = d + w
            if nd < dist[nbr]:
                dist[nbr] = nd
                prev[nbr] = node
                heapq.heappush(pq, (nd, nbr))

    if dist[body.end_object_id] == math.inf:
        return {"reachable": False, "edges": edges, "path": [], "total_distance_m": None}
    path = []
    cur: Optional[str] = body.end_object_id
    while cur is not None:
        path.append(cur)
        cur = prev[cur]
    path.reverse()
    return {"reachable": True, "edges": edges, "hops": len(path) - 1,
            "path": path, "total_distance_m": round(dist[body.end_object_id], 3)}


# ---------------------------------------------------------------------------
# Per-layer DISPLAYS (symbol + style rules)
# ---------------------------------------------------------------------------
@router.post("/gis/displays", response_model=GisDisplayRead)
def create_gis_display(body: GisDisplayCreate, db: Session = Depends(get_db)):
    display_id = body.id or uuid.uuid4().hex
    if db.query(GisDisplay).filter(GisDisplay.id == display_id).first():
        raise HTTPException(status_code=400, detail="GisDisplay already exists")
    row = GisDisplay(
        id=display_id,
        layer_id=body.layer_id,
        name=body.name,
        symbol=body.symbol,
        style_rules=body.style_rules,
        created_at=int(time.time()),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/gis/displays", response_model=List[GisDisplayRead])
def list_gis_displays(
    layer_id: Optional[str] = None,
    db: Session = Depends(get_db),
):
    query = db.query(GisDisplay)
    if layer_id is not None:
        query = query.filter(GisDisplay.layer_id == layer_id)
    return query.order_by(GisDisplay.created_at).all()


@router.get("/gis/displays/{display_id}", response_model=GisDisplayRead)
def get_gis_display(display_id: str, db: Session = Depends(get_db)):
    row = db.query(GisDisplay).filter(GisDisplay.id == display_id).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"GisDisplay '{display_id}' not found")
    return row


# ---------------------------------------------------------------------------
# VALUE-BASED STYLING (resolve color/size per feature against stops)
# ---------------------------------------------------------------------------
def _resolve_style(value: Any, stops: List[StyleStop],
                   default_color: Optional[str], default_size: Optional[float]) -> Dict[str, Any]:
    """Resolve {color,size} for a property value against an ordered stop list.

    Categorical stops (with `value`) match by equality. Graduated stops (with
    `max`) match the first stop whose `max` is >= the numeric value; graduated
    stops are evaluated in ascending `max` order for a deterministic result.
    """
    resolved: Dict[str, Any] = {"color": default_color, "size": default_size}

    # Exact (categorical) match first.
    for stop in stops:
        if stop.value is not None and stop.value == value:
            return {"color": stop.color, "size": stop.size}

    # Graduated match on numeric value.
    numeric: Optional[float] = None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        numeric = float(value)
    if numeric is not None:
        graduated = sorted(
            [s for s in stops if s.max is not None],
            key=lambda s: float(s.max),
        )
        for stop in graduated:
            if numeric <= float(stop.max):
                return {"color": stop.color, "size": stop.size}

    return resolved


@router.post("/gis/style/evaluate")
def evaluate_gis_style(body: StyleEvaluateRequest, db: Session = Depends(get_db)):
    if not body.features and not body.object_type_id:
        raise HTTPException(status_code=422, detail="provide either features or object_type_id")

    features: List[Dict[str, Any]]
    if body.features is not None:
        features = body.features
    else:
        rows, _ = runtime._logic_object_rows(db, body.object_type_id, {}, limit=10000)
        features = [
            {"id": row.id, "properties": dict(row.properties or {})}
            for row in rows
        ]

    results: List[Dict[str, Any]] = []
    for index, feature in enumerate(features):
        props = feature.get("properties")
        if not isinstance(props, dict):
            props = feature  # allow a flat dict of properties
        value = props.get(body.field) if isinstance(props, dict) else None
        style = _resolve_style(value, body.stops, body.default_color, body.default_size)
        results.append({
            "id": feature.get("id", index) if isinstance(feature, dict) else index,
            "value": value,
            "color": style["color"],
            "size": style["size"],
        })

    return {
        "field": body.field,
        "count": len(results),
        "results": results,
    }


# ---------------------------------------------------------------------------
# TEMPORAL spatial query (spatial filter + time-window filter)
# ---------------------------------------------------------------------------
@router.post("/gis/spatial-query-temporal")
def spatial_query_temporal(body: TemporalSpatialQueryRequest, db: Session = Depends(get_db)):
    if body.start_ms > body.end_ms:
        raise HTTPException(status_code=422, detail="start_ms must be <= end_ms")
    try:
        spatial = runtime.spatial_query_objects(
            db,
            object_type_id=body.object_type_id,
            filters=body.filters,
            geometry_field=body.geometry_field,
            near=body.near,
            radius_meters=body.radius_meters,
            bbox=body.bbox,
            polygon=body.polygon,
            limit=body.limit,
            include_lineage=False,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    matched: List[Dict[str, Any]] = []
    for obj in spatial["objects"]:
        ts = (obj.get("properties") or {}).get(body.time_field)
        if not isinstance(ts, (int, float)) or isinstance(ts, bool):
            continue
        if body.start_ms <= ts <= body.end_ms:
            matched.append(obj)

    return {
        "object_type_id": body.object_type_id,
        "geometry_field": body.geometry_field,
        "time_field": body.time_field,
        "window": {"start_ms": body.start_ms, "end_ms": body.end_ms},
        "spatial_total": spatial["total"],
        "count": len(matched),
        "objects": matched,
    }
