"""
Foundry VERTEX — graph exploration application (deepening module).

Faithful, deterministic implementation of the Vertex graph-exploration app:
    - graphs built from seed objects, expanded via link traversal over LinkInstance
      (mirrors runtime.search_around_objects)
    - deterministic layout positioners (grid / circular / hierarchy / cluster)
    - property filters (fading), styling, templates, events/timeline, and
      what-if scenarios (deterministic simulation, NOT a model invoke)
    - a control-panel settings store

Docs basis: vertex/{overview, graphs-explore, explore-object-relationships,
graphs-template, graphs-display-options, configure-events, timeline,
scenarios-getting-started, link-merging, vertex-settings-control-panel}.

Every ORM class and __tablename__ is prefixed with Vtx / vtx_ to avoid
collisions on the shared SQLAlchemy Base.
"""

from .database import Base, get_db
from . import models, models_action
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, Integer, JSON, Boolean, Float, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, Session
from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List, Any, Dict
import time, uuid, math, copy

# ---------------------------------------------------------------------------
# SQLAlchemy models (all prefixed Vtx / vtx_)
# ---------------------------------------------------------------------------


class VtxGraph(Base):
    """A materialized exploration graph: seed objects expanded via link traversal."""
    __tablename__ = "vtx_graphs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    display_name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    seed_object_ids: Mapped[list] = mapped_column(JSON, default=list)
    nodes: Mapped[list] = mapped_column(JSON, default=list)
    edges: Mapped[list] = mapped_column(JSON, default=list)
    layout_type: Mapped[str] = mapped_column(String, default="auto")
    styles: Mapped[dict] = mapped_column(JSON, default=dict)
    owner: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class VtxTemplate(Base):
    """A reusable graph template: parameterized seeds + canned search-arounds."""
    __tablename__ = "vtx_templates"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    display_name: Mapped[str] = mapped_column(String)
    object_params: Mapped[list] = mapped_column(JSON, default=list)   # [{name, object_type_id}]
    scalar_params: Mapped[list] = mapped_column(JSON, default=list)   # [{name, default}]
    search_arounds: Mapped[list] = mapped_column(JSON, default=list)  # [{link_type_id, direction, depth}]
    created_at: Mapped[int] = mapped_column(Integer)


class VtxScenario(Base):
    """Deterministic what-if simulation over a graph's node properties."""
    __tablename__ = "vtx_scenarios"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    graph_id: Mapped[str] = mapped_column(String, ForeignKey("vtx_graphs.id"), index=True)
    display_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    parameter_overrides: Mapped[dict] = mapped_column(JSON, default=dict)
    baseline: Mapped[dict] = mapped_column(JSON, default=dict)
    scenario_output: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[int] = mapped_column(Integer)


class VtxEventConfig(Base):
    """Event configuration: declares which object type carries time fields for the timeline."""
    __tablename__ = "vtx_event_configs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    graph_id: Mapped[str] = mapped_column(String, ForeignKey("vtx_graphs.id"), index=True)
    event_object_type_id: Mapped[str] = mapped_column(String)
    start_time_field: Mapped[str] = mapped_column(String)
    end_time_field: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    intent: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer)


class VtxControlPanel(Base):
    """Singleton-ish control-panel settings store (vertex-settings-control-panel)."""
    __tablename__ = "vtx_control_panel"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[int] = mapped_column(Integer)


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

LAYOUT_TYPES = {"auto", "grid", "circular", "radial", "hierarchy", "cluster"}
DIRECTIONS = {"out", "in", "both"}
# Scale factor for circular layouts; positions are still on the unit circle once divided.
_CIRCLE_SCALE = 100.0
_GRID_SPACING = 100.0


class GraphCreate(BaseModel):
    id: Optional[str] = None
    display_name: str
    description: Optional[str] = None
    seed_object_ids: List[str] = Field(default_factory=list)
    layout_type: str = "auto"
    owner: Optional[str] = None


class GraphRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    display_name: str
    description: Optional[str] = None
    seed_object_ids: List[str]
    nodes: List[Dict[str, Any]]
    edges: List[Dict[str, Any]]
    layout_type: str
    styles: Dict[str, Any]
    owner: Optional[str] = None
    created_at: int
    updated_at: int


class ExploreRequest(BaseModel):
    link_type_id: Optional[str] = None
    direction: str = "both"
    depth: int = 1


class ExploreResponse(BaseModel):
    graph: GraphRead
    added_nodes: int
    added_edges: int


class LayoutRequest(BaseModel):
    layout_type: str


class FilterRequest(BaseModel):
    property: str
    op: str
    value: Any = None


class FilterResponse(BaseModel):
    graph: GraphRead
    matched: int
    faded: int


class StyleRequest(BaseModel):
    node_styling: Dict[str, Any] = Field(default_factory=dict)
    edge_styling: Dict[str, Any] = Field(default_factory=dict)


class TemplateObjectParam(BaseModel):
    name: str
    object_type_id: str


class TemplateScalarParam(BaseModel):
    name: str
    default: Any = None


class TemplateSearchAround(BaseModel):
    link_type_id: Optional[str] = None
    direction: str = "both"
    depth: int = 1


class TemplateCreate(BaseModel):
    id: Optional[str] = None
    display_name: str
    object_params: List[TemplateObjectParam] = Field(default_factory=list)
    scalar_params: List[TemplateScalarParam] = Field(default_factory=list)
    search_arounds: List[TemplateSearchAround] = Field(default_factory=list)


class TemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    display_name: str
    object_params: List[Dict[str, Any]]
    scalar_params: List[Dict[str, Any]]
    search_arounds: List[Dict[str, Any]]
    created_at: int


class TemplateExecuteRequest(BaseModel):
    object_param_values: Dict[str, str] = Field(default_factory=dict)
    scalar_overrides: Dict[str, Any] = Field(default_factory=dict)
    display_name: Optional[str] = None


class EventConfigRequest(BaseModel):
    event_object_type_id: str
    start_time_field: str
    end_time_field: Optional[str] = None
    intent: Optional[str] = None


class TimelineFilterRequest(BaseModel):
    start_ms: int
    end_ms: int


class ScenarioRequest(BaseModel):
    display_name: Optional[str] = None
    parameter_overrides: Dict[str, Dict[str, Any]] = Field(default_factory=dict)


class ControlPanelRequest(BaseModel):
    settings: Dict[str, Any] = Field(default_factory=dict)


MERGE_AGGREGATIONS = {"count", "sum_weight"}
# Property names searched (in order) for a numeric edge weight when summing.
_WEIGHT_PROP_NAMES = ("weight", "value", "amount")


class LinkMergeRequest(BaseModel):
    # Optional: restrict merging to edges of one link type (others left untouched).
    link_type_id: Optional[str] = None
    # Optional: also split the merge buckets by an edge property value.
    group_by: Optional[str] = None
    aggregation: str = "count"


class LinkMergeResponse(BaseModel):
    graph: GraphRead
    before_edge_count: int
    after_edge_count: int
    merged_edge_count: int
    merged_edges: List[Dict[str, Any]]


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(tags=["vertex"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> int:
    return int(time.time())


def _audit(db: Session, event_type: str, subject_type: str, subject_id: str, payload: dict) -> None:
    db.add(models_action.AuditLog(
        id=uuid.uuid4().hex,
        actor="system",
        event_type=event_type,
        subject_type=subject_type,
        subject_id=subject_id,
        payload=payload,
    ))


def _get_graph(db: Session, graph_id: str) -> VtxGraph:
    g = db.query(VtxGraph).filter(VtxGraph.id == graph_id).first()
    if not g:
        raise HTTPException(status_code=404, detail=f"VtxGraph '{graph_id}' not found")
    return g


def _load_nodes(g: VtxGraph) -> List[Dict[str, Any]]:
    """Return a deep copy of the graph's persisted nodes.

    A fresh copy is required so that reassigning ``g.nodes`` is seen as a NEW object
    by SQLAlchemy's JSON column change detection (mutating the in-place dicts would
    otherwise not be flushed on commit).
    """
    return copy.deepcopy(list(g.nodes or []))


def _load_edges(g: VtxGraph) -> List[Dict[str, Any]]:
    return copy.deepcopy(list(g.edges or []))


def _node_from_object(obj: models.ObjectInstance) -> Dict[str, Any]:
    return {
        "id": obj.id,
        "object_type_id": obj.object_type_id,
        "properties": dict(obj.properties or {}),
        "faded": False,
    }


def _apply_layout(nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]], layout_type: str) -> List[Dict[str, Any]]:
    """Deterministically assign each node an {x, y}. Returns the same node list mutated."""
    n = len(nodes)
    if n == 0:
        return nodes
    lt = layout_type if layout_type in LAYOUT_TYPES else "auto"

    if lt in ("auto", "grid"):
        cols = max(1, int(math.ceil(math.sqrt(n))))
        for i, node in enumerate(nodes):
            node["x"] = float((i % cols) * _GRID_SPACING)
            node["y"] = float((i // cols) * _GRID_SPACING)

    elif lt in ("circular", "radial"):
        for k, node in enumerate(nodes):
            angle = 2.0 * math.pi * k / n
            node["x"] = round(math.cos(angle) * _CIRCLE_SCALE, 9)
            node["y"] = round(math.sin(angle) * _CIRCLE_SCALE, 9)

    elif lt == "hierarchy":
        # x by BFS depth from seeds, y by order within depth.
        depth_by_id = _bfs_depths(nodes, edges)
        # group node ids by depth (deterministic by current node order)
        by_depth: Dict[int, List[int]] = {}
        for idx, node in enumerate(nodes):
            d = depth_by_id.get(node["id"], 0)
            by_depth.setdefault(d, []).append(idx)
        for d, idxs in by_depth.items():
            for order, idx in enumerate(idxs):
                nodes[idx]["x"] = float(d * _GRID_SPACING)
                nodes[idx]["y"] = float(order * _GRID_SPACING)

    elif lt == "cluster":
        # group by object_type_id (sorted for determinism), then grid within cluster.
        groups: Dict[str, List[int]] = {}
        for idx, node in enumerate(nodes):
            groups.setdefault(node.get("object_type_id") or "", []).append(idx)
        for gi, key in enumerate(sorted(groups.keys())):
            idxs = groups[key]
            cols = max(1, int(math.ceil(math.sqrt(len(idxs)))))
            for j, idx in enumerate(idxs):
                nodes[idx]["x"] = float(gi * _GRID_SPACING * 10 + (j % cols) * _GRID_SPACING)
                nodes[idx]["y"] = float((j // cols) * _GRID_SPACING)

    return nodes


def _bfs_depths(nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> Dict[str, int]:
    """Compute BFS depth of each node from the seed set (faded flag is irrelevant here)."""
    node_ids = {node["id"] for node in nodes}
    # seeds = nodes flagged as seed, else the first node deterministically
    seeds = [node["id"] for node in nodes if node.get("is_seed")]
    if not seeds and nodes:
        seeds = [nodes[0]["id"]]
    adj: Dict[str, set] = {nid: set() for nid in node_ids}
    for e in edges:
        s, t = e.get("source_object_id"), e.get("target_object_id")
        if s in adj and t in adj:
            adj[s].add(t)
            adj[t].add(s)
    depths: Dict[str, int] = {}
    frontier = list(seeds)
    for s in seeds:
        depths[s] = 0
    d = 0
    while frontier:
        d += 1
        nxt: List[str] = []
        for cur in frontier:
            for nb in sorted(adj.get(cur, ())):
                if nb not in depths:
                    depths[nb] = d
                    nxt.append(nb)
        frontier = nxt
    # any unreachable node → depth 0
    for nid in node_ids:
        depths.setdefault(nid, 0)
    return depths


def _expand(
    db: Session,
    current_node_ids: List[str],
    link_type_id: Optional[str],
    direction: str,
    depth: int,
) -> Dict[str, Any]:
    """BFS over LinkInstance from current node ids. Mirrors search_around_objects.

    direction uses Vertex vocabulary out/in/both (out == follow source→target).
    Returns {node_ids:set, edges:[edge dicts]}.
    """
    if direction not in DIRECTIONS:
        raise HTTPException(status_code=422, detail="direction must be one of out/in/both")
    if link_type_id and not db.query(models.LinkType).filter(models.LinkType.id == link_type_id).first():
        raise HTTPException(status_code=404, detail=f"LinkType '{link_type_id}' not found")

    bounded_depth = max(1, min(int(depth), 6))
    frontier = set(str(x) for x in current_node_ids)
    visited = set(frontier)
    node_ids = set(frontier)
    edge_map: Dict[str, Dict[str, Any]] = {}

    q = db.query(models.LinkInstance)
    if link_type_id:
        q = q.filter(models.LinkInstance.link_type_id == link_type_id)
    all_links = q.all()

    for _ in range(bounded_depth):
        if not frontier:
            break
        next_frontier: set = set()
        for link in all_links:
            neighbors: List[str] = []
            if direction in ("out", "both") and link.source_object_id in frontier:
                neighbors.append(link.target_object_id)
            if direction in ("in", "both") and link.target_object_id in frontier:
                neighbors.append(link.source_object_id)
            if not neighbors:
                continue
            for neighbor_id in neighbors:
                neighbor = db.query(models.ObjectInstance).filter(
                    models.ObjectInstance.id == neighbor_id
                ).first()
                if not neighbor:
                    continue
                edge_map[link.id] = {
                    "id": link.id,
                    "link_type_id": link.link_type_id,
                    "source_object_id": link.source_object_id,
                    "target_object_id": link.target_object_id,
                }
                node_ids.add(link.source_object_id)
                node_ids.add(link.target_object_id)
                if neighbor_id not in visited:
                    next_frontier.add(neighbor_id)
        visited.update(next_frontier)
        frontier = next_frontier

    return {"node_ids": node_ids, "edges": list(edge_map.values())}


def _materialize_nodes(db: Session, node_ids, existing: List[Dict[str, Any]], seed_ids: set) -> List[Dict[str, Any]]:
    """Build node dicts for the given ids, preserving existing faded flags."""
    faded_by_id = {n["id"]: n.get("faded", False) for n in existing}
    result: List[Dict[str, Any]] = []
    for nid in sorted(node_ids):
        obj = db.query(models.ObjectInstance).filter(models.ObjectInstance.id == nid).first()
        if not obj:
            continue
        node = _node_from_object(obj)
        node["faded"] = faded_by_id.get(nid, False)
        node["is_seed"] = nid in seed_ids
        result.append(node)
    return result


def _compare(left: Any, op: str, right: Any) -> bool:
    try:
        if op == "eq":
            return left == right
        if op == "neq":
            return left != right
        if op == "gt":
            return left is not None and left > right
        if op == "gte":
            return left is not None and left >= right
        if op == "lt":
            return left is not None and left < right
        if op == "lte":
            return left is not None and left <= right
        if op == "contains":
            return right in left if left is not None else False
        if op == "exists":
            return left is not None
    except TypeError:
        return False
    raise HTTPException(status_code=422, detail=f"Unsupported op '{op}'")


# ---------------------------------------------------------------------------
# 1. Build graph
# ---------------------------------------------------------------------------


@router.post("/vertex/graphs", response_model=GraphRead)
def create_graph(body: GraphCreate, db: Session = Depends(get_db)):
    if body.layout_type not in LAYOUT_TYPES:
        raise HTTPException(status_code=422, detail=f"layout_type must be one of {sorted(LAYOUT_TYPES)}")

    seed_ids = list(dict.fromkeys(body.seed_object_ids))  # dedupe, keep order
    seed_objs = []
    for sid in seed_ids:
        obj = db.query(models.ObjectInstance).filter(models.ObjectInstance.id == sid).first()
        if not obj:
            raise HTTPException(status_code=404, detail=f"Seed object '{sid}' not found")
        seed_objs.append(obj)

    nodes = []
    seed_set = set(seed_ids)
    for obj in seed_objs:
        node = _node_from_object(obj)
        node["is_seed"] = True
        nodes.append(node)
    edges: List[Dict[str, Any]] = []
    _apply_layout(nodes, edges, body.layout_type)

    gid = body.id or uuid.uuid4().hex
    if db.query(VtxGraph).filter(VtxGraph.id == gid).first():
        raise HTTPException(status_code=400, detail="VtxGraph already exists")
    now = _now()
    g = VtxGraph(
        id=gid,
        display_name=body.display_name,
        description=body.description,
        seed_object_ids=seed_ids,
        nodes=nodes,
        edges=edges,
        layout_type=body.layout_type,
        styles={},
        owner=body.owner,
        created_at=now,
        updated_at=now,
    )
    db.add(g)
    _audit(db, "vertex.graph.created", "vtx_graph", gid,
           {"seed_count": len(seed_ids), "layout": body.layout_type})
    db.commit()
    db.refresh(g)
    return g


@router.get("/vertex/graphs", response_model=List[GraphRead])
def list_graphs(db: Session = Depends(get_db)):
    return db.query(VtxGraph).order_by(VtxGraph.created_at).all()


@router.get("/vertex/graphs/{graph_id}", response_model=GraphRead)
def get_graph(graph_id: str, db: Session = Depends(get_db)):
    return _get_graph(db, graph_id)


# ---------------------------------------------------------------------------
# 2. Expand / explore
# ---------------------------------------------------------------------------


@router.post("/vertex/graphs/{graph_id}/explore", response_model=ExploreResponse)
def explore_graph(graph_id: str, body: ExploreRequest, db: Session = Depends(get_db)):
    g = _get_graph(db, graph_id)
    existing_nodes = _load_nodes(g)
    existing_edges = _load_edges(g)
    prev_node_ids = {n["id"] for n in existing_nodes}
    prev_edge_ids = {e["id"] for e in existing_edges}
    current_ids = [n["id"] for n in existing_nodes]

    result = _expand(db, current_ids, body.link_type_id, body.direction, body.depth)
    new_node_ids = result["node_ids"]
    new_edges = result["edges"]

    seed_set = set(g.seed_object_ids or [])
    merged_node_ids = prev_node_ids | new_node_ids
    merged_nodes = _materialize_nodes(db, merged_node_ids, existing_nodes, seed_set)

    edge_by_id = {e["id"]: e for e in existing_edges}
    for e in new_edges:
        edge_by_id[e["id"]] = e
    merged_edges = list(edge_by_id.values())

    _apply_layout(merged_nodes, merged_edges, g.layout_type)

    added_nodes = len(merged_node_ids - prev_node_ids)
    added_edges = len({e["id"] for e in merged_edges} - prev_edge_ids)

    g.nodes = merged_nodes
    g.edges = merged_edges
    g.updated_at = _now()
    _audit(db, "vertex.graph.explored", "vtx_graph", graph_id,
           {"added_nodes": added_nodes, "added_edges": added_edges})
    db.commit()
    db.refresh(g)
    return ExploreResponse(graph=GraphRead.model_validate(g), added_nodes=added_nodes, added_edges=added_edges)


# ---------------------------------------------------------------------------
# 2b. Link merging — collapse parallel/intermediate edges between the same
#     endpoint pair into a SINGLE aggregated edge carrying a count (and a
#     summed weight if a numeric weight property is present).
#     Docs basis: vertex/link-merging.
# ---------------------------------------------------------------------------


def _numeric_weight(props: Dict[str, Any]) -> Optional[float]:
    """Pick the first numeric value among the known weight property names."""
    if not isinstance(props, dict):
        return None
    for name in _WEIGHT_PROP_NAMES:
        val = props.get(name)
        if isinstance(val, bool):
            continue
        if isinstance(val, (int, float)):
            return float(val)
    return None


def _edge_weight(edge: Dict[str, Any], weight_by_edge_id: Dict[str, float]) -> Optional[float]:
    """Return a numeric weight for a graph edge.

    Precedence: a top-level/embedded weight already materialized on the edge dict
    (``weight`` then ``value`` / ``amount``, also inside an edge ``properties``
    sub-dict), then a weight resolved from the underlying LinkInstance properties
    (``weight_by_edge_id``, keyed by edge id). Returns None when no numeric weight
    is present anywhere.
    """
    w = _numeric_weight(edge)
    if w is not None:
        return w
    w = _numeric_weight(edge.get("properties") or {})
    if w is not None:
        return w
    return weight_by_edge_id.get(str(edge.get("id")))


def _endpoint_pair_key(edge: Dict[str, Any]):
    """Unordered endpoint-pair key so parallel edges in either direction collapse."""
    s = edge.get("source_object_id")
    t = edge.get("target_object_id")
    return tuple(sorted((str(s), str(t))))


@router.post("/vertex/graphs/{graph_id}/links/merge", response_model=LinkMergeResponse)
def merge_links(graph_id: str, body: LinkMergeRequest, db: Session = Depends(get_db)):
    """Collapse multiple parallel/intermediate edges between the SAME endpoint pair
    into one aggregated edge carrying a ``merged_count`` (and ``merged_weight`` when a
    numeric weight property is present), then persist the rewritten edge list.

    Selection:
      * ``link_type_id`` (optional) — only edges of that link type are eligible to
        merge; all other edges pass through unchanged.
      * ``group_by`` (optional) — additionally split buckets by an edge property
        value so semantically different edges between the same pair stay separate.
      * ``aggregation`` — ``count`` (default) or ``sum_weight``.
    """
    if body.aggregation not in MERGE_AGGREGATIONS:
        raise HTTPException(
            status_code=422,
            detail=f"aggregation must be one of {sorted(MERGE_AGGREGATIONS)}",
        )
    if body.link_type_id and not db.query(models.LinkType).filter(
        models.LinkType.id == body.link_type_id
    ).first():
        raise HTTPException(status_code=404, detail=f"LinkType '{body.link_type_id}' not found")

    g = _get_graph(db, graph_id)
    edges = _load_edges(g)
    before_edge_count = len(edges)

    # Resolve numeric weights from the underlying LinkInstance properties for any
    # edge id that maps to a real link (graph edges don't materialize link props).
    edge_ids = [str(e.get("id")) for e in edges if e.get("id") is not None]
    weight_by_edge_id: Dict[str, float] = {}
    # Resolve the group_by property from the underlying LinkInstance too — graph edges
    # don't materialize link properties, so grouping must fall back to the real link.
    group_val_by_edge_id: Dict[str, Any] = {}
    if edge_ids:
        for li in db.query(models.LinkInstance).filter(
            models.LinkInstance.id.in_(edge_ids)
        ).all():
            li_props = li.properties or {}
            w = _numeric_weight(li_props)
            if w is not None:
                weight_by_edge_id[li.id] = w
            if body.group_by and body.group_by in li_props:
                group_val_by_edge_id[li.id] = li_props[body.group_by]

    def _group_val(edge: Dict[str, Any]) -> Any:
        if not body.group_by:
            return None
        # Precedence: materialized on the edge dict, then its embedded properties,
        # then the underlying LinkInstance properties (keyed by edge id).
        if body.group_by in edge:
            return edge.get(body.group_by)
        props = edge.get("properties") if isinstance(edge.get("properties"), dict) else {}
        if body.group_by in props:
            return props.get(body.group_by)
        return group_val_by_edge_id.get(str(edge.get("id")))

    # Bucket eligible edges; pass-through everything not eligible to merge.
    buckets: Dict[Any, List[Dict[str, Any]]] = {}
    bucket_order: List[Any] = []
    passthrough: List[Dict[str, Any]] = []
    for edge in edges:
        eligible = body.link_type_id is None or edge.get("link_type_id") == body.link_type_id
        if not eligible:
            passthrough.append(edge)
            continue
        key = (_endpoint_pair_key(edge), edge.get("link_type_id"), _group_val(edge))
        if key not in buckets:
            buckets[key] = []
            bucket_order.append(key)
        buckets[key].append(edge)

    merged_edges: List[Dict[str, Any]] = []
    new_edges: List[Dict[str, Any]] = []
    for key in bucket_order:
        members = buckets[key]
        if len(members) <= 1:
            # Nothing to collapse — keep the single edge as-is.
            new_edges.extend(members)
            continue
        rep = members[0]
        pair = key[0]
        member_ids = [m.get("id") for m in members]
        weights = [w for w in (_edge_weight(m, weight_by_edge_id) for m in members) if w is not None]
        summed_weight = sum(weights) if weights else None
        merged = {
            "id": f"merged::{pair[0]}::{pair[1]}::{rep.get('link_type_id') or ''}"
                  + (f"::{key[2]}" if body.group_by else ""),
            "link_type_id": rep.get("link_type_id"),
            "source_object_id": pair[0],
            "target_object_id": pair[1],
            "merged": True,
            "merged_count": len(members),
            "aggregation": body.aggregation,
            "merged_edge_ids": member_ids,
        }
        if body.group_by:
            merged["group_by"] = body.group_by
            merged["group_value"] = key[2]
        if summed_weight is not None:
            merged["merged_weight"] = summed_weight
        # The label surfaces the chosen aggregation in the UI.
        if body.aggregation == "sum_weight" and summed_weight is not None:
            merged["label"] = str(summed_weight)
        else:
            merged["label"] = str(len(members))
        merged_edges.append(merged)
        new_edges.append(merged)

    final_edges = passthrough + new_edges
    g.edges = final_edges
    g.updated_at = _now()
    _audit(db, "vertex.links.merged", "vtx_graph", graph_id,
           {"before_edge_count": before_edge_count, "after_edge_count": len(final_edges),
            "merged_edge_count": len(merged_edges), "aggregation": body.aggregation})
    db.commit()
    db.refresh(g)
    return LinkMergeResponse(
        graph=GraphRead.model_validate(g),
        before_edge_count=before_edge_count,
        after_edge_count=len(final_edges),
        merged_edge_count=len(merged_edges),
        merged_edges=merged_edges,
    )


# ---------------------------------------------------------------------------
# 3. Layout
# ---------------------------------------------------------------------------


@router.post("/vertex/graphs/{graph_id}/layout", response_model=GraphRead)
def relayout_graph(graph_id: str, body: LayoutRequest, db: Session = Depends(get_db)):
    if body.layout_type not in LAYOUT_TYPES:
        raise HTTPException(status_code=422, detail=f"layout_type must be one of {sorted(LAYOUT_TYPES)}")
    g = _get_graph(db, graph_id)
    nodes = _load_nodes(g)
    edges = _load_edges(g)
    _apply_layout(nodes, edges, body.layout_type)
    g.nodes = nodes
    g.layout_type = body.layout_type
    g.updated_at = _now()
    db.commit()
    db.refresh(g)
    return g


# ---------------------------------------------------------------------------
# 4. Filter (fading)
# ---------------------------------------------------------------------------


@router.post("/vertex/graphs/{graph_id}/filter", response_model=FilterResponse)
def filter_graph(graph_id: str, body: FilterRequest, db: Session = Depends(get_db)):
    g = _get_graph(db, graph_id)
    nodes = _load_nodes(g)
    matched = 0
    faded = 0
    for node in nodes:
        val = (node.get("properties") or {}).get(body.property)
        keep = _compare(val, body.op, body.value)
        node["faded"] = not keep
        if keep:
            matched += 1
        else:
            faded += 1
    g.nodes = nodes
    g.updated_at = _now()
    db.commit()
    db.refresh(g)
    return FilterResponse(graph=GraphRead.model_validate(g), matched=matched, faded=faded)


# ---------------------------------------------------------------------------
# 5. Style
# ---------------------------------------------------------------------------


@router.post("/vertex/graphs/{graph_id}/style", response_model=GraphRead)
def style_graph(graph_id: str, body: StyleRequest, db: Session = Depends(get_db)):
    g = _get_graph(db, graph_id)
    styles = dict(g.styles or {})
    if body.node_styling:
        styles["node_styling"] = body.node_styling
    if body.edge_styling:
        styles["edge_styling"] = body.edge_styling
    g.styles = styles
    g.updated_at = _now()
    db.commit()
    db.refresh(g)
    return g


# ---------------------------------------------------------------------------
# 6. Templates
# ---------------------------------------------------------------------------


@router.post("/vertex/templates", response_model=TemplateRead)
def create_template(body: TemplateCreate, db: Session = Depends(get_db)):
    tid = body.id or uuid.uuid4().hex
    if db.query(VtxTemplate).filter(VtxTemplate.id == tid).first():
        raise HTTPException(status_code=400, detail="VtxTemplate already exists")
    t = VtxTemplate(
        id=tid,
        display_name=body.display_name,
        object_params=[p.model_dump() for p in body.object_params],
        scalar_params=[p.model_dump() for p in body.scalar_params],
        search_arounds=[s.model_dump() for s in body.search_arounds],
        created_at=_now(),
    )
    db.add(t)
    _audit(db, "vertex.template.created", "vtx_template", tid, {"display_name": body.display_name})
    db.commit()
    db.refresh(t)
    return t


@router.get("/vertex/templates", response_model=List[TemplateRead])
def list_templates(db: Session = Depends(get_db)):
    return db.query(VtxTemplate).order_by(VtxTemplate.created_at).all()


@router.post("/vertex/templates/{template_id}/execute", response_model=GraphRead)
def execute_template(template_id: str, body: TemplateExecuteRequest, db: Session = Depends(get_db)):
    t = db.query(VtxTemplate).filter(VtxTemplate.id == template_id).first()
    if not t:
        raise HTTPException(status_code=404, detail=f"VtxTemplate '{template_id}' not found")

    # Resolve seeds from object_param_values, validating against the template's declared params.
    declared = {p["name"]: p["object_type_id"] for p in (t.object_params or [])}
    seed_ids: List[str] = []
    for name, object_type_id in declared.items():
        if name not in body.object_param_values:
            raise HTTPException(status_code=422, detail=f"Missing object param value for '{name}'")
        oid = body.object_param_values[name]
        obj = db.query(models.ObjectInstance).filter(models.ObjectInstance.id == oid).first()
        if not obj:
            raise HTTPException(status_code=404, detail=f"Object '{oid}' for param '{name}' not found")
        if obj.object_type_id != object_type_id:
            raise HTTPException(
                status_code=422,
                detail=f"Object '{oid}' is not of type '{object_type_id}' required by param '{name}'",
            )
        if oid not in seed_ids:
            seed_ids.append(oid)

    # Build base graph from mapped seeds.
    seed_set = set(seed_ids)
    nodes: List[Dict[str, Any]] = []
    for oid in seed_ids:
        obj = db.query(models.ObjectInstance).filter(models.ObjectInstance.id == oid).first()
        node = _node_from_object(obj)
        node["is_seed"] = True
        nodes.append(node)
    edges: List[Dict[str, Any]] = []

    # Run each defined search-around in order, accumulating nodes/edges.
    for sa in (t.search_arounds or []):
        current_ids = [n["id"] for n in nodes]
        result = _expand(db, current_ids, sa.get("link_type_id"), sa.get("direction", "both"), sa.get("depth", 1))
        merged_node_ids = {n["id"] for n in nodes} | result["node_ids"]
        nodes = _materialize_nodes(db, merged_node_ids, nodes, seed_set)
        edge_by_id = {e["id"]: e for e in edges}
        for e in result["edges"]:
            edge_by_id[e["id"]] = e
        edges = list(edge_by_id.values())

    layout = "auto"
    _apply_layout(nodes, edges, layout)

    gid = uuid.uuid4().hex
    now = _now()
    g = VtxGraph(
        id=gid,
        display_name=body.display_name or f"{t.display_name} (run)",
        description=f"Generated from template {template_id}",
        seed_object_ids=seed_ids,
        nodes=nodes,
        edges=edges,
        layout_type=layout,
        styles={},
        owner=None,
        created_at=now,
        updated_at=now,
    )
    db.add(g)
    _audit(db, "vertex.template.executed", "vtx_template", template_id,
           {"graph_id": gid, "node_count": len(nodes), "edge_count": len(edges)})
    db.commit()
    db.refresh(g)
    return g


# ---------------------------------------------------------------------------
# 7. Events / timeline
# ---------------------------------------------------------------------------


@router.post("/vertex/graphs/{graph_id}/events")
def configure_events(graph_id: str, body: EventConfigRequest, db: Session = Depends(get_db)):
    g = _get_graph(db, graph_id)
    cfg = VtxEventConfig(
        id=uuid.uuid4().hex,
        graph_id=g.id,
        event_object_type_id=body.event_object_type_id,
        start_time_field=body.start_time_field,
        end_time_field=body.end_time_field,
        intent=body.intent,
        created_at=_now(),
    )
    db.add(cfg)
    db.commit()
    db.refresh(cfg)
    return {
        "id": cfg.id,
        "graph_id": cfg.graph_id,
        "event_object_type_id": cfg.event_object_type_id,
        "start_time_field": cfg.start_time_field,
        "end_time_field": cfg.end_time_field,
        "intent": cfg.intent,
        "created_at": cfg.created_at,
    }


def _graph_event_configs(db: Session, graph_id: str) -> List[VtxEventConfig]:
    return db.query(VtxEventConfig).filter(VtxEventConfig.graph_id == graph_id).all()


def _node_start_ms(node: Dict[str, Any], configs: List[VtxEventConfig]) -> Optional[int]:
    """Resolve a node's event start time using a matching event config, else None."""
    props = node.get("properties") or {}
    for cfg in configs:
        if node.get("object_type_id") == cfg.event_object_type_id and cfg.start_time_field in props:
            val = props.get(cfg.start_time_field)
            if isinstance(val, (int, float)):
                return int(val)
    return None


@router.get("/vertex/graphs/{graph_id}/timeline")
def get_timeline(graph_id: str, db: Session = Depends(get_db)):
    g = _get_graph(db, graph_id)
    configs = _graph_event_configs(db, graph_id)
    events = []
    for node in (g.nodes or []):
        start = _node_start_ms(node, configs)
        if start is None:
            continue
        # resolve end if a config provides it
        end = None
        props = node.get("properties") or {}
        for cfg in configs:
            if node.get("object_type_id") == cfg.event_object_type_id and cfg.end_time_field and cfg.end_time_field in props:
                ev = props.get(cfg.end_time_field)
                if isinstance(ev, (int, float)):
                    end = int(ev)
        events.append({"node_id": node["id"], "start_ms": start, "end_ms": end})
    events.sort(key=lambda e: (e["start_ms"], e["node_id"]))
    return {"graph_id": graph_id, "events": events, "count": len(events)}


@router.post("/vertex/graphs/{graph_id}/timeline/filter", response_model=FilterResponse)
def timeline_filter(graph_id: str, body: TimelineFilterRequest, db: Session = Depends(get_db)):
    g = _get_graph(db, graph_id)
    configs = _graph_event_configs(db, graph_id)
    nodes = _load_nodes(g)
    matched = 0
    faded = 0
    for node in nodes:
        start = _node_start_ms(node, configs)
        # Nodes without an event start are kept visible (no temporal info to filter on).
        if start is None:
            node["faded"] = False
            matched += 1
            continue
        in_window = body.start_ms <= start <= body.end_ms
        node["faded"] = not in_window
        if in_window:
            matched += 1
        else:
            faded += 1
    g.nodes = nodes
    g.updated_at = _now()
    db.commit()
    db.refresh(g)
    return FilterResponse(graph=GraphRead.model_validate(g), matched=matched, faded=faded)


# ---------------------------------------------------------------------------
# 8. Scenarios — DETERMINISTIC what-if simulation (NOT a model invoke)
# ---------------------------------------------------------------------------


@router.post("/vertex/graphs/{graph_id}/scenarios")
def create_scenario(graph_id: str, body: ScenarioRequest, db: Session = Depends(get_db)):
    """Clone current node props as baseline, apply overrides to a copy, return the diff.

    This is a fully deterministic what-if simulation: there is NO model / ML invocation.
    """
    g = _get_graph(db, graph_id)
    baseline: Dict[str, Dict[str, Any]] = {}
    scenario_output: Dict[str, Dict[str, Any]] = {}
    diff: Dict[str, Dict[str, Any]] = {}

    for node in (g.nodes or []):
        nid = node["id"]
        props = dict(node.get("properties") or {})
        baseline[nid] = props
        overridden = dict(props)
        node_overrides = body.parameter_overrides.get(nid, {})
        node_diff: Dict[str, Any] = {}
        for prop, new_val in node_overrides.items():
            old_val = props.get(prop)
            overridden[prop] = new_val
            if old_val != new_val:
                node_diff[prop] = {"baseline": old_val, "scenario": new_val}
        scenario_output[nid] = overridden
        if node_diff:
            diff[nid] = node_diff

    sid = uuid.uuid4().hex
    sc = VtxScenario(
        id=sid,
        graph_id=g.id,
        display_name=body.display_name,
        parameter_overrides=body.parameter_overrides,
        baseline=baseline,
        scenario_output=scenario_output,
        created_at=_now(),
    )
    db.add(sc)
    _audit(db, "vertex.scenario.created", "vtx_scenario", sid,
           {"graph_id": g.id, "changed_nodes": len(diff)})
    db.commit()
    db.refresh(sc)
    return {
        "id": sc.id,
        "graph_id": sc.graph_id,
        "display_name": sc.display_name,
        "kind": "deterministic_what_if_simulation",
        "baseline": baseline,
        "scenario_output": scenario_output,
        "diff": diff,
        "created_at": sc.created_at,
    }


@router.get("/vertex/graphs/{graph_id}/scenarios/{scenario_id}")
def get_scenario(graph_id: str, scenario_id: str, db: Session = Depends(get_db)):
    sc = db.query(VtxScenario).filter(
        VtxScenario.id == scenario_id, VtxScenario.graph_id == graph_id
    ).first()
    if not sc:
        raise HTTPException(status_code=404, detail=f"VtxScenario '{scenario_id}' not found")
    return {
        "id": sc.id,
        "graph_id": sc.graph_id,
        "display_name": sc.display_name,
        "kind": "deterministic_what_if_simulation",
        "parameter_overrides": sc.parameter_overrides,
        "baseline": sc.baseline,
        "scenario_output": sc.scenario_output,
        "created_at": sc.created_at,
    }


# ---------------------------------------------------------------------------
# 9. Control panel settings
# ---------------------------------------------------------------------------

_CONTROL_PANEL_ID = "vtx_control_panel_singleton"


@router.post("/vertex/control-panel/settings")
def set_control_panel(body: ControlPanelRequest, db: Session = Depends(get_db)):
    row = db.query(VtxControlPanel).filter(VtxControlPanel.id == _CONTROL_PANEL_ID).first()
    now = _now()
    if row:
        merged = dict(row.settings or {})
        merged.update(body.settings)
        row.settings = merged
        row.updated_at = now
    else:
        row = VtxControlPanel(id=_CONTROL_PANEL_ID, settings=dict(body.settings), updated_at=now)
        db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "settings": row.settings, "updated_at": row.updated_at}


@router.get("/vertex/control-panel/settings")
def get_control_panel(db: Session = Depends(get_db)):
    row = db.query(VtxControlPanel).filter(VtxControlPanel.id == _CONTROL_PANEL_ID).first()
    if not row:
        return {"id": _CONTROL_PANEL_ID, "settings": {}, "updated_at": None}
    return {"id": row.id, "settings": row.settings, "updated_at": row.updated_at}
