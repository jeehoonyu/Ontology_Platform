"""
Local deterministic DataOps and ModelOps reliability layer.

Provides data contracts, lineage impact analysis, and bounded backfill plans on
top of existing DataAsset, PipelineDefinition, PipelineRun, and lineage APIs.
"""
from __future__ import annotations

import os
import time
import uuid
from collections import Counter, deque
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Boolean, Integer, JSON, String
from sqlalchemy.orm import Mapped, Session, mapped_column

from . import models, models_action
from .database import Base, get_db
from .runtime import execute_pipeline_steps

router = APIRouter(tags=["reliability_ops"])


def _now() -> int:
    return int(time.time())


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class DataQualityContract(Base):
    __tablename__ = "data_quality_contracts"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    display_name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    asset_id: Mapped[str] = mapped_column(String, index=True)
    checks: Mapped[list] = mapped_column(JSON, default=list)
    thresholds: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class DataQualityRun(Base):
    __tablename__ = "data_quality_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    contract_id: Mapped[str] = mapped_column(String, index=True)
    asset_id: Mapped[str] = mapped_column(String, index=True)
    status: Mapped[str] = mapped_column(String, default="PASS", index=True)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    check_results: Mapped[list] = mapped_column(JSON, default=list)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[int] = mapped_column(Integer)


class LineageImpactRun(Base):
    __tablename__ = "lineage_impact_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    resource_kind: Mapped[str] = mapped_column(String, index=True)
    resource_id: Mapped[str] = mapped_column(String, index=True)
    direction: Mapped[str] = mapped_column(String, default="downstream")
    impacted_nodes: Mapped[list] = mapped_column(JSON, default=list)
    impacted_edges: Mapped[list] = mapped_column(JSON, default=list)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[int] = mapped_column(Integer)


class BackfillPlan(Base):
    __tablename__ = "backfill_plans"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    display_name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    pipeline_ids: Mapped[list] = mapped_column(JSON, default=list)
    asset_ids: Mapped[list] = mapped_column(JSON, default=list)
    parameters: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String, default="DRAFT", index=True)
    run_results: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class ReliabilitySnapshot(Base):
    __tablename__ = "reliability_snapshots"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    snapshot_type: Mapped[str] = mapped_column(String, index=True)
    status: Mapped[str] = mapped_column(String, default="PASS", index=True)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[int] = mapped_column(Integer)


class DataQualityContractCreate(BaseModel):
    id: Optional[str] = None
    display_name: str
    description: Optional[str] = None
    asset_id: str
    checks: List[Dict[str, Any]] = Field(default_factory=list)
    thresholds: Dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class DataQualityRunRequest(BaseModel):
    asset_id: Optional[str] = None


class LineageImpactRequest(BaseModel):
    resource_kind: str
    resource_id: str
    direction: str = "downstream"
    max_depth: int = 8


class BackfillPlanCreate(BaseModel):
    id: Optional[str] = None
    display_name: str
    description: Optional[str] = None
    pipeline_ids: List[str] = Field(default_factory=list)
    asset_ids: List[str] = Field(default_factory=list)
    parameters: Dict[str, Any] = Field(default_factory=dict)


class BackfillRunRequest(BaseModel):
    actor: str = "reliability"


def _ensure_tables(db: Session) -> None:
    if os.getenv("APP_ENV", "").strip().lower() == "production":
        return
    for table in (
        DataQualityContract.__table__,
        DataQualityRun.__table__,
        LineageImpactRun.__table__,
        BackfillPlan.__table__,
        ReliabilitySnapshot.__table__,
    ):
        table.create(bind=db.get_bind(), checkfirst=True)


def _audit(db: Session, event_type: str, subject_type: str, subject_id: str, payload: Dict[str, Any]) -> None:
    db.add(models_action.AuditLog(
        id=uuid.uuid4().hex,
        actor="reliability",
        event_type=event_type,
        subject_type=subject_type,
        subject_id=subject_id,
        payload=payload,
    ))


def _contract_dict(contract: DataQualityContract) -> Dict[str, Any]:
    return {
        "id": contract.id,
        "display_name": contract.display_name,
        "description": contract.description,
        "asset_id": contract.asset_id,
        "checks": contract.checks or [],
        "thresholds": contract.thresholds or {},
        "enabled": contract.enabled,
        "created_at": contract.created_at,
        "updated_at": contract.updated_at,
    }


def _run_dict(run: DataQualityRun) -> Dict[str, Any]:
    return {
        "id": run.id,
        "contract_id": run.contract_id,
        "asset_id": run.asset_id,
        "status": run.status,
        "row_count": run.row_count,
        "check_results": run.check_results or [],
        "summary": run.summary or {},
        "created_at": run.created_at,
    }


def _impact_dict(run: LineageImpactRun) -> Dict[str, Any]:
    return {
        "id": run.id,
        "resource_kind": run.resource_kind,
        "resource_id": run.resource_id,
        "direction": run.direction,
        "impacted_nodes": run.impacted_nodes or [],
        "impacted_edges": run.impacted_edges or [],
        "summary": run.summary or {},
        "created_at": run.created_at,
    }


def _backfill_dict(plan: BackfillPlan) -> Dict[str, Any]:
    return {
        "id": plan.id,
        "display_name": plan.display_name,
        "description": plan.description,
        "pipeline_ids": plan.pipeline_ids or [],
        "asset_ids": plan.asset_ids or [],
        "parameters": plan.parameters or {},
        "status": plan.status,
        "run_results": plan.run_results or [],
        "created_at": plan.created_at,
        "updated_at": plan.updated_at,
    }


def _field_values(records: List[Dict[str, Any]], field: str) -> List[Any]:
    return [row.get(field) for row in records if isinstance(row, dict)]


def _type_name(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    if value is None:
        return "null"
    return type(value).__name__


def _parse_time(value: Any) -> Optional[int]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value)
    if isinstance(value, str):
        try:
            text = value.replace("Z", "+00:00")
            return int(datetime.fromisoformat(text).timestamp())
        except ValueError:
            return None
    return None


def _status_from_results(results: List[Dict[str, Any]]) -> str:
    statuses = [result.get("status", "PASS") for result in results]
    if "FAIL" in statuses:
        return "FAIL"
    if "WARN" in statuses:
        return "WARN"
    return "PASS"


def _check_result(check: Dict[str, Any], status: str, message: str, metrics: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "type": check.get("type"),
        "field": check.get("field"),
        "status": status,
        "message": message,
        "metrics": metrics or {},
        "check": check,
    }


def _evaluate_check(check: Dict[str, Any], records: List[Dict[str, Any]]) -> Dict[str, Any]:
    check_type = check.get("type")
    row_count = len(records)
    if check_type == "required_fields":
        fields = check.get("fields") or []
        missing = [field for field in fields if any(field not in row for row in records)]
        return _check_result(check, "FAIL" if missing else "PASS", "missing required fields" if missing else "all required fields present", {"missing_fields": missing})
    if check_type == "type_shape":
        field = check.get("field")
        expected = check.get("expected") or check.get("type_name")
        mismatches = [idx for idx, value in enumerate(_field_values(records, field)) if value is not None and _type_name(value) != expected]
        return _check_result(check, "FAIL" if mismatches else "PASS", "type mismatch" if mismatches else "type shape matched", {"mismatch_count": len(mismatches), "expected": expected})
    if check_type == "range":
        field = check.get("field")
        minimum = check.get("min")
        maximum = check.get("max")
        failures = []
        for idx, value in enumerate(_field_values(records, field)):
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                failures.append(idx)
            elif minimum is not None and value < minimum:
                failures.append(idx)
            elif maximum is not None and value > maximum:
                failures.append(idx)
        return _check_result(check, "FAIL" if failures else "PASS", "range violations" if failures else "range matched", {"violation_count": len(failures)})
    if check_type == "unique":
        field = check.get("field")
        values = [value for value in _field_values(records, field) if value is not None]
        counts = Counter(values)
        duplicates = [value for value, count in counts.items() if count > 1]
        return _check_result(check, "FAIL" if duplicates else "PASS", "duplicates found" if duplicates else "values unique", {"duplicate_count": len(duplicates), "duplicates": duplicates[:20]})
    if check_type == "row_count_bounds":
        minimum = check.get("min")
        maximum = check.get("max")
        failed = (minimum is not None and row_count < minimum) or (maximum is not None and row_count > maximum)
        return _check_result(check, "FAIL" if failed else "PASS", "row count outside bounds" if failed else "row count in bounds", {"row_count": row_count, "min": minimum, "max": maximum})
    if check_type == "missing_rate":
        field = check.get("field")
        maximum = float(check.get("max", 0))
        values = _field_values(records, field)
        missing = sum(1 for value in values if value is None or value == "")
        rate = (missing / row_count) if row_count else 0.0
        return _check_result(check, "FAIL" if rate > maximum else "PASS", "missing rate too high" if rate > maximum else "missing rate accepted", {"missing_rate": round(rate, 4), "missing": missing, "max": maximum})
    if check_type == "categorical_allowed_values":
        field = check.get("field")
        allowed = set(check.get("values") or [])
        bad = [value for value in _field_values(records, field) if value is not None and value not in allowed]
        return _check_result(check, "FAIL" if bad else "PASS", "unexpected categorical values" if bad else "categories accepted", {"unexpected_values": list(dict.fromkeys(bad))[:20]})
    if check_type == "freshness":
        field = check.get("field")
        max_age = int(check.get("max_age_seconds", 86400))
        timestamps = [_parse_time(value) for value in _field_values(records, field)]
        latest = max([ts for ts in timestamps if ts is not None], default=None)
        age = (_now() - latest) if latest is not None else None
        failed = age is None or age > max_age
        return _check_result(check, "FAIL" if failed else "PASS", "data is stale" if failed else "freshness accepted", {"latest": latest, "age_seconds": age, "max_age_seconds": max_age})
    return _check_result(check, "WARN", f"unsupported check type '{check_type}'", {})


def run_data_contract_inline(db: Session, *, contract_id: str, asset_id: Optional[str] = None) -> Dict[str, Any]:
    _ensure_tables(db)
    contract = db.get(DataQualityContract, contract_id)
    if not contract:
        raise HTTPException(status_code=404, detail=f"DataQualityContract '{contract_id}' not found")
    if not contract.enabled:
        raise HTTPException(status_code=409, detail="DataQualityContract is disabled")
    target_asset_id = asset_id or contract.asset_id
    asset = db.get(models.DataAsset, target_asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail=f"DataAsset '{target_asset_id}' not found")
    records = [dict(row) for row in (asset.records or []) if isinstance(row, dict)]
    results = [_evaluate_check(check, records) for check in contract.checks or []]
    status = _status_from_results(results)
    summary = {
        "checks": len(results),
        "passed": sum(1 for item in results if item["status"] == "PASS"),
        "warned": sum(1 for item in results if item["status"] == "WARN"),
        "failed": sum(1 for item in results if item["status"] == "FAIL"),
    }
    run = DataQualityRun(
        id=_new_id("dq_run"),
        contract_id=contract.id,
        asset_id=asset.id,
        status=status,
        row_count=len(records),
        check_results=results,
        summary=summary,
        created_at=_now(),
    )
    db.add(run)
    _audit(db, "reliability.data_contract.run", "data_quality_contract", contract.id, {"run_id": run.id, "status": status, "asset_id": asset.id})
    try:
        from . import ops_control
        ops_control.record_ops_event(
            db,
            source="data_contract",
            event_type="data_contract.run",
            severity="high" if status == "FAIL" else "medium" if status == "WARN" else "info",
            title=f"Data contract {contract.display_name} {status}",
            subject_type="data_quality_contract",
            subject_id=contract.id,
            payload={"run_id": run.id, "asset_id": asset.id, "status": status, "summary": summary},
        )
    except Exception:
        pass
    return _run_dict(run)


def analyze_lineage_impact_inline(
    db: Session,
    *,
    resource_kind: str,
    resource_id: str,
    direction: str = "downstream",
    max_depth: int = 8,
) -> Dict[str, Any]:
    _ensure_tables(db)
    from .lineage import _assemble_graph

    graph = _assemble_graph(db)
    nodes = {node.id: node.model_dump() for node in graph.nodes}
    if resource_id not in nodes:
        raise HTTPException(status_code=404, detail=f"{resource_kind} '{resource_id}' not found in lineage graph")
    forward: Dict[str, List[Dict[str, Any]]] = {}
    backward: Dict[str, List[Dict[str, Any]]] = {}
    for edge in graph.edges:
        edge_dict = edge.model_dump()
        forward.setdefault(edge.source, []).append(edge_dict)
        backward.setdefault(edge.target, []).append(edge_dict)
    use_edges = backward if direction == "upstream" else forward
    seen = {resource_id}
    impacted_edges: List[Dict[str, Any]] = []
    queue = deque([(resource_id, 0)])
    while queue:
        current, depth = queue.popleft()
        if depth >= max_depth:
            continue
        for edge in use_edges.get(current, []):
            nxt = edge["source"] if direction == "upstream" else edge["target"]
            impacted_edges.append(edge)
            if nxt not in seen:
                seen.add(nxt)
                queue.append((nxt, depth + 1))
    impacted_nodes = [nodes[node_id] for node_id in seen if node_id != resource_id and node_id in nodes]
    by_kind = Counter(node["kind"] for node in impacted_nodes)
    summary = {"node_count": len(impacted_nodes), "edge_count": len(impacted_edges), "by_kind": dict(by_kind)}
    run = LineageImpactRun(
        id=_new_id("impact"),
        resource_kind=resource_kind,
        resource_id=resource_id,
        direction=direction,
        impacted_nodes=impacted_nodes,
        impacted_edges=impacted_edges,
        summary=summary,
        created_at=_now(),
    )
    db.add(run)
    _audit(db, "reliability.lineage_impact.analyzed", "lineage_impact_run", run.id, summary)
    return _impact_dict(run)


def _run_pipeline_backfill(db: Session, pipeline: models.PipelineDefinition, actor: str) -> Dict[str, Any]:
    input_asset = db.get(models.DataAsset, pipeline.input_asset_id)
    if not input_asset:
        return {"pipeline_id": pipeline.id, "status": "FAILED", "error": f"Input asset '{pipeline.input_asset_id}' not found"}
    if input_asset.project_id != pipeline.project_id:
        return {"pipeline_id": pipeline.id, "status": "FAILED", "error": "Pipeline input belongs to another project"}
    now = _now()
    run = models.PipelineRun(
        id=str(uuid.uuid4()),
        project_id=pipeline.project_id,
        pipeline_id=pipeline.id,
        status="RUNNING",
        input_asset_id=input_asset.id,
        output_asset_id=pipeline.output_asset_id,
        records_in=len(input_asset.records or []),
        records_out=0,
        lineage={},
        metrics={},
        created_at=now,
    )
    db.add(run)
    try:
        output_records, lineage, metrics = execute_pipeline_steps(db, pipeline=pipeline, run_id=run.id, input_asset=input_asset)
        output_asset_id = pipeline.output_asset_id or f"{pipeline.id}_output"
        output_asset = db.get(models.DataAsset, output_asset_id)
        if output_asset and output_asset.project_id != pipeline.project_id:
            raise HTTPException(status_code=409, detail="Pipeline output belongs to another project")
        if not output_asset:
            output_asset = models.DataAsset(
                id=output_asset_id,
                project_id=pipeline.project_id,
                display_name=f"{pipeline.display_name} Output",
                description=f"Backfill output of pipeline {pipeline.id}",
                kind="dataset",
                asset_schema={"project_id": pipeline.project_id},
                records=[],
                created_at=now,
                updated_at=now,
            )
            db.add(output_asset)
        output_asset.records = output_records
        output_asset.updated_at = _now()
        run.status = "SUCCESS"
        run.output_asset_id = output_asset.id
        run.records_out = len(output_records)
        run.lineage = lineage
        run.metrics = metrics
        run.completed_at = _now()
        _audit(db, "reliability.backfill.pipeline.completed", "pipeline_run", run.id, {"pipeline_id": pipeline.id, "records_out": len(output_records), "actor": actor})
        return {"pipeline_id": pipeline.id, "run_id": run.id, "status": "SUCCESS", "records_out": len(output_records), "output_asset_id": output_asset.id}
    except Exception as exc:
        run.status = "FAILED"
        run.error = str(exc)
        run.completed_at = _now()
        _audit(db, "reliability.backfill.pipeline.failed", "pipeline_run", run.id, {"pipeline_id": pipeline.id, "error": str(exc), "actor": actor})
        return {"pipeline_id": pipeline.id, "run_id": run.id, "status": "FAILED", "error": str(exc)}


@router.post("/reliability/data-contracts")
def create_data_contract(body: DataQualityContractCreate, db: Session = Depends(get_db)):
    _ensure_tables(db)
    if not db.get(models.DataAsset, body.asset_id):
        raise HTTPException(status_code=404, detail=f"DataAsset '{body.asset_id}' not found")
    contract_id = body.id or _new_id("dq_contract")
    if db.get(DataQualityContract, contract_id):
        raise HTTPException(status_code=400, detail="DataQualityContract already exists")
    now = _now()
    contract = DataQualityContract(id=contract_id, created_at=now, updated_at=now, **body.model_dump(exclude={"id"}))
    db.add(contract)
    _audit(db, "reliability.data_contract.created", "data_quality_contract", contract.id, _contract_dict(contract))
    db.commit()
    db.refresh(contract)
    return _contract_dict(contract)


@router.get("/reliability/data-contracts")
def list_data_contracts(db: Session = Depends(get_db)):
    _ensure_tables(db)
    latest = {
        run.contract_id: run
        for run in db.query(DataQualityRun).order_by(DataQualityRun.created_at.asc()).all()
    }
    return [
        {**_contract_dict(contract), "latest_run": _run_dict(latest[contract.id]) if contract.id in latest else None}
        for contract in db.query(DataQualityContract).order_by(DataQualityContract.updated_at.desc()).all()
    ]


@router.post("/reliability/data-contracts/{contract_id}/run")
def run_data_contract(contract_id: str, body: DataQualityRunRequest = DataQualityRunRequest(), db: Session = Depends(get_db)):
    result = run_data_contract_inline(db, contract_id=contract_id, asset_id=body.asset_id)
    db.commit()
    return result


@router.get("/reliability/data-contracts/{contract_id}/runs")
def list_data_contract_runs(contract_id: str, db: Session = Depends(get_db)):
    _ensure_tables(db)
    if not db.get(DataQualityContract, contract_id):
        raise HTTPException(status_code=404, detail=f"DataQualityContract '{contract_id}' not found")
    return [
        _run_dict(run)
        for run in db.query(DataQualityRun).filter(DataQualityRun.contract_id == contract_id).order_by(DataQualityRun.created_at.desc()).all()
    ]


@router.post("/reliability/lineage-impact")
def analyze_lineage_impact(body: LineageImpactRequest, db: Session = Depends(get_db)):
    result = analyze_lineage_impact_inline(
        db,
        resource_kind=body.resource_kind,
        resource_id=body.resource_id,
        direction=body.direction,
        max_depth=body.max_depth,
    )
    db.commit()
    return result


@router.post("/reliability/backfills")
def create_backfill(body: BackfillPlanCreate, db: Session = Depends(get_db)):
    _ensure_tables(db)
    plan_id = body.id or _new_id("backfill")
    if db.get(BackfillPlan, plan_id):
        raise HTTPException(status_code=400, detail="BackfillPlan already exists")
    for pipeline_id in body.pipeline_ids:
        if not db.get(models.PipelineDefinition, pipeline_id):
            raise HTTPException(status_code=404, detail=f"PipelineDefinition '{pipeline_id}' not found")
    now = _now()
    plan = BackfillPlan(id=plan_id, status="DRAFT", run_results=[], created_at=now, updated_at=now, **body.model_dump(exclude={"id"}))
    db.add(plan)
    _audit(db, "reliability.backfill.created", "backfill_plan", plan.id, _backfill_dict(plan))
    db.commit()
    db.refresh(plan)
    return _backfill_dict(plan)


@router.get("/reliability/backfills")
def list_backfills(db: Session = Depends(get_db)):
    _ensure_tables(db)
    return [_backfill_dict(plan) for plan in db.query(BackfillPlan).order_by(BackfillPlan.updated_at.desc()).all()]


@router.post("/reliability/backfills/{backfill_id}/run")
def run_backfill(backfill_id: str, body: BackfillRunRequest = BackfillRunRequest(), db: Session = Depends(get_db)):
    plan = db.get(BackfillPlan, backfill_id)
    if not plan:
        raise HTTPException(status_code=404, detail=f"BackfillPlan '{backfill_id}' not found")
    results = []
    for pipeline_id in plan.pipeline_ids or []:
        pipeline = db.get(models.PipelineDefinition, pipeline_id)
        if pipeline:
            results.append(_run_pipeline_backfill(db, pipeline, body.actor))
        else:
            results.append({"pipeline_id": pipeline_id, "status": "FAILED", "error": "pipeline missing"})
    plan.run_results = results
    plan.status = "FAILED" if any(result.get("status") == "FAILED" for result in results) else "SUCCESS"
    plan.updated_at = _now()
    _audit(db, "reliability.backfill.ran", "backfill_plan", plan.id, {"status": plan.status, "results": results})
    try:
        from . import ops_control
        ops_control.record_ops_event(
            db,
            source="backfill",
            event_type="backfill.ran",
            severity="high" if plan.status == "FAILED" else "info",
            title=f"Backfill {plan.display_name} {plan.status}",
            subject_type="backfill_plan",
            subject_id=plan.id,
            payload={"results": results},
        )
    except Exception:
        pass
    db.commit()
    db.refresh(plan)
    return _backfill_dict(plan)


@router.get("/reliability/summary")
def reliability_summary(db: Session = Depends(get_db)):
    _ensure_tables(db)
    latest_contract_runs = db.query(DataQualityRun).order_by(DataQualityRun.created_at.desc()).limit(25).all()
    status_counts = Counter(run.status for run in latest_contract_runs)
    latest_backfills = db.query(BackfillPlan).order_by(BackfillPlan.updated_at.desc()).limit(10).all()
    latest_impacts = db.query(LineageImpactRun).order_by(LineageImpactRun.created_at.desc()).limit(10).all()
    snapshot = ReliabilitySnapshot(
        id=_new_id("rel_snap"),
        snapshot_type="summary",
        status="FAIL" if status_counts.get("FAIL") else "WARN" if status_counts.get("WARN") else "PASS",
        metrics={
            "data_contracts": db.query(DataQualityContract).count(),
            "latest_contract_status": dict(status_counts),
            "backfills": db.query(BackfillPlan).count(),
            "lineage_impact_runs": db.query(LineageImpactRun).count(),
        },
        created_at=_now(),
    )
    db.add(snapshot)
    db.commit()
    return {
        **snapshot.metrics,
        "status": snapshot.status,
        "latest_contract_runs": [_run_dict(run) for run in latest_contract_runs[:8]],
        "latest_backfills": [_backfill_dict(plan) for plan in latest_backfills],
        "latest_impacts": [_impact_dict(run) for run in latest_impacts],
    }
