"""
AIP Document Intelligence — extraction strategies (deep-fidelity pass 3).

The base `/aip/document-intelligence/extract` does regex/schema extraction only.
This module adds the documented strategy model: raw-text, layout (section split),
classify, entities, structured (regex/schema), and chunking + deterministic local
embeddings for RAG. Additive; deterministic; no proprietary document models.
"""
import re
import time
import uuid
import zlib
from typing import Optional, List, Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from .database import get_db
from . import runtime

router = APIRouter(tags=["aip_document"])

EMBED_DIM = 16


def _embed(text: str) -> List[float]:
    """Deterministic local bag-of-tokens embedding (no model). Hash tokens into a
    fixed-dim vector and L2-normalize — stable across runs for RAG demos/tests."""
    vec = [0.0] * EMBED_DIM
    for tok in re.findall(r"[a-z0-9]+", text.lower()):
        vec[zlib.crc32(tok.encode()) % EMBED_DIM] += 1.0
    norm = sum(v * v for v in vec) ** 0.5 or 1.0
    return [round(v / norm, 6) for v in vec]


def _chunk(text: str, size: int, overlap: int) -> List[str]:
    words = text.split()
    if size <= 0:
        return [text]
    chunks = []
    step = max(1, size - overlap)
    for start in range(0, len(words), step):
        chunk = words[start:start + size]
        if chunk:
            chunks.append(" ".join(chunk))
        if start + size >= len(words):
            break
    return chunks


class ProcessRequest(BaseModel):
    text: str
    strategy: str = "raw_text"  # raw_text | structured | layout | classify | entities | chunk
    extraction_schema: Dict[str, Any] = Field(default_factory=dict)
    labels: List[str] = Field(default_factory=list)
    chunk_size: int = 60
    overlap: int = 10


class ChunkRequest(BaseModel):
    text: str
    chunk_size: int = 60
    overlap: int = 10


@router.get("/aip/document-intelligence/strategies")
def strategies():
    return {"strategies": ["raw_text", "structured", "layout", "classify", "entities", "chunk"],
            "embedding": {"type": "deterministic_local_bag_of_tokens", "dim": EMBED_DIM}}


@router.post("/aip/document-intelligence/process")
def process_document(body: ProcessRequest, db: Session = Depends(get_db)):
    text = body.text or ""
    strategy = body.strategy

    if strategy == "raw_text":
        clean = re.sub(r"\s+", " ", text).strip()
        return {"strategy": strategy, "char_count": len(text), "word_count": len(text.split()),
                "line_count": text.count("\n") + 1 if text else 0, "text": clean}

    if strategy == "structured":
        return {"strategy": strategy, **runtime.extract_document_intelligence(text, body.extraction_schema)}

    if strategy == "layout":
        # split into sections on blank lines; treat short all-ish lines as headings
        blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
        sections = []
        for i, block in enumerate(blocks):
            lines = block.splitlines()
            heading = lines[0].strip() if lines and len(lines[0].strip()) <= 80 else None
            sections.append({"index": i, "heading": heading,
                             "text": block, "word_count": len(block.split())})
        return {"strategy": strategy, "section_count": len(sections), "sections": sections}

    if strategy == "classify":
        lowered = text.lower()
        label = next((l for l in body.labels if str(l).lower() in lowered), (body.labels[0] if body.labels else "unknown"))
        scores = {l: sum(1 for w in str(l).lower().split() if w in lowered) for l in body.labels}
        return {"strategy": strategy, "label": label, "scores": scores}

    if strategy == "entities":
        return {"strategy": strategy, "entities": runtime.extract_document_intelligence(text, {})["entities"]}

    if strategy == "chunk":
        chunks = _chunk(text, body.chunk_size, body.overlap)
        return {"strategy": strategy, "chunk_count": len(chunks),
                "chunks": [{"index": i, "text": c, "embedding": _embed(c)} for i, c in enumerate(chunks)]}

    raise HTTPException(status_code=422, detail=f"Unknown strategy '{strategy}'")


@router.post("/aip/document-intelligence/chunk")
def chunk_document(body: ChunkRequest):
    chunks = _chunk(body.text or "", body.chunk_size, body.overlap)
    return {"chunk_count": len(chunks),
            "embedding_dim": EMBED_DIM,
            "chunks": [{"index": i, "text": c, "embedding": _embed(c)} for i, c in enumerate(chunks)]}
