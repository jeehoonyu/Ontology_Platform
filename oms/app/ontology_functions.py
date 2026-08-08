"""
Foundry FUNCTIONS ON OBJECTS — typed, deterministic compute functions over object sets.

Distinct from AIP Logic (block-based reasoning chains), these are aggregate / query
functions that operate directly on ObjectInstance rows for a given object_type_id.
"""

from .database import Base, get_db
from . import models, models_action
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import String, Integer, JSON
from sqlalchemy.orm import Mapped, mapped_column, Session
from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List, Any, Dict
import time, uuid, math

router = APIRouter(tags=["ontology-functions"])

# ---------------------------------------------------------------------------
# SQLAlchemy models
# ---------------------------------------------------------------------------

class OntologyFunction(Base):
    """
    Typed, deterministic function definition.  kind=query returns filtered rows;
    kind=compute applies an aggregate expression over a numeric property.
    """
    __tablename__ = "ontology_functions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    display_name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    kind: Mapped[str] = mapped_column(String, default="query")          # "query" | "compute"
    input_schema: Mapped[dict] = mapped_column(JSON, default=dict)
    object_type_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    expression: Mapped[dict] = mapped_column(JSON, default=dict)        # {type:"aggregate", op:"count|sum|avg|min|max", field}
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class OntologyFunctionRun(Base):
    """
    Immutable execution record for every function invocation.
    """
    __tablename__ = "ontology_function_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    function_id: Mapped[str] = mapped_column(String, index=True)
    inputs: Mapped[dict] = mapped_column(JSON, default=dict)
    output: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[int] = mapped_column(Integer)


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class OntologyFunctionCreate(BaseModel):
    id: Optional[str] = None
    display_name: str
    description: Optional[str] = None
    kind: str = Field(default="query", pattern="^(query|compute)$")
    input_schema: Dict[str, Any] = Field(default_factory=dict)
    object_type_id: Optional[str] = None
    expression: Dict[str, Any] = Field(default_factory=dict)


class OntologyFunctionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    display_name: str
    description: Optional[str]
    kind: str
    input_schema: Dict[str, Any]
    object_type_id: Optional[str]
    expression: Dict[str, Any]
    created_at: int
    updated_at: int


class OntologyFunctionRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    function_id: str
    inputs: Dict[str, Any]
    output: Dict[str, Any]
    created_at: int


class FunctionRunRequest(BaseModel):
    inputs: Dict[str, Any] = Field(default_factory=dict)
    actor: str = "system"


# ---------------------------------------------------------------------------
# Helper: apply expression deterministically
# ---------------------------------------------------------------------------

def _apply_expression(
    instances: List[models.ObjectInstance],
    expression: Dict[str, Any],
    kind: str,
) -> Dict[str, Any]:
    """
    Evaluate the expression against a list of ObjectInstance rows.

    For kind='query':  return {rows: [...serialized properties...], rows_considered: N}
    For kind='compute' with type='aggregate':
        op=count  -> count of rows
        op=sum    -> sum of numeric `field` across all instance.properties
        op=avg    -> arithmetic mean
        op=min    -> minimum
        op=max    -> maximum
    """
    rows_considered = len(instances)

    if kind == "query":
        rows = [
            {"id": inst.id, "object_type_id": inst.object_type_id, "properties": inst.properties}
            for inst in instances
        ]
        return {"rows": rows, "rows_considered": rows_considered}

    # kind == "compute"
    expr_type = expression.get("type", "aggregate")
    if expr_type != "aggregate":
        return {"error": f"Unsupported expression type: {expr_type}", "rows_considered": rows_considered}

    op = str(expression.get("op", "count")).lower()
    field = expression.get("field")

    if op == "count":
        return {"output": rows_considered, "rows_considered": rows_considered}

    # numeric aggregations require a field name
    if not field:
        return {"error": f"op='{op}' requires a 'field' in the expression", "rows_considered": rows_considered}

    values: List[float] = []
    for inst in instances:
        props = inst.properties or {}
        raw = props.get(field)
        if raw is None:
            continue
        try:
            values.append(float(raw))
        except (TypeError, ValueError):
            pass  # non-numeric – skip

    if not values:
        return {"output": None, "rows_considered": rows_considered, "values_found": 0}

    if op == "sum":
        result_val: Any = sum(values)
    elif op == "avg":
        result_val = sum(values) / len(values)
    elif op == "min":
        result_val = min(values)
    elif op == "max":
        result_val = max(values)
    else:
        return {"error": f"Unknown op: {op}", "rows_considered": rows_considered}

    # Guard against NaN / Infinity before serialising
    if isinstance(result_val, float) and (math.isnan(result_val) or math.isinf(result_val)):
        result_val = None

    return {"output": result_val, "rows_considered": rows_considered, "values_found": len(values)}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/ontology-functions", response_model=OntologyFunctionRead, status_code=201)
def create_ontology_function(
    body: OntologyFunctionCreate,
    db: Session = Depends(get_db),
):
    fn_id = body.id or uuid.uuid4().hex
    existing = db.query(OntologyFunction).filter(OntologyFunction.id == fn_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="OntologyFunction already exists")

    # Validate object_type_id if provided
    if body.object_type_id:
        ot = db.query(models.ObjectType).filter(models.ObjectType.id == body.object_type_id).first()
        if not ot:
            raise HTTPException(status_code=404, detail=f"ObjectType '{body.object_type_id}' not found")

    now = int(time.time())
    db_fn = OntologyFunction(
        id=fn_id,
        display_name=body.display_name,
        description=body.description,
        kind=body.kind,
        input_schema=body.input_schema,
        object_type_id=body.object_type_id,
        expression=body.expression,
        created_at=now,
        updated_at=now,
    )
    db.add(db_fn)
    db.add(models_action.AuditLog(
        id=uuid.uuid4().hex,
        actor="system",
        event_type="ontology_function.created",
        subject_type="ontology_function",
        subject_id=fn_id,
        payload={"display_name": body.display_name, "kind": body.kind},
    ))
    db.commit()
    db.refresh(db_fn)
    return db_fn


@router.get("/ontology-functions", response_model=List[OntologyFunctionRead])
def list_ontology_functions(
    kind: Optional[str] = None,
    object_type_id: Optional[str] = None,
    db: Session = Depends(get_db),
):
    query = db.query(OntologyFunction)
    if kind:
        query = query.filter(OntologyFunction.kind == kind)
    if object_type_id:
        query = query.filter(OntologyFunction.object_type_id == object_type_id)
    return query.order_by(OntologyFunction.created_at.desc()).all()


@router.get("/ontology-functions/{function_id}", response_model=OntologyFunctionRead)
def get_ontology_function(function_id: str, db: Session = Depends(get_db)):
    fn = db.query(OntologyFunction).filter(OntologyFunction.id == function_id).first()
    if not fn:
        raise HTTPException(status_code=404, detail=f"OntologyFunction '{function_id}' not found")
    return fn


@router.post("/ontology-functions/{function_id}/run", response_model=OntologyFunctionRunRead, status_code=201)
def run_ontology_function(
    function_id: str,
    body: FunctionRunRequest,
    db: Session = Depends(get_db),
):
    fn = db.query(OntologyFunction).filter(OntologyFunction.id == function_id).first()
    if not fn:
        raise HTTPException(status_code=404, detail=f"OntologyFunction '{function_id}' not found")

    # Load matching ObjectInstance rows when object_type_id is set
    instances: List[models.ObjectInstance] = []
    if fn.object_type_id:
        instances = (
            db.query(models.ObjectInstance)
            .filter(models.ObjectInstance.object_type_id == fn.object_type_id)
            .all()
        )

    output = _apply_expression(instances, fn.expression, fn.kind)

    run_id = uuid.uuid4().hex
    run = OntologyFunctionRun(
        id=run_id,
        function_id=function_id,
        inputs=body.inputs,
        output=output,
        created_at=int(time.time()),
    )
    db.add(run)
    db.add(models_action.AuditLog(
        id=uuid.uuid4().hex,
        actor=body.actor,
        event_type="ontology_function.run",
        subject_type="ontology_function",
        subject_id=function_id,
        payload={"run_id": run_id, "rows_considered": output.get("rows_considered", 0)},
    ))
    db.commit()
    db.refresh(run)
    return run
