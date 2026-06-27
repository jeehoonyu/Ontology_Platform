"""
Marketplace — declared dependencies, validated dependency-resolved install &
upgrade diff (deep-fidelity pass 10). Based on /docs/foundry/marketplace/install-product:
products declare required inputs; installation maps them to local resources;
validation surfaces missing/unresolved inputs before install; install creates the
content portfolio (with optional prefix/suffix); upgrades apply a new release.
Additive; deterministic; local.
"""
import time
import uuid
from typing import Optional, List, Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import String, Integer, Boolean, JSON
from sqlalchemy.orm import Mapped, mapped_column, Session
from pydantic import BaseModel, Field

from .database import Base, get_db
from . import models, models_action, marketplace as _mkt

router = APIRouter(tags=["marketplace_ops"])


def _now() -> int:
    return int(time.time())


class ProductRequirement(Base):
    __tablename__ = "product_requirements"
    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    product_id: Mapped[str] = mapped_column(String, index=True)
    key: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String, default="dataset")  # dataset/source/object_type
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[int] = mapped_column(Integer)


class ReleaseSnapshot(Base):
    __tablename__ = "release_snapshots"
    release_id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    product_id: Mapped[str] = mapped_column(String, index=True)
    version: Mapped[str] = mapped_column(String)
    resources: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[int] = mapped_column(Integer)


class ProductPort(Base):
    """Explicit INPUT vs OUTPUT of a DevOps product.

    Outputs are resources Marketplace recreates on install; inputs are upstream
    dependencies installers must map to their own resources. Foundry DevOps derives
    inputs automatically from the upstream resources of an output; an input may later
    be promoted to an output (so the product ships that resource itself).
    """
    __tablename__ = "product_ports"
    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    product_id: Mapped[str] = mapped_column(String, index=True)
    port_type: Mapped[str] = mapped_column(String, index=True)  # input | output
    kind: Mapped[str] = mapped_column(String, default="dataset")  # dataset/source/object_type
    resource_id: Mapped[str] = mapped_column(String)
    # auto-derived inputs are flagged so promotion / re-derivation can distinguish them
    derived: Mapped[bool] = mapped_column(Boolean, default=False)
    derived_from: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[int] = mapped_column(Integer)


# ---------------------------------------------------------------------------
class RequirementCreate(BaseModel):
    key: str
    kind: str = "dataset"
    required: bool = True


class ValidateInstallRequest(BaseModel):
    input_mappings: Dict[str, str] = Field(default_factory=dict)


class InstallResolvedRequest(BaseModel):
    target_project: str
    input_mappings: Dict[str, str] = Field(default_factory=dict)
    release_id: Optional[str] = None
    prefix: Optional[str] = None
    suffix: Optional[str] = None


class UpgradeDiffRequest(BaseModel):
    from_release_id: str
    to_release_id: str


class OutputCreate(BaseModel):
    kind: str = "dataset"  # dataset/source/object_type
    resource_id: str


class InputCreate(BaseModel):
    kind: str = "dataset"
    resource_id: str
    required: bool = True


def _require_product(db: Session, product_id: str):
    p = db.get(_mkt.DevopsProduct, product_id)
    if not p:
        raise HTTPException(status_code=404, detail=f"Product '{product_id}' not found")
    return p


def _resource_exists(db: Session, kind: str, rid: str) -> bool:
    if kind in ("dataset", "source"):
        return db.get(models.DataAsset, rid) is not None
    if kind == "object_type":
        return db.get(models.ObjectType, rid) is not None
    return True


def _upstream_inputs(db: Session, kind: str, resource_id: str) -> List[Dict[str, str]]:
    """Derive the upstream dependencies of a single output resource.

    Lineage sources in this implementation:
      - PipelineDefinition: output_asset_id <- input_asset_id
      - DataAsset.source_asset_id chain
      - object_type outputs: source_asset_id of materialized ObjectInstances
    Returns a list of {kind, resource_id} dependency descriptors (the output itself
    is never returned as its own upstream).
    """
    upstreams: List[Dict[str, str]] = []
    seen = set()

    def _add(k: str, rid: str):
        if not rid or rid == resource_id:
            return
        sig = (k, rid)
        if sig in seen:
            return
        seen.add(sig)
        upstreams.append({"kind": k, "resource_id": rid})

    if kind in ("dataset", "source"):
        # pipelines that produce this dataset declare their inputs upstream
        for pipe in (
            db.query(models.PipelineDefinition)
            .filter(models.PipelineDefinition.output_asset_id == resource_id)
            .all()
        ):
            if pipe.input_asset_id:
                _add("dataset", pipe.input_asset_id)
        # direct source-asset lineage on the DataAsset row
        asset = db.get(models.DataAsset, resource_id)
        if asset is not None and getattr(asset, "source_asset_id", None):
            _add("dataset", asset.source_asset_id)
    elif kind == "object_type":
        # ontology objects are hydrated from a source dataset
        for inst in (
            db.query(models.ObjectInstance)
            .filter(models.ObjectInstance.object_type_id == resource_id)
            .all()
        ):
            if getattr(inst, "source_asset_id", None):
                _add("dataset", inst.source_asset_id)
    return upstreams


# ---------------------------------------------------------------------------
@router.post("/devops/products/{product_id}/requirements", status_code=201)
def add_requirement(product_id: str, body: RequirementCreate, db: Session = Depends(get_db)):
    _require_product(db, product_id)
    req = ProductRequirement(id=uuid.uuid4().hex, product_id=product_id, key=body.key,
                             kind=body.kind, required=body.required, created_at=_now())
    db.add(req); db.commit()
    return {"id": req.id, "product_id": product_id, "key": body.key, "kind": body.kind, "required": body.required}


@router.get("/devops/products/{product_id}/requirements")
def list_requirements(product_id: str, db: Session = Depends(get_db)):
    rows = db.query(ProductRequirement).filter(ProductRequirement.product_id == product_id).all()
    return [{"key": r.key, "kind": r.kind, "required": r.required} for r in rows]


def _validate(db: Session, product_id: str, input_mappings: Dict[str, str]):
    reqs = db.query(ProductRequirement).filter(ProductRequirement.product_id == product_id).all()
    missing, unresolved, resolved = [], [], []
    for r in reqs:
        if r.required and r.key not in input_mappings:
            missing.append(r.key)
            continue
        if r.key in input_mappings:
            mapped = input_mappings[r.key]
            exists = _resource_exists(db, r.kind, mapped)
            entry = {"key": r.key, "kind": r.kind, "mapped_to": mapped, "exists": exists}
            (resolved if exists else unresolved).append(entry)
    return missing, unresolved, resolved


@router.post("/marketplace/{product_id}/validate-install")
def validate_install(product_id: str, body: ValidateInstallRequest, db: Session = Depends(get_db)):
    _require_product(db, product_id)
    missing, unresolved, resolved = _validate(db, product_id, body.input_mappings)
    return {"product_id": product_id, "valid": not missing and not unresolved,
            "missing_inputs": missing, "unresolved_inputs": unresolved, "resolved_inputs": resolved}


@router.post("/marketplace/{product_id}/install-resolved", status_code=201)
def install_resolved(product_id: str, body: InstallResolvedRequest, db: Session = Depends(get_db)):
    product = _require_product(db, product_id)
    missing, unresolved, resolved = _validate(db, product_id, body.input_mappings)
    if missing or unresolved:
        raise HTTPException(status_code=422, detail={"missing_inputs": missing, "unresolved_inputs": unresolved})

    # pick release (explicit or latest)
    release_id = body.release_id
    if not release_id:
        latest = (db.query(_mkt.ProductRelease).filter(_mkt.ProductRelease.product_id == product_id)
                  .order_by(_mkt.ProductRelease.created_at.desc()).first())
        release_id = latest.id if latest else None

    # build created-content manifest with prefix/suffix applied
    created = []
    for res in (product.resources or []):
        name = res.get("id")
        final = name
        if body.prefix and res.get("kind") in ("object_type", "action_type", "link_type"):
            final = f"{body.prefix}{name}"
        created.append({"kind": res.get("kind"), "source_id": name, "installed_as": final})

    now = _now()
    inst = _mkt.ProductInstallation(
        id=uuid.uuid4().hex, product_id=product_id, release_id=release_id or "unversioned",
        target_project=body.target_project + (body.suffix or ""), status="installed",
        input_mappings=body.input_mappings, created_at=now, updated_at=now)
    db.add(inst)
    db.add(models_action.AuditLog(id=uuid.uuid4().hex, actor="system", event_type="marketplace.installed",
                                  subject_type="product", subject_id=product_id,
                                  payload={"target": inst.target_project, "resolved": len(resolved)}))
    db.commit()
    return {"installation_id": inst.id, "product_id": product_id, "release_id": release_id,
            "target_project": inst.target_project, "resolved_inputs": resolved, "created_content": created}


@router.post("/devops/products/{product_id}/releases/{release_id}/snapshot", status_code=201)
def snapshot_release(product_id: str, release_id: str, db: Session = Depends(get_db)):
    product = _require_product(db, product_id)
    rel = db.get(_mkt.ProductRelease, release_id)
    if not rel:
        raise HTTPException(status_code=404, detail=f"Release '{release_id}' not found")
    snap = db.get(ReleaseSnapshot, release_id)
    if snap:
        snap.resources = list(product.resources or [])
        snap.version = rel.version
    else:
        snap = ReleaseSnapshot(release_id=release_id, product_id=product_id, version=rel.version,
                               resources=list(product.resources or []), created_at=_now())
        db.add(snap)
    db.commit()
    return {"release_id": release_id, "version": rel.version, "resource_count": len(product.resources or [])}


@router.post("/marketplace/upgrade-diff")
def upgrade_diff(body: UpgradeDiffRequest, db: Session = Depends(get_db)):
    a = db.get(ReleaseSnapshot, body.from_release_id)
    b = db.get(ReleaseSnapshot, body.to_release_id)
    if not a or not b:
        raise HTTPException(status_code=404, detail="both releases must be snapshotted first")
    a_ids = {r.get("id") for r in a.resources}
    b_ids = {r.get("id") for r in b.resources}
    return {"from_version": a.version, "to_version": b.version,
            "added": sorted(b_ids - a_ids), "removed": sorted(a_ids - b_ids),
            "unchanged": sorted(a_ids & b_ids)}


# ---------------------------------------------------------------------------
# Product INPUTS vs OUTPUTS (explicit ports + upstream derivation + promotion)
# ---------------------------------------------------------------------------
def _port_dict(p: ProductPort) -> Dict[str, Any]:
    return {
        "id": p.id, "product_id": p.product_id, "port_type": p.port_type,
        "kind": p.kind, "resource_id": p.resource_id, "required": p.required,
        "derived": p.derived, "derived_from": p.derived_from,
    }


@router.post("/devops/products/{product_id}/outputs", status_code=201)
def add_output(product_id: str, body: OutputCreate, db: Session = Depends(get_db)):
    """Add an OUTPUT (a resource the product ships and recreates on install)."""
    _require_product(db, product_id)
    existing = (
        db.query(ProductPort)
        .filter(ProductPort.product_id == product_id, ProductPort.port_type == "output",
                ProductPort.resource_id == body.resource_id)
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="output already declared")
    port = ProductPort(id=uuid.uuid4().hex, product_id=product_id, port_type="output",
                       kind=body.kind, resource_id=body.resource_id, required=False,
                       derived=False, created_at=_now())
    db.add(port)
    db.add(models_action.AuditLog(id=uuid.uuid4().hex, actor="system",
                                  event_type="marketplace.output.added", subject_type="product",
                                  subject_id=product_id,
                                  payload={"kind": body.kind, "resource_id": body.resource_id}))
    db.commit()
    return _port_dict(port)


@router.post("/devops/products/{product_id}/inputs", status_code=201)
def add_input(product_id: str, body: InputCreate, db: Session = Depends(get_db)):
    """Manually declare an INPUT (a dependency installers must map)."""
    _require_product(db, product_id)
    existing = (
        db.query(ProductPort)
        .filter(ProductPort.product_id == product_id, ProductPort.port_type == "input",
                ProductPort.resource_id == body.resource_id)
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="input already declared")
    port = ProductPort(id=uuid.uuid4().hex, product_id=product_id, port_type="input",
                       kind=body.kind, resource_id=body.resource_id, required=body.required,
                       derived=False, created_at=_now())
    db.add(port)
    db.commit()
    return _port_dict(port)


@router.get("/devops/products/{product_id}/ports")
def list_ports(product_id: str, db: Session = Depends(get_db)):
    """List explicit inputs and outputs for a product."""
    _require_product(db, product_id)
    rows = db.query(ProductPort).filter(ProductPort.product_id == product_id).all()
    return {
        "product_id": product_id,
        "inputs": [_port_dict(p) for p in rows if p.port_type == "input"],
        "outputs": [_port_dict(p) for p in rows if p.port_type == "output"],
    }


@router.post("/devops/products/{product_id}/derive-inputs", status_code=201)
def derive_inputs(product_id: str, db: Session = Depends(get_db)):
    """Derive INPUTS from the upstream dependencies of declared OUTPUTS.

    Foundry DevOps automatically surfaces output dependencies as inputs. An upstream
    resource that is itself an output of this product is NOT surfaced as an input.
    Existing derived inputs are recomputed; manual inputs are preserved.
    """
    _require_product(db, product_id)
    outputs = (
        db.query(ProductPort)
        .filter(ProductPort.product_id == product_id, ProductPort.port_type == "output")
        .all()
    )
    output_ids = {o.resource_id for o in outputs}

    # clear previously-derived inputs (keep manual inputs intact)
    for stale in (
        db.query(ProductPort)
        .filter(ProductPort.product_id == product_id, ProductPort.port_type == "input",
                ProductPort.derived == True)  # noqa: E712
        .all()
    ):
        db.delete(stale)

    existing_input_ids = {
        p.resource_id for p in db.query(ProductPort)
        .filter(ProductPort.product_id == product_id, ProductPort.port_type == "input",
                ProductPort.derived == False)  # noqa: E712
        .all()
    }

    created: List[Dict[str, Any]] = []
    seen = set()
    for out in outputs:
        for dep in _upstream_inputs(db, out.kind, out.resource_id):
            rid = dep["resource_id"]
            # skip deps that the product already ships as an output, or already an input
            if rid in output_ids or rid in existing_input_ids or rid in seen:
                continue
            seen.add(rid)
            port = ProductPort(id=uuid.uuid4().hex, product_id=product_id, port_type="input",
                               kind=dep["kind"], resource_id=rid, required=True,
                               derived=True, derived_from=out.resource_id, created_at=_now())
            db.add(port)
            created.append(_port_dict(port))
    db.add(models_action.AuditLog(id=uuid.uuid4().hex, actor="system",
                                  event_type="marketplace.inputs.derived", subject_type="product",
                                  subject_id=product_id, payload={"derived_count": len(created)}))
    db.commit()
    return {"product_id": product_id, "derived_inputs": created, "derived_count": len(created)}


@router.post("/devops/products/{product_id}/inputs/{resource_id}/promote", status_code=200)
def promote_input_to_output(product_id: str, resource_id: str, db: Session = Depends(get_db)):
    """Promote an INPUT to an OUTPUT (the product ships it instead of requiring it)."""
    _require_product(db, product_id)
    port = (
        db.query(ProductPort)
        .filter(ProductPort.product_id == product_id, ProductPort.port_type == "input",
                ProductPort.resource_id == resource_id)
        .first()
    )
    if not port:
        raise HTTPException(status_code=404, detail=f"input '{resource_id}' not found")
    already = (
        db.query(ProductPort)
        .filter(ProductPort.product_id == product_id, ProductPort.port_type == "output",
                ProductPort.resource_id == resource_id)
        .first()
    )
    if already:
        db.delete(port)
        db.commit()
        return _port_dict(already)
    port.port_type = "output"
    port.required = False
    port.derived = False
    port.derived_from = None
    db.add(models_action.AuditLog(id=uuid.uuid4().hex, actor="system",
                                  event_type="marketplace.input.promoted", subject_type="product",
                                  subject_id=product_id,
                                  payload={"resource_id": resource_id, "kind": port.kind}))
    db.commit()
    return _port_dict(port)
