"""
lineage.py — Read-only cross-resource data lineage graph.

Builds nodes/edges from existing tables:
  - models.DataAsset        → "dataset" nodes
  - models.PipelineDefinition → "pipeline" nodes; edges asset→pipeline and pipeline→output_asset
  - models.PipelineRun      → provides the latest run status for each pipeline node
  - models.ObjectInstance   → via source_asset_id, edges dataset→object_type
  - models.ObjectType       → "object_type" nodes (only those referenced by instances)

No new tables are created. All operations are read-only queries.
"""

from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from .database import get_db
from . import models

router = APIRouter(tags=["lineage"])


# ---------------------------------------------------------------------------
# Pydantic schemas (inline, read-only — no mutations)
# ---------------------------------------------------------------------------

class LineageNode(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: str           # "dataset" | "pipeline" | "object_type"
    label: str
    status: Optional[str] = None   # pipeline run status if available


class LineageEdge(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source: str
    target: str
    kind: str           # "feeds" | "produces" | "hydrates"


class LineageGraphResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    nodes: List[LineageNode]
    edges: List[LineageEdge]
    node_count: int
    edge_count: int


class LineageResourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    resource_kind: str
    resource_id: str
    resource_label: str
    upstream: List[Dict[str, Any]]
    downstream: List[Dict[str, Any]]


# ---------------------------------------------------------------------------
# Internal graph assembly helper
# ---------------------------------------------------------------------------

def _assemble_graph(db: Session) -> LineageGraphResponse:
    """
    Build the full lineage graph deterministically from existing tables.

    Node kinds:
      "dataset"     — every DataAsset row
      "pipeline"    — every PipelineDefinition row
      "object_type" — ObjectType rows referenced by at least one ObjectInstance
                      that has a non-null source_asset_id

    Edge kinds:
      "feeds"    — DataAsset(input_asset_id) → PipelineDefinition
      "produces" — PipelineDefinition → DataAsset(output_asset_id)
      "hydrates" — DataAsset → ObjectType
                   (derived from ObjectInstance.source_asset_id grouped by object_type_id)
    """
    nodes: List[LineageNode] = []
    edges: List[LineageEdge] = []

    # Track which node ids we have already added (deduplication)
    seen_node_ids: set = set()

    # --- Dataset nodes ---
    assets = db.query(models.DataAsset).all()
    asset_ids = {a.id for a in assets}
    for asset in assets:
        if asset.id not in seen_node_ids:
            nodes.append(LineageNode(
                id=asset.id,
                kind="dataset",
                label=asset.display_name or asset.id,
            ))
            seen_node_ids.add(asset.id)

    # --- Latest run status per pipeline (for status field on pipeline node) ---
    pipeline_run_status: Dict[str, str] = {}
    runs = (
        db.query(models.PipelineRun)
        .order_by(models.PipelineRun.created_at.desc())
        .all()
    )
    for run in runs:
        # Keep only the most-recent run per pipeline (list is desc-ordered)
        if run.pipeline_id not in pipeline_run_status:
            pipeline_run_status[run.pipeline_id] = run.status

    # --- Pipeline nodes + feed/produce edges ---
    pipelines = db.query(models.PipelineDefinition).all()
    pipeline_ids = {p.id for p in pipelines}
    for pipeline in pipelines:
        if pipeline.id not in seen_node_ids:
            nodes.append(LineageNode(
                id=pipeline.id,
                kind="pipeline",
                label=pipeline.display_name or pipeline.id,
                status=pipeline_run_status.get(pipeline.id),
            ))
            seen_node_ids.add(pipeline.id)

        # edge: input_asset → pipeline  (kind="feeds")
        if pipeline.input_asset_id and pipeline.input_asset_id in asset_ids:
            edges.append(LineageEdge(
                source=pipeline.input_asset_id,
                target=pipeline.id,
                kind="feeds",
            ))

        # edge: pipeline → output_asset  (kind="produces")
        if pipeline.output_asset_id and pipeline.output_asset_id in asset_ids:
            edges.append(LineageEdge(
                source=pipeline.id,
                target=pipeline.output_asset_id,
                kind="produces",
            ))

    # --- ObjectType nodes + hydrates edges via ObjectInstance.source_asset_id ---
    # Collect (source_asset_id, object_type_id) pairs that exist
    instances_with_source = (
        db.query(
            models.ObjectInstance.source_asset_id,
            models.ObjectInstance.object_type_id,
        )
        .filter(models.ObjectInstance.source_asset_id.isnot(None))
        .distinct()
        .all()
    )

    # Gather referenced object_type_ids
    referenced_ot_ids = {row.object_type_id for row in instances_with_source}

    # Fetch only the needed ObjectType rows
    if referenced_ot_ids:
        object_types = (
            db.query(models.ObjectType)
            .filter(models.ObjectType.id.in_(referenced_ot_ids))
            .all()
        )
    else:
        object_types = []

    ot_id_to_label = {ot.id: (ot.display_name or ot.id) for ot in object_types}

    for ot in object_types:
        if ot.id not in seen_node_ids:
            nodes.append(LineageNode(
                id=ot.id,
                kind="object_type",
                label=ot.display_name or ot.id,
            ))
            seen_node_ids.add(ot.id)

    # Build "hydrates" edges; dedup by (source_asset_id, object_type_id)
    seen_hydrates: set = set()
    for row in instances_with_source:
        key = (row.source_asset_id, row.object_type_id)
        if key in seen_hydrates:
            continue
        seen_hydrates.add(key)

        # Only emit the edge if the source asset is in our node set
        if row.source_asset_id in asset_ids and row.object_type_id in ot_id_to_label:
            edges.append(LineageEdge(
                source=row.source_asset_id,
                target=row.object_type_id,
                kind="hydrates",
            ))

    return LineageGraphResponse(
        nodes=nodes,
        edges=edges,
        node_count=len(nodes),
        edge_count=len(edges),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/lineage/graph", response_model=LineageGraphResponse)
def get_lineage_graph(db: Session = Depends(get_db)) -> LineageGraphResponse:
    """
    Return the full cross-resource data lineage graph assembled from existing
    DataAsset, PipelineDefinition, PipelineRun, ObjectInstance, and ObjectType
    rows.  No writes are performed.
    """
    return _assemble_graph(db)


@router.get("/lineage/resource/{kind}/{resource_id}", response_model=LineageResourceResponse)
def get_resource_lineage(
    kind: str,
    resource_id: str,
    db: Session = Depends(get_db),
) -> LineageResourceResponse:
    """
    Return immediate upstream and downstream neighbours for a specific resource.

    Supported kinds: "dataset", "pipeline", "object_type"

    Upstream   = nodes that have an outbound edge pointing TO this resource.
    Downstream = nodes that this resource has an outbound edge pointing TO.
    """
    valid_kinds = {"dataset", "pipeline", "object_type"}
    if kind not in valid_kinds:
        raise HTTPException(
            status_code=422,
            detail=f"kind must be one of: {sorted(valid_kinds)}",
        )

    graph = _assemble_graph(db)

    # Verify the requested node exists in the graph
    node_map: Dict[str, LineageNode] = {n.id: n for n in graph.nodes}
    if resource_id not in node_map:
        raise HTTPException(
            status_code=404,
            detail=f"{kind} '{resource_id}' not found in lineage graph",
        )

    node = node_map[resource_id]

    # Walk edges for upstream (edges whose target == resource_id)
    upstream: List[Dict[str, Any]] = []
    for edge in graph.edges:
        if edge.target == resource_id:
            src_node = node_map.get(edge.source)
            upstream.append({
                "id": edge.source,
                "kind": src_node.kind if src_node else "unknown",
                "label": src_node.label if src_node else edge.source,
                "edge_kind": edge.kind,
            })

    # Walk edges for downstream (edges whose source == resource_id)
    downstream: List[Dict[str, Any]] = []
    for edge in graph.edges:
        if edge.source == resource_id:
            tgt_node = node_map.get(edge.target)
            downstream.append({
                "id": edge.target,
                "kind": tgt_node.kind if tgt_node else "unknown",
                "label": tgt_node.label if tgt_node else edge.target,
                "edge_kind": edge.kind,
            })

    return LineageResourceResponse(
        resource_kind=node.kind,
        resource_id=resource_id,
        resource_label=node.label,
        upstream=upstream,
        downstream=downstream,
    )
