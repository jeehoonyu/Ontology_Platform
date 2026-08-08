"""
lineage_ops.py — Deepened Data Lineage operations.

Implements (faithful to Foundry data-lineage docs:
  data-lineage/{overview,explore-lineage,find-column,see-impact-marking-changes,
  build-timeline,stale-datasets,pipeline-rollback,dataset-rollback}):

  1. Recursive upstream/downstream traversal (BFS, depth-bounded, cycle-safe),
     grouped by depth level, over the dataset <-> pipeline <-> dataset graph.
  2. Column DISCOVERY (CRITIC CORRECTION): Foundry's documented "find column"
     feature locates datasets that contain a column by name — it is NOT a
     per-column source-pipeline transformation lineage. We model a
     LinDatasetSchema and implement discovery (exact + prefix).
  3. Impact analysis — recursive downstream resources tagged STALE/NEEDS_REBUILD,
     and marking-driven downstream PERMISSION_CHANGE impact.
  4. Staleness — compare a dataset's latest build to its upstream datasets' latest
     builds (UPSTREAM_CHANGED / NO_BUILD).
  5. Build timeline — record builds and report ordered history + metrics.
  6. Rollback — validate the target build succeeded, record a LinRollback row.

The base module `app/lineage.py` builds the cross-resource graph from core tables.
This module REBUILDS its own adjacency from core models (DataAsset,
PipelineDefinition: input_asset_id -> pipeline -> output_asset_id) and keeps all
endpoints under NEW paths so nothing collides with the base lineage router.

All new ORM classes/tables are prefixed `Lin`/`lin_` to avoid Base collisions.
"""

from .database import Base, get_db
from . import models, models_action
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, Integer, JSON, Boolean, Float, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, Session
from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List, Any, Dict
import time, uuid

router = APIRouter(tags=["lineage-ops"])


# ---------------------------------------------------------------------------
# SQLAlchemy models (all prefixed Lin / lin_)
# ---------------------------------------------------------------------------

class LinDatasetSchema(Base):
    """Registered column schema for a dataset (drives column discovery)."""
    __tablename__ = "lin_dataset_schemas"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    dataset_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    # list of {name, type, description}
    columns: Mapped[list] = mapped_column(JSON, default=list)
    updated_at: Mapped[int] = mapped_column(Integer)


class LinBuildRecord(Base):
    """A recorded build of a dataset (build timeline + staleness + rollback)."""
    __tablename__ = "lin_build_records"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    dataset_id: Mapped[str] = mapped_column(String, index=True)
    pipeline_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="SUCCEEDED")  # SUCCEEDED|FAILED|...
    records_in: Mapped[int] = mapped_column(Integer, default=0)
    records_out: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    completed_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class LinMarking(Base):
    """A security marking applied to a dataset (drives PERMISSION_CHANGE impact)."""
    __tablename__ = "lin_markings"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    dataset_id: Mapped[str] = mapped_column(String, index=True)
    marking: Mapped[str] = mapped_column(String)
    created_at: Mapped[int] = mapped_column(Integer)


class LinRollback(Base):
    """A recorded rollback of a dataset to a prior successful build."""
    __tablename__ = "lin_rollbacks"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    dataset_id: Mapped[str] = mapped_column(String, index=True)
    from_build_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    to_build_id: Mapped[str] = mapped_column(String)
    reason: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer)


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class ColumnSpec(BaseModel):
    name: str
    type: Optional[str] = None
    description: Optional[str] = None


class DatasetSchemaPut(BaseModel):
    columns: List[ColumnSpec] = Field(default_factory=list)


class DatasetSchemaRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    dataset_id: str
    columns: List[Dict[str, Any]]
    updated_at: int


class BuildCreate(BaseModel):
    id: Optional[str] = None
    pipeline_id: Optional[str] = None
    status: str = "SUCCEEDED"
    records_in: int = 0
    records_out: int = 0
    started_at: Optional[int] = None
    completed_at: Optional[int] = None
    duration_ms: Optional[int] = None


class BuildRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    dataset_id: str
    pipeline_id: Optional[str] = None
    status: str
    records_in: int
    records_out: int
    started_at: Optional[int] = None
    completed_at: Optional[int] = None
    duration_ms: Optional[int] = None


class MarkingCreate(BaseModel):
    id: Optional[str] = None
    marking: str


class RollbackCreate(BaseModel):
    to_build_id: str
    reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Internal graph helpers (rebuilt from core models — dataset<->pipeline<->dataset)
# ---------------------------------------------------------------------------

VALID_KINDS = {"dataset", "pipeline", "object_type"}


def _build_adjacency(db: Session):
    """
    Build directed adjacency over dataset and pipeline nodes from core models.

    Edges (directed, downstream direction):
      dataset(input_asset_id) -> pipeline      (feeds)
      pipeline -> dataset(output_asset_id)      (produces)

    Returns (down, up, node_kind):
      down[node]  = list of immediate downstream node ids
      up[node]    = list of immediate upstream node ids
      node_kind   = {node_id: "dataset"|"pipeline"}
    """
    down: Dict[str, List[str]] = {}
    up: Dict[str, List[str]] = {}
    node_kind: Dict[str, str] = {}

    assets = db.query(models.DataAsset).all()
    asset_ids = {a.id for a in assets}
    for a in assets:
        node_kind[a.id] = "dataset"
        down.setdefault(a.id, [])
        up.setdefault(a.id, [])

    pipelines = db.query(models.PipelineDefinition).all()
    for p in pipelines:
        node_kind[p.id] = "pipeline"
        down.setdefault(p.id, [])
        up.setdefault(p.id, [])

    def _add_edge(src: str, tgt: str):
        if tgt not in down[src]:
            down[src].append(tgt)
        if src not in up[tgt]:
            up[tgt].append(src)

    for p in pipelines:
        if p.input_asset_id and p.input_asset_id in asset_ids:
            _add_edge(p.input_asset_id, p.id)
        if p.output_asset_id and p.output_asset_id in asset_ids:
            _add_edge(p.id, p.output_asset_id)

    return down, up, node_kind


def _bfs_levels(
    start: str,
    adj: Dict[str, List[str]],
    max_depth: int,
    node_kind: Dict[str, str],
) -> List[Dict[str, Any]]:
    """
    Cycle-safe, depth-bounded BFS grouped by DATASET-distance depth.

    Foundry's lineage explorer counts hops between datasets; the pipeline nodes
    between two datasets are intermediate. So depth increments only when we reach
    a DATASET node. A pipeline reached from a depth-d dataset is reported at depth
    d+1 (the same depth as the dataset it produces), so for the chain
    A -> p1 -> B -> p2 -> C, downstream(A) yields p1,B at depth 1 and p2,C at
    depth 2. `max_depth` bounds the dataset-distance.

    Returns: [{depth: 1, nodes: [id, ...]}, {depth: 2, nodes: [...]}, ...]
    The start node is at depth 0 and is NOT included in the output levels.
    """
    visited = {start}
    # frontier holds (node_id, dataset_depth) where dataset_depth is the depth
    # already "spent" reaching this node's dataset layer.
    frontier = [(start, 0)]
    by_depth: Dict[int, List[str]] = {}

    while frontier:
        next_frontier: List[tuple] = []
        for node, dnode in frontier:
            for nb in adj.get(node, []):
                if nb in visited:
                    continue
                kind = node_kind.get(nb)
                if kind == "dataset":
                    nb_depth = dnode + 1
                else:
                    # pipeline (or unknown): same dataset-depth-layer as the
                    # dataset it leads to, i.e. one past its feeding dataset.
                    nb_depth = dnode + 1
                if nb_depth > max_depth:
                    continue
                visited.add(nb)
                by_depth.setdefault(nb_depth, []).append(nb)
                # When we step ONTO a dataset, its dataset-depth advances; when we
                # step onto a pipeline, the dataset-depth it carries forward stays
                # the same so the dataset it produces lands at the same layer.
                carry = nb_depth if kind == "dataset" else dnode
                next_frontier.append((nb, carry))
        frontier = next_frontier

    levels: List[Dict[str, Any]] = []
    for depth in sorted(by_depth.keys()):
        levels.append({"depth": depth, "nodes": by_depth[depth]})
    return levels


def _flatten_levels(levels: List[Dict[str, Any]], node_kind: Dict[str, str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for lvl in levels:
        for nid in lvl["nodes"]:
            out.append({"id": nid, "kind": node_kind.get(nid, "unknown"), "depth": lvl["depth"]})
    return out


def _require_node(db: Session, kind: str, resource_id: str, node_kind: Dict[str, str]):
    if kind not in VALID_KINDS:
        raise HTTPException(status_code=422, detail=f"kind must be one of {sorted(VALID_KINDS)}")
    if resource_id not in node_kind:
        raise HTTPException(status_code=404, detail=f"{kind} '{resource_id}' not found in lineage graph")


def _latest_build(db: Session, dataset_id: str) -> Optional[LinBuildRecord]:
    """Latest SUCCEEDED build for a dataset, ordered by completed_at then started_at."""
    builds = (
        db.query(LinBuildRecord)
        .filter(LinBuildRecord.dataset_id == dataset_id, LinBuildRecord.status == "SUCCEEDED")
        .all()
    )
    if not builds:
        return None

    def _key(b: LinBuildRecord):
        return (b.completed_at or 0, b.started_at or 0)

    return max(builds, key=_key)


def _upstream_datasets(dataset_id: str, up: Dict[str, List[str]], node_kind: Dict[str, str], max_depth: int = 1000) -> List[str]:
    """All upstream DATASET node ids (skipping pipeline nodes), recursive, cycle-safe."""
    visited = {dataset_id}
    frontier = [dataset_id]
    result: List[str] = []
    depth = 0
    while frontier and depth < max_depth:
        depth += 1
        nxt: List[str] = []
        for node in frontier:
            for nb in up.get(node, []):
                if nb not in visited:
                    visited.add(nb)
                    nxt.append(nb)
                    if node_kind.get(nb) == "dataset":
                        result.append(nb)
        frontier = nxt
    return result


# ---------------------------------------------------------------------------
# 1. Recursive traversal endpoints
# ---------------------------------------------------------------------------

@router.get("/lineage/resource/{kind}/{resource_id}/upstream")
def get_upstream(
    kind: str,
    resource_id: str,
    depth: int = Query(5, ge=1, le=100),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    down, up, node_kind = _build_adjacency(db)
    _require_node(db, kind, resource_id, node_kind)
    levels = _bfs_levels(resource_id, up, depth, node_kind)
    return {
        "resource_kind": node_kind.get(resource_id, kind),
        "resource_id": resource_id,
        "direction": "upstream",
        "depth": depth,
        "levels": levels,
        "nodes": _flatten_levels(levels, node_kind),
        "count": sum(len(lvl["nodes"]) for lvl in levels),
    }


@router.get("/lineage/resource/{kind}/{resource_id}/downstream")
def get_downstream(
    kind: str,
    resource_id: str,
    depth: int = Query(5, ge=1, le=100),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    down, up, node_kind = _build_adjacency(db)
    _require_node(db, kind, resource_id, node_kind)
    levels = _bfs_levels(resource_id, down, depth, node_kind)
    return {
        "resource_kind": node_kind.get(resource_id, kind),
        "resource_id": resource_id,
        "direction": "downstream",
        "depth": depth,
        "levels": levels,
        "nodes": _flatten_levels(levels, node_kind),
        "count": sum(len(lvl["nodes"]) for lvl in levels),
    }


# ---------------------------------------------------------------------------
# 2. Column discovery + schema registration
# ---------------------------------------------------------------------------

@router.put("/lineage/dataset/{dataset_id}/schema", response_model=DatasetSchemaRead)
def put_dataset_schema(
    dataset_id: str,
    body: DatasetSchemaPut,
    db: Session = Depends(get_db),
):
    asset = db.query(models.DataAsset).filter(models.DataAsset.id == dataset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail=f"DataAsset '{dataset_id}' not found")

    cols = [c.model_dump() for c in body.columns]
    names = [c["name"] for c in cols]
    if len(names) != len(set(names)):
        raise HTTPException(status_code=422, detail="Duplicate column names in schema")

    row = db.query(LinDatasetSchema).filter(LinDatasetSchema.dataset_id == dataset_id).first()
    now = int(time.time())
    if row:
        row.columns = cols
        row.updated_at = now
    else:
        row = LinDatasetSchema(
            id=uuid.uuid4().hex,
            dataset_id=dataset_id,
            columns=cols,
            updated_at=now,
        )
        db.add(row)
    db.add(models_action.AuditLog(
        id=uuid.uuid4().hex, actor="system",
        event_type="lineage.dataset_schema.registered",
        subject_type="dataset", subject_id=dataset_id,
        payload={"column_count": len(cols)},
    ))
    db.commit()
    db.refresh(row)
    return row


@router.get("/lineage/dataset/{dataset_id}/schema", response_model=DatasetSchemaRead)
def get_dataset_schema(dataset_id: str, db: Session = Depends(get_db)):
    row = db.query(LinDatasetSchema).filter(LinDatasetSchema.dataset_id == dataset_id).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"No registered schema for dataset '{dataset_id}'")
    return row


@router.get("/lineage/columns/search")
def search_columns(
    column: str = Query(...),
    prefix: bool = Query(False),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Column DISCOVERY: find datasets whose registered schema contains the column.
    exact match by default; ?prefix=true does a case-insensitive prefix match.
    """
    schemas = db.query(LinDatasetSchema).all()
    matches: List[Dict[str, Any]] = []
    needle = column.lower()
    for s in schemas:
        matched_cols = []
        for c in (s.columns or []):
            cname = c.get("name", "")
            if prefix:
                if cname.lower().startswith(needle):
                    matched_cols.append(c)
            else:
                if cname == column:
                    matched_cols.append(c)
        if matched_cols:
            matches.append({"dataset_id": s.dataset_id, "matched_columns": matched_cols})
    matches.sort(key=lambda m: m["dataset_id"])
    return {
        "column": column,
        "prefix": prefix,
        "datasets": matches,
        "count": len(matches),
    }


# ---------------------------------------------------------------------------
# 3. Impact analysis
# ---------------------------------------------------------------------------

# NOTE: this specific `/marking/{dataset_id}` route MUST be declared BEFORE the
# generic `/{kind}/{resource_id}` route below, otherwise FastAPI would match
# "marking" as a {kind} value and 422 on kind validation.
@router.get("/lineage/impact/marking/{dataset_id}")
def get_marking_impact(
    dataset_id: str,
    depth: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Downstream resources needing permission re-evaluation because a marking was
    applied to this dataset. Requires at least one LinMarking on the dataset.
    """
    down, up, node_kind = _build_adjacency(db)
    if dataset_id not in node_kind:
        raise HTTPException(status_code=404, detail=f"dataset '{dataset_id}' not found in lineage graph")

    markings = db.query(LinMarking).filter(LinMarking.dataset_id == dataset_id).all()
    if not markings:
        raise HTTPException(status_code=422, detail=f"No markings set on dataset '{dataset_id}'")

    levels = _bfs_levels(dataset_id, down, depth, node_kind)
    impacted: List[Dict[str, Any]] = []
    for lvl in levels:
        for nid in lvl["nodes"]:
            impacted.append({
                "id": nid,
                "kind": node_kind.get(nid, "unknown"),
                "depth": lvl["depth"],
                "impact_type": "PERMISSION_CHANGE",
            })
    return {
        "dataset_id": dataset_id,
        "markings": [m.marking for m in markings],
        "impacted": impacted,
        "count": len(impacted),
    }


@router.get("/lineage/impact/{kind}/{resource_id}")
def get_impact(
    kind: str,
    resource_id: str,
    depth: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """All downstream resources affected by a change, tagged with an impact_type."""
    down, up, node_kind = _build_adjacency(db)
    _require_node(db, kind, resource_id, node_kind)
    levels = _bfs_levels(resource_id, down, depth, node_kind)
    impacted: List[Dict[str, Any]] = []
    for lvl in levels:
        for nid in lvl["nodes"]:
            k = node_kind.get(nid, "unknown")
            # Datasets become STALE; pipelines NEED_REBUILD.
            impact_type = "STALE" if k == "dataset" else "NEEDS_REBUILD"
            impacted.append({"id": nid, "kind": k, "depth": lvl["depth"], "impact_type": impact_type})
    return {
        "resource_kind": node_kind.get(resource_id, kind),
        "resource_id": resource_id,
        "impacted": impacted,
        "count": len(impacted),
    }


@router.post("/lineage/dataset/{dataset_id}/markings")
def set_marking(dataset_id: str, body: MarkingCreate, db: Session = Depends(get_db)) -> Dict[str, Any]:
    asset = db.query(models.DataAsset).filter(models.DataAsset.id == dataset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail=f"DataAsset '{dataset_id}' not found")
    mid = body.id or uuid.uuid4().hex
    if db.query(LinMarking).filter(LinMarking.id == mid).first():
        raise HTTPException(status_code=400, detail="LinMarking already exists")
    row = LinMarking(id=mid, dataset_id=dataset_id, marking=body.marking, created_at=int(time.time()))
    db.add(row)
    db.add(models_action.AuditLog(
        id=uuid.uuid4().hex, actor="system",
        event_type="lineage.marking.set",
        subject_type="dataset", subject_id=dataset_id,
        payload={"marking": body.marking},
    ))
    db.commit()
    db.refresh(row)
    return {"id": row.id, "dataset_id": row.dataset_id, "marking": row.marking, "created_at": row.created_at}


@router.get("/lineage/dataset/{dataset_id}/markings")
def list_markings(dataset_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    rows = db.query(LinMarking).filter(LinMarking.dataset_id == dataset_id).order_by(LinMarking.created_at).all()
    return {
        "dataset_id": dataset_id,
        "markings": [{"id": r.id, "marking": r.marking, "created_at": r.created_at} for r in rows],
        "count": len(rows),
    }


# ---------------------------------------------------------------------------
# 4. Staleness
# ---------------------------------------------------------------------------

@router.get("/lineage/dataset/{dataset_id}/staleness")
def get_staleness(dataset_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    down, up, node_kind = _build_adjacency(db)
    if dataset_id not in node_kind or node_kind[dataset_id] != "dataset":
        raise HTTPException(status_code=404, detail=f"dataset '{dataset_id}' not found in lineage graph")

    this_build = _latest_build(db, dataset_id)
    if this_build is None:
        return {
            "dataset_id": dataset_id,
            "is_stale": True,
            "reason": "NO_BUILD",
            "this_completed_at": None,
            "newer_upstream": [],
        }

    this_ts = this_build.completed_at or this_build.started_at or 0
    upstream_ds = _upstream_datasets(dataset_id, up, node_kind)
    newer_upstream: List[Dict[str, Any]] = []
    for uid in upstream_ds:
        ub = _latest_build(db, uid)
        if ub is None:
            continue
        u_ts = ub.completed_at or ub.started_at or 0
        if u_ts > this_ts:
            newer_upstream.append({"dataset_id": uid, "completed_at": u_ts, "build_id": ub.id})

    is_stale = len(newer_upstream) > 0
    return {
        "dataset_id": dataset_id,
        "is_stale": is_stale,
        "reason": "UPSTREAM_CHANGED" if is_stale else None,
        "this_completed_at": this_ts,
        "newer_upstream": newer_upstream,
    }


# ---------------------------------------------------------------------------
# 5. Build timeline
# ---------------------------------------------------------------------------

@router.post("/lineage/dataset/{dataset_id}/builds", response_model=BuildRead)
def record_build(dataset_id: str, body: BuildCreate, db: Session = Depends(get_db)):
    asset = db.query(models.DataAsset).filter(models.DataAsset.id == dataset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail=f"DataAsset '{dataset_id}' not found")

    bid = body.id or uuid.uuid4().hex
    if db.query(LinBuildRecord).filter(LinBuildRecord.id == bid).first():
        raise HTTPException(status_code=400, detail="LinBuildRecord already exists")

    duration = body.duration_ms
    if duration is None and body.started_at is not None and body.completed_at is not None:
        duration = max(0, (body.completed_at - body.started_at) * 1000)

    row = LinBuildRecord(
        id=bid,
        dataset_id=dataset_id,
        pipeline_id=body.pipeline_id,
        status=body.status,
        records_in=body.records_in,
        records_out=body.records_out,
        started_at=body.started_at,
        completed_at=body.completed_at,
        duration_ms=duration,
    )
    db.add(row)
    db.add(models_action.AuditLog(
        id=uuid.uuid4().hex, actor="system",
        event_type="lineage.build.recorded",
        subject_type="dataset", subject_id=dataset_id,
        payload={"build_id": bid, "status": body.status},
    ))
    db.commit()
    db.refresh(row)
    return row


@router.get("/lineage/dataset/{dataset_id}/builds")
def list_builds(dataset_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    builds = db.query(LinBuildRecord).filter(LinBuildRecord.dataset_id == dataset_id).all()

    def _key(b: LinBuildRecord):
        return (b.started_at or 0, b.completed_at or 0)

    builds.sort(key=_key)

    count = len(builds)
    succeeded = [b for b in builds if b.status == "SUCCEEDED"]
    success_rate = (len(succeeded) / count) if count else 0.0
    durations = [b.duration_ms for b in builds if b.duration_ms is not None]
    avg_duration = (sum(durations) / len(durations)) if durations else 0.0
    total_records_out = sum(b.records_out or 0 for b in builds)

    history = [
        {
            "id": b.id,
            "dataset_id": b.dataset_id,
            "pipeline_id": b.pipeline_id,
            "status": b.status,
            "records_in": b.records_in,
            "records_out": b.records_out,
            "started_at": b.started_at,
            "completed_at": b.completed_at,
            "duration_ms": b.duration_ms,
        }
        for b in builds
    ]
    return {
        "dataset_id": dataset_id,
        "history": history,
        "metrics": {
            "count": count,
            "success_rate": success_rate,
            "avg_duration_ms": avg_duration,
            "total_records_out": total_records_out,
        },
    }


# ---------------------------------------------------------------------------
# 6. Rollback
# ---------------------------------------------------------------------------

@router.post("/lineage/dataset/{dataset_id}/rollback")
def rollback_dataset(dataset_id: str, body: RollbackCreate, db: Session = Depends(get_db)) -> Dict[str, Any]:
    asset = db.query(models.DataAsset).filter(models.DataAsset.id == dataset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail=f"DataAsset '{dataset_id}' not found")

    target = (
        db.query(LinBuildRecord)
        .filter(LinBuildRecord.id == body.to_build_id, LinBuildRecord.dataset_id == dataset_id)
        .first()
    )
    if not target:
        raise HTTPException(status_code=404, detail=f"Build '{body.to_build_id}' not found for dataset '{dataset_id}'")
    if target.status != "SUCCEEDED":
        raise HTTPException(status_code=422, detail=f"Cannot roll back to build '{body.to_build_id}': status is {target.status}")

    # Determine the current (latest) build to record as the "from" pointer.
    current = _latest_build(db, dataset_id)
    from_build_id = current.id if current else None

    row = LinRollback(
        id=uuid.uuid4().hex,
        dataset_id=dataset_id,
        from_build_id=from_build_id,
        to_build_id=target.id,
        reason=body.reason,
        created_at=int(time.time()),
    )
    db.add(row)
    db.add(models_action.AuditLog(
        id=uuid.uuid4().hex, actor="system",
        event_type="lineage.dataset.rolled_back",
        subject_type="dataset", subject_id=dataset_id,
        payload={"to_build_id": target.id, "from_build_id": from_build_id, "reason": body.reason},
    ))
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "dataset_id": dataset_id,
        "from_build_id": from_build_id,
        "to_build_id": target.id,
        "reason": row.reason,
        "created_at": row.created_at,
        "restored_build": {
            "id": target.id,
            "status": target.status,
            "records_out": target.records_out,
            "completed_at": target.completed_at,
        },
    }


@router.get("/lineage/dataset/{dataset_id}/rollbacks")
def list_rollbacks(dataset_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    rows = db.query(LinRollback).filter(LinRollback.dataset_id == dataset_id).order_by(LinRollback.created_at).all()
    return {
        "dataset_id": dataset_id,
        "rollbacks": [
            {
                "id": r.id,
                "from_build_id": r.from_build_id,
                "to_build_id": r.to_build_id,
                "reason": r.reason,
                "created_at": r.created_at,
            }
            for r in rows
        ],
        "count": len(rows),
    }
