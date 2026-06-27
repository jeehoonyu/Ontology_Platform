"""
Notepad — deep render with live charts, templated text & markdown export
(deep-fidelity pass 11). Extends the base render with `chart` blocks (object-set
aggregation series), `template` blocks (interpolated from context + object props),
filtered metrics, and a rendered markdown export string. Additive; deterministic.
"""
from typing import Optional, List, Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from .database import get_db
from . import models, runtime, notepad as _notepad

router = APIRouter(tags=["notepad_ops"])


def _agg(rows, op, field):
    nums = [(r.properties or {}).get(field) for r in rows
            if isinstance((r.properties or {}).get(field), (int, float)) and not isinstance((r.properties or {}).get(field), bool)]
    if op == "count":
        return len(rows)
    if op == "sum":
        return sum(nums)
    if op == "avg":
        return round(sum(nums) / len(nums), 6) if nums else 0
    if op == "min":
        return min(nums) if nums else None
    if op == "max":
        return max(nums) if nums else None
    return len(rows)


class RenderFullRequest(BaseModel):
    context: Dict[str, Any] = Field(default_factory=dict)


@router.post("/notepad/documents/{document_id}/render-full")
def render_full(document_id: str, body: RenderFullRequest, db: Session = Depends(get_db)):
    doc = db.get(_notepad.NotepadDocument, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"NotepadDocument '{document_id}' not found")
    ctx = dict(body.context)
    resolved: List[Dict[str, Any]] = []
    md_lines: List[str] = [f"# {doc.title}", ""]

    for block in (doc.blocks or []):
        bt = block.get("type")
        if bt == "heading":
            text = str(block.get("content", ""))
            resolved.append({"type": bt, "content": text})
            md_lines += [f"## {text}", ""]
        elif bt in ("text", "template"):
            template = str(block.get("content") or block.get("template") or "")
            try:
                text = template.format(**ctx)
            except Exception:
                text = template
            resolved.append({"type": bt, "content": text})
            md_lines += [text, ""]
        elif bt == "object_reference":
            obj = db.get(models.ObjectInstance, block.get("object_id"))
            props = obj.properties if obj else None
            resolved.append({"type": bt, "object_id": block.get("object_id"), "resolved": props, "exists": obj is not None})
            md_lines += [f"- **{block.get('object_id')}**: {props}", ""]
        elif bt in ("object_table", "metric"):
            rows, _ = runtime._logic_object_rows(db, block.get("object_type_id"), block.get("filters", {}), 10 ** 9)
            if bt == "metric":
                val = _agg(rows, block.get("agg", "count"), block.get("field"))
                resolved.append({"type": "metric", "object_type_id": block.get("object_type_id"), "value": val})
                md_lines += [f"**{block.get('title', 'Metric')}:** {val}", ""]
            else:
                resolved.append({"type": "object_table", "object_type_id": block.get("object_type_id"),
                                 "row_count": len(rows), "sample_ids": [r.id for r in rows[:5]]})
                md_lines += [f"_{block.get('object_type_id')} table — {len(rows)} rows_", ""]
        elif bt == "chart":
            rows, _ = runtime._logic_object_rows(db, block.get("object_type_id"), block.get("filters", {}), 10 ** 9)
            group_by = block.get("group_by")
            agg, field = block.get("agg", "count"), block.get("field")
            series = []
            if group_by:
                buckets: Dict[Any, List[Any]] = {}
                for r in rows:
                    buckets.setdefault((r.properties or {}).get(group_by), []).append(r)
                series = [{"group": g, "value": _agg(grp, agg, field)} for g, grp in buckets.items()]
            resolved.append({"type": "chart", "object_type_id": block.get("object_type_id"),
                             "group_by": group_by, "series": series})
            md_lines += [f"_chart: {agg}({field or '*'}) by {group_by}_ -> {series}", ""]
        else:
            resolved.append(dict(block))

    return {"document_id": document_id, "title": doc.title, "blocks": resolved,
            "markdown_export": "\n".join(md_lines)}
