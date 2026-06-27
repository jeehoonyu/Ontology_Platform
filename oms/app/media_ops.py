"""
Media Sets — strategy extraction, RAG chunking & entity extraction over stored items
(deep-fidelity pass 11). Applies the documented Document-Intelligence strategies to a
media item's stored text (layout/entities/chunk+embeddings), so media content can feed
RAG and the ontology. Additive; deterministic; reuses aip_document + runtime.
"""
from typing import Optional, List, Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from .database import get_db
from . import media_sets as _media, aip_document as _doc, runtime

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
