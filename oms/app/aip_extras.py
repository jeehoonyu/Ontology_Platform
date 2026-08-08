"""
AIP EXTRAS module:
  - MODEL CATALOG  static list of catalog LLMs + BYOM registration
  - COMPUTE MODULES  create, list, and invoke compute containers
  - OSDK GENERATOR  emit typed SDK descriptors from ObjectType definitions
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import String, Integer, JSON
from sqlalchemy.orm import Mapped, mapped_column, Session

from .database import Base, get_db
from . import models, models_action, tenancy
from .production_auth import Principal, require_permission

router = APIRouter(tags=["aip-extras"])

# ---------------------------------------------------------------------------
# SQLAlchemy models
# ---------------------------------------------------------------------------

class ComputeModule(Base):
    """Container-based compute unit that can be invoked interactively or in a pipeline."""
    __tablename__ = "compute_modules"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    display_name: Mapped[str] = mapped_column(String)
    image: Mapped[str] = mapped_column(String)
    entrypoint: Mapped[str] = mapped_column(String)
    mode: Mapped[str] = mapped_column(String, default="interactive")  # interactive / pipeline
    status: Mapped[str] = mapped_column(String, default="running")
    created_at: Mapped[int] = mapped_column(Integer)


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

# --- Model Catalog ---

class CatalogEntry(BaseModel):
    id: str
    provider: str
    context_window: int
    modalities: List[str]


class ByomCreate(BaseModel):
    id: Optional[str] = None
    project_id: str = "default"
    display_name: str
    provider: str
    endpoint_url: str
    model_name: str


class ByomRead(BaseModel):
    id: str
    status: str


# --- Compute Modules ---

class ComputeModuleCreate(BaseModel):
    id: Optional[str] = None
    display_name: str
    image: str
    entrypoint: str
    mode: Optional[str] = "interactive"


class ComputeModuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    display_name: str
    image: str
    entrypoint: str
    mode: str
    status: str
    created_at: int


class InvokeRequest(BaseModel):
    input: Any


class InvokeResponse(BaseModel):
    output: Any
    module_id: str


# --- OSDK Generator ---

class OsdkGenerateRequest(BaseModel):
    object_type_ids: Optional[List[str]] = None


class OsdkTypeDescriptor(BaseModel):
    name: str
    typescript_interface: str
    python_dataclass: str


class OsdkGenerateResponse(BaseModel):
    sdk: List[OsdkTypeDescriptor]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> int:
    return int(time.time())


def _audit(
    db: Session,
    actor: str,
    event_type: str,
    subject_type: str,
    subject_id: str,
    payload: Optional[Dict[str, Any]] = None,
) -> None:
    db.add(
        models_action.AuditLog(
            id=uuid.uuid4().hex,
            actor=actor,
            event_type=event_type,
            subject_type=subject_type,
            subject_id=subject_id,
            payload=payload or {},
        )
    )


# Static catalog definition — deterministic, no real keys
_STATIC_CATALOG: List[Dict[str, Any]] = [
    {
        "id": "catalog-gpt-turbo",
        "provider": "openai-compat",
        "context_window": 128_000,
        "modalities": ["text"],
    },
    {
        "id": "catalog-claude-sonnet",
        "provider": "anthropic-compat",
        "context_window": 200_000,
        "modalities": ["text", "vision"],
    },
    {
        "id": "catalog-llama3-70b",
        "provider": "meta-compat",
        "context_window": 8_192,
        "modalities": ["text"],
    },
    {
        "id": "catalog-mistral-8x7b",
        "provider": "mistral-compat",
        "context_window": 32_768,
        "modalities": ["text"],
    },
    {
        "id": "catalog-gemini-flash",
        "provider": "google-compat",
        "context_window": 1_000_000,
        "modalities": ["text", "vision", "audio"],
    },
]

# Base-type to TypeScript type mapping
_TS_TYPE_MAP: Dict[str, str] = {
    "string": "string",
    "str": "string",
    "integer": "number",
    "int": "number",
    "float": "number",
    "number": "number",
    "boolean": "boolean",
    "bool": "boolean",
    "array": "any[]",
    "list": "any[]",
    "object": "Record<string, any>",
    "dict": "Record<string, any>",
    "any": "any",
}

# Base-type to Python dataclass type mapping
_PY_TYPE_MAP: Dict[str, str] = {
    "string": "str",
    "str": "str",
    "integer": "int",
    "int": "int",
    "float": "float",
    "number": "float",
    "boolean": "bool",
    "bool": "bool",
    "array": "list",
    "list": "list",
    "object": "dict",
    "dict": "dict",
    "any": "Any",
}


def _to_ts_type(raw: str) -> str:
    return _TS_TYPE_MAP.get(raw.lower(), "any")


def _to_py_type(raw: str) -> str:
    return _PY_TYPE_MAP.get(raw.lower(), "Any")


def _safe_identifier(name: str) -> str:
    """Convert a display_name/id to a safe PascalCase identifier."""
    parts = [p.capitalize() for p in name.replace("-", "_").split("_") if p]
    return "".join(parts) or "Unknown"


def _build_sdk_descriptor(ot: models.ObjectType) -> OsdkTypeDescriptor:
    """Generate TypeScript interface and Python dataclass strings for an ObjectType."""
    props: Dict[str, Any] = ot.properties or {}
    class_name = _safe_identifier(ot.display_name or ot.id)
    # Foundry object types always expose a primary-key `id`. Only synthesize one
    # when the declared properties don't already include an `id`, otherwise the
    # generated code would declare `id` twice (invalid TS/Python).
    has_id = any(str(prop_name).lower() == "id" for prop_name in props.keys())

    # TypeScript interface lines
    ts_lines = [f"interface {class_name} {{"]
    if not has_id:
        ts_lines.append(f"  id: string;")
    for prop_name, prop_def in props.items():
        if isinstance(prop_def, dict):
            raw_type = str(prop_def.get("type", "any"))
        else:
            raw_type = str(prop_def)
        ts_type = _to_ts_type(raw_type)
        safe_prop = prop_name.replace("-", "_")
        ts_lines.append(f"  {safe_prop}: {ts_type};")
    ts_lines.append("}")
    typescript_interface = "\n".join(ts_lines)

    # Python dataclass lines
    py_lines = ["from dataclasses import dataclass", "from typing import Any", "", "@dataclass"]
    py_lines.append(f"class {class_name}:")
    field_count = 0
    if not has_id:
        py_lines.append(f"    id: str")
        field_count += 1
    for prop_name, prop_def in props.items():
        if isinstance(prop_def, dict):
            raw_type = str(prop_def.get("type", "any"))
        else:
            raw_type = str(prop_def)
        py_type = _to_py_type(raw_type)
        safe_prop = prop_name.replace("-", "_")
        py_lines.append(f"    {safe_prop}: {py_type} = None")
        field_count += 1
    if field_count == 0:  # no id, no props
        py_lines.append("    pass")
    python_dataclass = "\n".join(py_lines)

    return OsdkTypeDescriptor(
        name=class_name,
        typescript_interface=typescript_interface,
        python_dataclass=python_dataclass,
    )


# ---------------------------------------------------------------------------
# MODEL CATALOG endpoints
# ---------------------------------------------------------------------------

@router.get("/aip/model-catalog", response_model=List[CatalogEntry])
def list_model_catalog() -> List[CatalogEntry]:
    """Return a static list of catalog LLM descriptors."""
    return [CatalogEntry(**entry) for entry in _STATIC_CATALOG]


@router.post("/aip/model-catalog/byom", response_model=ByomRead)
def register_byom(body: ByomCreate, principal: Principal = Depends(require_permission("edit")), db: Session = Depends(get_db)) -> ByomRead:
    """Register a Bring-Your-Own-Model endpoint in the ModelEndpoint table."""
    tenancy.assert_project_permission(db, principal, body.project_id, "edit")
    endpoint_id = body.id or uuid.uuid4().hex
    existing = db.query(models.ModelEndpoint).filter(models.ModelEndpoint.id == endpoint_id).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"ModelEndpoint '{endpoint_id}' already exists")

    now = _now()
    row = models.ModelEndpoint(
        id=endpoint_id,
        project_id=body.project_id,
        display_name=body.display_name,
        provider=body.provider,
        model_name=body.model_name,
        purpose="byom",
        policy={"endpoint_url": body.endpoint_url},
        status="ACTIVE",
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    _audit(db, principal.id, "aip.byom.registered", "model_endpoint", endpoint_id,
           {"project_id": body.project_id, "provider": body.provider, "model_name": body.model_name})
    db.commit()
    return ByomRead(id=endpoint_id, status="ACTIVE")


# ---------------------------------------------------------------------------
# COMPUTE MODULES endpoints
# ---------------------------------------------------------------------------

@router.post("/compute-modules", response_model=ComputeModuleRead)
def create_compute_module(body: ComputeModuleCreate, db: Session = Depends(get_db)) -> ComputeModuleRead:
    """Create a new compute module record."""
    module_id = body.id or uuid.uuid4().hex
    existing = db.query(ComputeModule).filter(ComputeModule.id == module_id).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"ComputeModule '{module_id}' already exists")

    now = _now()
    row = ComputeModule(
        id=module_id,
        display_name=body.display_name,
        image=body.image,
        entrypoint=body.entrypoint,
        mode=body.mode or "interactive",
        status="running",
        created_at=now,
    )
    db.add(row)
    _audit(db, "system", "compute_module.created", "compute_module", module_id,
           {"image": body.image, "mode": row.mode})
    db.commit()
    db.refresh(row)
    return row


@router.get("/compute-modules", response_model=List[ComputeModuleRead])
def list_compute_modules(db: Session = Depends(get_db)) -> List[ComputeModuleRead]:
    """List all registered compute modules."""
    return db.query(ComputeModule).order_by(ComputeModule.created_at.desc()).all()


@router.post("/compute-modules/{module_id}/invoke", response_model=InvokeResponse)
def invoke_compute_module(
    module_id: str,
    body: InvokeRequest,
    db: Session = Depends(get_db),
) -> InvokeResponse:
    """Invoke a compute module with the given input; returns a deterministic echo-style transform."""
    module = db.query(ComputeModule).filter(ComputeModule.id == module_id).first()
    if not module:
        raise HTTPException(status_code=404, detail=f"ComputeModule '{module_id}' not found")

    if module.status != "running":
        raise HTTPException(status_code=409, detail=f"ComputeModule '{module_id}' is not running (status={module.status})")

    _audit(db, "system", "compute_module.invoked", "compute_module", module_id,
           {"input_type": type(body.input).__name__})
    db.commit()
    return InvokeResponse(output=body.input, module_id=module_id)


# ---------------------------------------------------------------------------
# OSDK GENERATOR endpoint
# ---------------------------------------------------------------------------

@router.post("/osdk/generate", response_model=OsdkGenerateResponse)
def generate_osdk(body: OsdkGenerateRequest, db: Session = Depends(get_db)) -> OsdkGenerateResponse:
    """Generate typed SDK descriptors (TypeScript interface + Python dataclass) for ObjectTypes."""
    if body.object_type_ids:
        object_types = (
            db.query(models.ObjectType)
            .filter(models.ObjectType.id.in_(body.object_type_ids))
            .all()
        )
        missing = set(body.object_type_ids) - {ot.id for ot in object_types}
        if missing:
            raise HTTPException(
                status_code=404,
                detail=f"ObjectType(s) not found: {sorted(missing)}",
            )
    else:
        object_types = db.query(models.ObjectType).all()

    sdk = [_build_sdk_descriptor(ot) for ot in object_types]

    _audit(db, "system", "osdk.generated", "osdk", "batch",
           {"count": len(sdk), "ids": [ot.id for ot in object_types]})
    db.commit()
    return OsdkGenerateResponse(sdk=sdk)
