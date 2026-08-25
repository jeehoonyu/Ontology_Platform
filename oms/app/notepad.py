"""
Notepad & Reports local equivalent. A Notepad document combines formatted text
with LIVE embedded artifacts (object references, object tables, metric cards) that
resolve against the ontology at render time — mirroring Foundry Notepad as
documented in the public Foundry documentation. Deterministic and local.
"""
import time
import uuid
from typing import Optional, List, Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, Integer, JSON
from sqlalchemy.orm import Mapped, mapped_column, Session
from pydantic import BaseModel, ConfigDict, Field

from .database import Base, get_db
from . import models, models_action

router = APIRouter(tags=["notepad"])


def _now() -> int:
    return int(time.time())


# ---------------------------------------------------------------------------
# ORM model
# ---------------------------------------------------------------------------
class NotepadDocument(Base):
    __tablename__ = "notepad_documents"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String, default="document")  # document/report
    owner: Mapped[str] = mapped_column(String, default="system")
    # blocks: [{type: text|heading|object_reference|object_table|metric|chart|embed, ...}]
    blocks: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class NptTemplate(Base):
    """
    First-class, reusable Notepad TEMPLATE. Mirrors Foundry Notepad templates:
    a parameterized document fragment whose body blocks can be instantiated into a
    live document, with declared inputs bound to specific blocks. Deterministic/local.
    """
    __tablename__ = "npt_templates"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    # inputs: [{name: str, type: string|number|object, default: Any|None, required: bool}]
    inputs: Mapped[list] = mapped_column(JSON, default=list)
    # widget_bindings: [{block_ref: str, input_name: str}]
    widget_bindings: Mapped[list] = mapped_column(JSON, default=list)
    # body: [block template dict], each may carry a "ref" used by widget_bindings
    body: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class DocumentCreate(BaseModel):
    id: Optional[str] = None
    title: str
    kind: str = "document"
    owner: str = "system"
    blocks: List[Dict[str, Any]] = Field(default_factory=list)


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    title: str
    kind: str
    owner: str
    blocks: List[Any]
    created_at: int
    updated_at: int


class BlocksUpdate(BaseModel):
    blocks: List[Dict[str, Any]]


class ExportRequest(BaseModel):
    format: str = "pdf"  # pdf/html/markdown


# ---- Template schemas -----------------------------------------------------
NPT_INPUT_TYPES = {"string", "number", "object"}


class TemplateInputSpec(BaseModel):
    name: str
    type: str = "string"  # string/number/object
    default: Optional[Any] = None
    required: bool = False


class TemplateBindingSpec(BaseModel):
    block_ref: str
    input_name: str


class TemplateCreate(BaseModel):
    id: Optional[str] = None
    name: str
    inputs: List[TemplateInputSpec] = Field(default_factory=list)
    widget_bindings: List[TemplateBindingSpec] = Field(default_factory=list)
    body: List[Dict[str, Any]] = Field(default_factory=list)


class TemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    inputs: List[Any]
    widget_bindings: List[Any]
    body: List[Any]
    created_at: int
    updated_at: int


class TemplateInputsBody(BaseModel):
    inputs: Dict[str, Any] = Field(default_factory=dict)


class FromTemplateRequest(BaseModel):
    template_id: str
    inputs: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.post("/notepad/documents", response_model=DocumentRead, status_code=201)
def create_document(body: DocumentCreate, db: Session = Depends(get_db)):
    did = body.id or uuid.uuid4().hex
    if db.get(NotepadDocument, did):
        raise HTTPException(status_code=400, detail="NotepadDocument already exists")
    now = _now()
    doc = NotepadDocument(id=did, title=body.title, kind=body.kind, owner=body.owner,
                          blocks=body.blocks, created_at=now, updated_at=now)
    db.add(doc)
    db.add(models_action.AuditLog(id=uuid.uuid4().hex, actor=body.owner, event_type="notepad.document.created",
                                  subject_type="notepad_document", subject_id=did, payload={"kind": body.kind}))
    db.commit(); db.refresh(doc)
    return doc


@router.get("/notepad/documents", response_model=List[DocumentRead])
def list_documents(kind: Optional[str] = Query(default=None), db: Session = Depends(get_db)):
    q = db.query(NotepadDocument)
    if kind:
        q = q.filter(NotepadDocument.kind == kind)
    return q.all()


@router.get("/notepad/documents/{document_id}", response_model=DocumentRead)
def get_document(document_id: str, db: Session = Depends(get_db)):
    doc = db.get(NotepadDocument, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="NotepadDocument not found")
    return doc


@router.put("/notepad/documents/{document_id}/blocks", response_model=DocumentRead)
def update_blocks(document_id: str, body: BlocksUpdate, db: Session = Depends(get_db)):
    doc = db.get(NotepadDocument, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="NotepadDocument not found")
    doc.blocks = body.blocks
    doc.updated_at = _now()
    db.commit(); db.refresh(doc)
    return doc


@router.get("/notepad/documents/{document_id}/render")
def render_document(document_id: str, db: Session = Depends(get_db)):
    """Resolve embedded live artifacts against the current ontology state."""
    doc = db.get(NotepadDocument, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="NotepadDocument not found")

    resolved: List[Dict[str, Any]] = []
    for block in (doc.blocks or []):
        btype = block.get("type")
        if btype in ("text", "heading"):
            resolved.append({"type": btype, "content": block.get("content", "")})
        elif btype == "object_reference":
            oid = block.get("object_id")
            obj = db.get(models.ObjectInstance, oid) if oid else None
            resolved.append({
                "type": btype, "object_id": oid,
                "resolved": obj.properties if obj else None,
                "exists": obj is not None,
            })
        elif btype in ("object_table", "metric"):
            otype = block.get("object_type_id")
            instances = (db.query(models.ObjectInstance)
                         .filter(models.ObjectInstance.object_type_id == otype).all()) if otype else []
            if btype == "metric":
                field = block.get("field")
                vals = [i.properties.get(field) for i in instances if isinstance(i.properties.get(field), (int, float))] if field else []
                agg = block.get("agg", "count")
                value = len(instances) if agg == "count" else (sum(vals) if agg == "sum" else (sum(vals) / len(vals) if vals else 0))
                resolved.append({"type": "metric", "object_type_id": otype, "agg": agg, "field": field, "value": value})
            else:
                resolved.append({
                    "type": "object_table", "object_type_id": otype,
                    "row_count": len(instances),
                    "sample_ids": [i.id for i in instances[:5]],
                })
        else:
            resolved.append(dict(block))
    return {"document_id": document_id, "title": doc.title, "kind": doc.kind, "blocks": resolved}


@router.post("/notepad/documents/{document_id}/export")
def export_document(document_id: str, body: ExportRequest, db: Session = Depends(get_db)):
    doc = db.get(NotepadDocument, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="NotepadDocument not found")
    db.add(models_action.AuditLog(id=uuid.uuid4().hex, actor="system", event_type="notepad.document.exported",
                                  subject_type="notepad_document", subject_id=document_id, payload={"format": body.format}))
    db.commit()
    return {
        "document_id": document_id, "title": doc.title, "format": body.format,
        "block_count": len(doc.blocks or []),
        "artifact": f"{doc.title.replace(' ', '_')}.{body.format}",
        "status": "generated",
    }


# ---------------------------------------------------------------------------
# Template resource (first-class, reusable, parameterized document fragments)
# ---------------------------------------------------------------------------
def _type_matches(value: Any, declared: str) -> bool:
    """Type-check an input value against a declared template input type."""
    if declared == "string":
        return isinstance(value, str)
    if declared == "number":
        # accept int/float but not bool (which is an int subclass)
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if declared == "object":
        return isinstance(value, dict)
    # unknown declared type -> accept (validation of the spec happens at create)
    return True


def _validate_template_inputs(tpl: NptTemplate, supplied: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Validate supplied inputs against the template's declared inputs.
    Returns a list of error dicts (empty == valid). Errors: missing required
    inputs and type mismatches (string/number/object).
    """
    errors: List[Dict[str, Any]] = []
    for spec in (tpl.inputs or []):
        name = spec.get("name")
        declared = spec.get("type", "string")
        required = bool(spec.get("required", False))
        if name not in supplied:
            if required:
                errors.append({"input": name, "error": "missing_required"})
            continue
        if not _type_matches(supplied[name], declared):
            errors.append({"input": name, "error": "type_mismatch", "expected": declared})
    return errors


def _resolved_inputs(tpl: NptTemplate, supplied: Dict[str, Any]) -> Dict[str, Any]:
    """Merge declared defaults with supplied values (supplied wins)."""
    values: Dict[str, Any] = {}
    for spec in (tpl.inputs or []):
        name = spec.get("name")
        if name is None:
            continue
        if "default" in spec and spec.get("default") is not None:
            values[name] = spec.get("default")
    values.update(supplied)
    return values


@router.post("/notepad/templates", response_model=TemplateRead, status_code=201)
def create_template(body: TemplateCreate, db: Session = Depends(get_db)):
    tid = body.id or uuid.uuid4().hex
    if db.get(NptTemplate, tid):
        raise HTTPException(status_code=400, detail="NptTemplate already exists")
    for spec in body.inputs:
        if spec.type not in NPT_INPUT_TYPES:
            raise HTTPException(
                status_code=422,
                detail=f"Input '{spec.name}' has invalid type '{spec.type}'; must be one of {sorted(NPT_INPUT_TYPES)}",
            )
    now = _now()
    tpl = NptTemplate(
        id=tid,
        name=body.name,
        inputs=[s.model_dump() for s in body.inputs],
        widget_bindings=[b.model_dump() for b in body.widget_bindings],
        body=body.body,
        created_at=now,
        updated_at=now,
    )
    db.add(tpl)
    db.add(models_action.AuditLog(id=uuid.uuid4().hex, actor="system", event_type="notepad.template.created",
                                  subject_type="notepad_template", subject_id=tid,
                                  payload={"name": body.name, "input_count": len(body.inputs)}))
    db.commit(); db.refresh(tpl)
    return tpl


@router.get("/notepad/templates", response_model=List[TemplateRead])
def list_templates(db: Session = Depends(get_db)):
    return db.query(NptTemplate).all()


@router.get("/notepad/templates/{template_id}", response_model=TemplateRead)
def get_template(template_id: str, db: Session = Depends(get_db)):
    tpl = db.get(NptTemplate, template_id)
    if not tpl:
        raise HTTPException(status_code=404, detail="NptTemplate not found")
    return tpl


@router.post("/notepad/templates/{template_id}/validate")
def validate_template_inputs(template_id: str, body: TemplateInputsBody, db: Session = Depends(get_db)):
    tpl = db.get(NptTemplate, template_id)
    if not tpl:
        raise HTTPException(status_code=404, detail="NptTemplate not found")
    errors = _validate_template_inputs(tpl, body.inputs)
    if errors:
        raise HTTPException(status_code=422, detail={"template_id": template_id, "errors": errors})
    return {"template_id": template_id, "ok": True}


def _instantiate_block(block: Dict[str, Any], bound: Dict[str, Any], values: Dict[str, Any]) -> Dict[str, Any]:
    """
    Produce a concrete document block from a template block. Inputs bound to this
    block (via widget_bindings -> bound[input_name]) are substituted: any string
    field is interpolated with {input_name} placeholders, and the resolved input
    values are also attached under "inputs" for downstream live resolution.
    """
    out = dict(block)
    out.pop("ref", None)
    if not bound:
        return out
    fmt_values = {k: values.get(k) for k in bound.keys()}
    for key, val in list(out.items()):
        if isinstance(val, str):
            try:
                out[key] = val.format(**{k: ("" if v is None else v) for k, v in fmt_values.items()})
            except Exception:
                pass
    merged_inputs = dict(out.get("inputs") or {})
    for input_name in bound.keys():
        merged_inputs[input_name] = values.get(input_name)
    out["inputs"] = merged_inputs
    return out


@router.post("/notepad/documents/{document_id}/blocks/from-template", response_model=DocumentRead)
def add_blocks_from_template(document_id: str, body: FromTemplateRequest, db: Session = Depends(get_db)):
    doc = db.get(NotepadDocument, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="NotepadDocument not found")
    tpl = db.get(NptTemplate, body.template_id)
    if not tpl:
        raise HTTPException(status_code=404, detail="NptTemplate not found")

    errors = _validate_template_inputs(tpl, body.inputs)
    if errors:
        raise HTTPException(status_code=422, detail={"template_id": body.template_id, "errors": errors})

    values = _resolved_inputs(tpl, body.inputs)

    # block_ref -> {input_name, ...} bindings
    bindings_by_ref: Dict[str, Dict[str, Any]] = {}
    for b in (tpl.widget_bindings or []):
        ref = b.get("block_ref")
        iname = b.get("input_name")
        if ref is None or iname is None:
            continue
        bindings_by_ref.setdefault(ref, {})[iname] = True

    new_blocks: List[Dict[str, Any]] = []
    for tb in (tpl.body or []):
        ref = tb.get("ref")
        bound = bindings_by_ref.get(ref, {}) if ref is not None else {}
        new_blocks.append(_instantiate_block(tb, bound, values))

    doc.blocks = list(doc.blocks or []) + new_blocks
    doc.updated_at = _now()
    db.add(models_action.AuditLog(id=uuid.uuid4().hex, actor="system", event_type="notepad.template.instantiated",
                                  subject_type="notepad_document", subject_id=document_id,
                                  payload={"template_id": body.template_id, "blocks_added": len(new_blocks)}))
    db.commit(); db.refresh(doc)
    return doc
