"""
Media Sets — strategy extraction, RAG chunking & entity extraction over stored items
(deep-fidelity pass 11). Applies the documented Document-Intelligence strategies to a
media item's stored text (layout/entities/chunk+embeddings), so media content can feed
RAG and the ontology. Additive; deterministic; reuses aip_document + runtime.
"""
import time
import uuid
from typing import Optional, List, Any, Dict

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import Response
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from .database import get_db
from . import media_sets as _media, aip_document as _doc, runtime, storage

router = APIRouter(tags=["media_ops"])


def _item(db: Session, media_item_id: str):
    item = db.get(_media.MediaItem, media_item_id)
    if not item:
        raise HTTPException(status_code=404, detail=f"Media item '{media_item_id}' not found")
    return item


class ChunkRequest(BaseModel):
    chunk_size: int = 60
    overlap: int = 10


class ProcessRequest(BaseModel):
    strategy: str = "entities"   # entities | layout | chunk | classify
    labels: List[str] = Field(default_factory=list)
    chunk_size: int = 60
    overlap: int = 10


@router.post("/media-items/{media_item_id}/chunk")
def chunk_media(media_item_id: str, body: ChunkRequest, db: Session = Depends(get_db)):
    item = _item(db, media_item_id)
    text = item.text_content or ""
    chunks = _doc._chunk(text, body.chunk_size, body.overlap)
    return {"media_item_id": media_item_id, "chunk_count": len(chunks), "embedding_dim": _doc.EMBED_DIM,
            "chunks": [{"index": i, "text": c, "embedding": _doc._embed(c)} for i, c in enumerate(chunks)]}


@router.post("/media-items/{media_item_id}/extract-entities")
def extract_entities(media_item_id: str, db: Session = Depends(get_db)):
    item = _item(db, media_item_id)
    result = runtime.extract_document_intelligence(item.text_content or "", {})
    return {"media_item_id": media_item_id, "entities": result["entities"], "summary": result["summary"]}


@router.post("/media-items/{media_item_id}/process")
def process_media(media_item_id: str, body: ProcessRequest, db: Session = Depends(get_db)):
    item = _item(db, media_item_id)
    text = item.text_content or ""
    if body.strategy == "entities":
        return {"strategy": "entities", "entities": runtime.extract_document_intelligence(text, {})["entities"]}
    if body.strategy == "layout":
        import re
        blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
        return {"strategy": "layout", "section_count": len(blocks),
                "sections": [{"index": i, "text": b, "word_count": len(b.split())} for i, b in enumerate(blocks)]}
    if body.strategy == "chunk":
        chunks = _doc._chunk(text, body.chunk_size, body.overlap)
        return {"strategy": "chunk", "chunk_count": len(chunks),
                "chunks": [{"index": i, "text": c, "embedding": _doc._embed(c)} for i, c in enumerate(chunks)]}
    if body.strategy == "classify":
        lowered = text.lower()
        label = next((l for l in body.labels if str(l).lower() in lowered), (body.labels[0] if body.labels else "unknown"))
        return {"strategy": "classify", "label": label}
    raise HTTPException(status_code=422, detail=f"Unknown strategy '{body.strategy}'")


# ---------------------------------------------------------------------------
# Real binary media upload/download.
# ---------------------------------------------------------------------------

_TEXTLIKE_EXT = (".txt", ".md", ".csv", ".json", ".log", ".xml", ".html")


@router.post("/media-sets/{media_set_id}/items/upload")
async def upload_media_item(media_set_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Upload a real binary media artifact into a media set; the bytes go to object
    storage. Text-like uploads also populate `text_content` so the existing extraction
    strategies (chunk/entities/layout) work on them immediately."""
    mset = db.get(_media.MediaSet, media_set_id)
    if not mset:
        raise HTTPException(status_code=404, detail=f"Media set '{media_set_id}' not found")
    raw = await file.read()
    item_id = uuid.uuid4().hex
    uri = storage.put(f"media/{item_id}/{file.filename or 'upload'}", raw)
    ctype = file.content_type or "application/octet-stream"
    text_content: Optional[str] = None
    if ctype.startswith("text/") or (file.filename or "").lower().endswith(_TEXTLIKE_EXT):
        try:
            text_content = raw.decode("utf-8")
        except Exception:
            text_content = None
    item = _media.MediaItem(
        id=item_id, media_set_id=media_set_id, filename=file.filename or "upload",
        mime_type=ctype, size_bytes=len(raw), storage_uri=uri, text_content=text_content,
        item_metadata={}, created_at=int(time.time()))
    db.add(item)
    db.commit()
    return {"id": item_id, "media_set_id": media_set_id, "filename": item.filename,
            "mime_type": ctype, "size_bytes": len(raw), "storage_uri": uri,
            "has_text": text_content is not None}


@router.get("/media-items/{media_item_id}/content")
def media_item_content(media_item_id: str, db: Session = Depends(get_db)):
    item = _item(db, media_item_id)
    data = storage.open_bytes(item.storage_uri)
    if data is None:
        if item.text_content is not None:
            return Response(content=item.text_content.encode("utf-8"),
                            media_type=item.mime_type or "text/plain")
        raise HTTPException(status_code=404, detail="no stored content for this media item")
    return Response(content=data, media_type=item.mime_type or "application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{item.filename}"'})
