"""
AIP Assist — custom content sources / RAG context (deepening pass).

Lets teams register custom documentation ("content sources") that AIP Assist can
retrieve from when answering. Faithful to the documented mechanics in
assist/{aip-assist-custom-docs-overview, adding-documentation-to-aip-assist,
aip-assist-registering-content, custom-documentation-best-practices,
agents-in-aip-assist, overview}.

Modeled deterministically (no real LLM, no real embedding model):
  - Ingestion uses the documented **heading-hierarchy** best practice: Markdown is
    chunked by ATX headings (`#`..`######`), building a `heading_path` (e.g.
    "H1 > H2") and accumulating paragraph text per section.
  - Embeddings are deterministic bag-of-tokens hashes (mirrors app/aip_document.py),
    so retrieval is repeatable across runs.
  - Hybrid retrieval mixes a keyword (Jaccard token-overlap) score and a cosine
    embedding score.

CRITIC CORRECTIONS honored:
  - The exact chunking regex and the hybrid-ranking weights are NOT documented.
    Chunking is tied to the documented heading-hierarchy best practice; the
    keyword/embedding blend weights (0.6 / 0.4) are an IMPLEMENTATION CHOICE and are
    flagged as such in code (see _hybrid_score), not presented as documented fact.
  - Deterministic hash embeddings mirror the approach already in aip_document.py.
"""

from .database import Base, get_db
from . import models, models_action
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, Integer, JSON, Boolean, Float, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, Session
from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List, Any, Dict
import re, time, uuid, zlib

router = APIRouter(tags=["aip-assist-content-sources"])

# ---------------------------------------------------------------------------
# Constants / helpers
# ---------------------------------------------------------------------------

EMBED_DIM = 64  # documented best practice ties chunking to headings; dim is local choice

VALID_SOURCE_TYPES = {"notepad", "markdown_docs"}
VALID_SCOPE_TYPES = {"always", "by_resource"}

# Ranking blend. IMPLEMENTATION CHOICE — the docs do NOT specify hybrid weights.
KEYWORD_WEIGHT = 0.6
EMBEDDING_WEIGHT = 0.4

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


def _tokens(text: str) -> List[str]:
    return _TOKEN_RE.findall((text or "").lower())


def _embed(text: str) -> List[float]:
    """Deterministic local bag-of-tokens embedding (no model). Hash each token into a
    fixed-dim vector and L2-normalize — stable across runs (mirrors aip_document._embed)."""
    vec = [0.0] * EMBED_DIM
    for tok in _tokens(text):
        vec[zlib.crc32(tok.encode()) % EMBED_DIM] += 1.0
    norm = sum(v * v for v in vec) ** 0.5 or 1.0
    return [round(v / norm, 6) for v in vec]


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5 or 1.0
    nb = sum(y * y for y in b) ** 0.5 or 1.0
    return dot / (na * nb)


def _keyword_score(query_tokens: set, chunk_tokens: set) -> float:
    """Jaccard token-overlap between query and chunk."""
    if not query_tokens or not chunk_tokens:
        return 0.0
    inter = len(query_tokens & chunk_tokens)
    union = len(query_tokens | chunk_tokens)
    return inter / union if union else 0.0


def _hybrid_score(query: str, chunk_text: str, chunk_embedding: List[float]) -> float:
    """score = 0.6*keyword + 0.4*embedding.

    IMPLEMENTATION CHOICE: the docs do not specify hybrid-ranking weights; the blend
    below is our deterministic choice (NOT documented fact)."""
    q_tokens = set(_tokens(query))
    kw = _keyword_score(q_tokens, set(_tokens(chunk_text)))
    emb = _cosine(_embed(query), chunk_embedding or [])
    return round(KEYWORD_WEIGHT * kw + EMBEDDING_WEIGHT * emb, 6)


def _chunk_markdown(text: str) -> List[Dict[str, Any]]:
    """Heading-hierarchy chunking (documented best practice).

    Parse Markdown by ATX headings (#..######), maintaining a heading stack to build
    `heading_path` like "H1 > H2". Accumulate paragraph text (split on blank lines)
    under each heading into chunks with sequence_index. Returns a list of dicts:
    {heading_path, section_title, text, sequence_index}.
    """
    lines = (text or "").splitlines()
    chunks: List[Dict[str, Any]] = []
    heading_stack: List[Dict[str, Any]] = []  # [{level, title}]
    buffer: List[str] = []
    seq = 0

    def _current_path() -> str:
        return " > ".join(h["title"] for h in heading_stack)

    def _current_title() -> Optional[str]:
        return heading_stack[-1]["title"] if heading_stack else None

    def _flush():
        nonlocal seq, buffer
        body = "\n".join(buffer).strip()
        buffer = []
        if not body:
            return
        # Split body into paragraph chunks on blank lines.
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
        for para in paragraphs:
            chunks.append({
                "heading_path": _current_path(),
                "section_title": _current_title(),
                "text": para,
                "sequence_index": seq,
            })
            seq += 1

    for line in lines:
        m = _HEADING_RE.match(line)
        if m:
            # New heading: flush any accumulated body under the prior heading.
            _flush()
            level = len(m.group(1))
            title = m.group(2).strip()
            # Pop the stack down to (and including) the same/deeper levels.
            while heading_stack and heading_stack[-1]["level"] >= level:
                heading_stack.pop()
            heading_stack.append({"level": level, "title": title})
        else:
            buffer.append(line)
    _flush()
    return chunks


# ---------------------------------------------------------------------------
# SQLAlchemy models  (prefix Acs / acs_)
# ---------------------------------------------------------------------------


class AcsSource(Base):
    __tablename__ = "acs_sources"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    display_name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    source_type: Mapped[str] = mapped_column(String)  # notepad | markdown_docs
    owner: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    ingestion_status: Mapped[str] = mapped_column(String, default="PENDING")  # PENDING|INGESTED|FAILED
    raw_content: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    last_ingested_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class AcsVisibility(Base):
    __tablename__ = "acs_visibility"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    source_id: Mapped[str] = mapped_column(String, ForeignKey("acs_sources.id"), index=True)
    scope_type: Mapped[str] = mapped_column(String, default="always")  # always | by_resource
    resource_ids: Mapped[list] = mapped_column(JSON, default=list)
    updated_at: Mapped[int] = mapped_column(Integer)


class AcsChunk(Base):
    __tablename__ = "acs_chunks"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    source_id: Mapped[str] = mapped_column(String, ForeignKey("acs_sources.id"), index=True)
    heading_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    section_title: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    text: Mapped[str] = mapped_column(String)
    sequence_index: Mapped[int] = mapped_column(Integer)
    embedding: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[int] = mapped_column(Integer)


class AcsIngestLog(Base):
    __tablename__ = "acs_ingest_logs"

    # Monotonic surrogate so logs written in the same wall-clock second keep insert order.
    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    id: Mapped[str] = mapped_column(String, index=True)
    source_id: Mapped[str] = mapped_column(String, ForeignKey("acs_sources.id"), index=True)
    event_type: Mapped[str] = mapped_column(String)  # registered|updated|deleted|reingested
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String)  # INGESTED|FAILED
    error_detail: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer)


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class SourceCreate(BaseModel):
    id: Optional[str] = None
    display_name: str
    description: Optional[str] = None
    source_type: str = "markdown_docs"
    owner: Optional[str] = None
    content: str = ""  # markdown body to ingest immediately


class SourceUpdate(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    content: Optional[str] = None


class SourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    display_name: str
    description: Optional[str] = None
    source_type: str
    owner: Optional[str] = None
    ingestion_status: str
    last_ingested_at: Optional[int] = None
    created_at: int
    updated_at: int


class VisibilityUpdate(BaseModel):
    scope_type: str = "always"
    resource_ids: List[str] = Field(default_factory=list)


class VisibilityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_id: str
    scope_type: str
    resource_ids: List[str]
    updated_at: int


class RetrieveRequest(BaseModel):
    query: str
    k: int = 5
    scope_context: Optional[str] = None


class QueryWithSourcesRequest(BaseModel):
    prompt: str
    source_ids: Optional[List[str]] = None
    scope_context: Optional[str] = None
    k: int = 3


# ---------------------------------------------------------------------------
# Internal ingestion logic
# ---------------------------------------------------------------------------


def _ingest_source(db: Session, source: AcsSource, content: str, event_type: str) -> Dict[str, Any]:
    """(Re)ingest a source's content into chunks. Returns a summary dict."""
    now = int(time.time())
    # Wipe prior chunks.
    db.query(AcsChunk).filter(AcsChunk.source_id == source.id).delete()

    parsed = _chunk_markdown(content)
    if not parsed:
        source.ingestion_status = "FAILED"
        source.raw_content = content
        source.updated_at = now
        log = AcsIngestLog(
            id=uuid.uuid4().hex, source_id=source.id, event_type=event_type,
            chunk_count=0, status="FAILED",
            error_detail="empty document: no headings or text to chunk",
            created_at=now,
        )
        db.add(log)
        return {"status": "FAILED", "chunk_count": 0, "error_detail": log.error_detail}

    for c in parsed:
        db.add(AcsChunk(
            id=uuid.uuid4().hex,
            source_id=source.id,
            heading_path=c["heading_path"],
            section_title=c["section_title"],
            text=c["text"],
            sequence_index=c["sequence_index"],
            embedding=_embed(c["text"]),
            created_at=now,
        ))
    source.ingestion_status = "INGESTED"
    source.raw_content = content
    source.last_ingested_at = now
    source.updated_at = now
    db.add(AcsIngestLog(
        id=uuid.uuid4().hex, source_id=source.id, event_type=event_type,
        chunk_count=len(parsed), status="INGESTED", error_detail=None, created_at=now,
    ))
    return {"status": "INGESTED", "chunk_count": len(parsed)}


def _get_source_or_404(db: Session, source_id: str) -> AcsSource:
    src = db.query(AcsSource).filter(AcsSource.id == source_id, AcsSource.ingestion_status != "DELETED").first()
    if not src:
        raise HTTPException(status_code=404, detail=f"AcsSource '{source_id}' not found")
    return src


def _visibility_for(db: Session, source_id: str) -> Optional[AcsVisibility]:
    return db.query(AcsVisibility).filter(AcsVisibility.source_id == source_id).first()


def _is_in_scope(db: Session, source_id: str, scope_context: Optional[str]) -> bool:
    """always -> always visible; by_resource -> visible only if scope_context in resource_ids."""
    vis = _visibility_for(db, source_id)
    if vis is None or vis.scope_type == "always":
        return True
    # by_resource
    return scope_context is not None and scope_context in (vis.resource_ids or [])


def _retrieve(db: Session, source_id: str, query: str, k: int) -> List[Dict[str, Any]]:
    chunks = db.query(AcsChunk).filter(AcsChunk.source_id == source_id).all()
    scored = []
    for ch in chunks:
        score = _hybrid_score(query, ch.text, ch.embedding or [])
        scored.append({
            "chunk_id": ch.id,
            "source_id": ch.source_id,
            "heading_path": ch.heading_path,
            "section_title": ch.section_title,
            "text": ch.text,
            "sequence_index": ch.sequence_index,
            "score": score,
        })
    # Deterministic ordering: score desc, then sequence_index asc (stable tie-break).
    scored.sort(key=lambda r: (-r["score"], r["sequence_index"]))
    return scored[: max(0, k)]


# ---------------------------------------------------------------------------
# CRUD endpoints
# ---------------------------------------------------------------------------


@router.post("/aip/assist/sources", response_model=SourceRead)
def create_source(body: SourceCreate, db: Session = Depends(get_db)):
    if body.source_type not in VALID_SOURCE_TYPES:
        raise HTTPException(status_code=422, detail=f"source_type must be one of {sorted(VALID_SOURCE_TYPES)}")
    src_id = body.id or uuid.uuid4().hex
    if db.query(AcsSource).filter(AcsSource.id == src_id).first():
        raise HTTPException(status_code=400, detail="AcsSource already exists")

    now = int(time.time())
    src = AcsSource(
        id=src_id,
        display_name=body.display_name,
        description=body.description,
        source_type=body.source_type,
        owner=body.owner,
        ingestion_status="PENDING",
        raw_content=body.content or "",
        created_at=now,
        updated_at=now,
    )
    db.add(src)
    db.flush()

    # Default visibility = always.
    db.add(AcsVisibility(
        id=uuid.uuid4().hex, source_id=src_id, scope_type="always",
        resource_ids=[], updated_at=now,
    ))

    summary = _ingest_source(db, src, body.content or "", event_type="registered")

    db.add(models_action.AuditLog(
        id=uuid.uuid4().hex, actor="system",
        event_type="aip_assist.content_source.created",
        subject_type="acs_source", subject_id=src_id,
        payload={"display_name": body.display_name, **summary},
    ))
    db.commit()
    db.refresh(src)
    return src


@router.get("/aip/assist/sources", response_model=List[SourceRead])
def list_sources(db: Session = Depends(get_db)):
    return db.query(AcsSource).filter(AcsSource.ingestion_status != "DELETED").order_by(AcsSource.created_at).all()


@router.get("/aip/assist/sources/suggest")
def suggest_sources(prompt: str = Query(...), scope_context: Optional[str] = Query(None),
                    db: Session = Depends(get_db)):
    """Rank sources by their best chunk score for the prompt (respecting visibility)."""
    results = []
    for src in db.query(AcsSource).filter(AcsSource.ingestion_status == "INGESTED").all():
        if not _is_in_scope(db, src.id, scope_context):
            continue
        top = _retrieve(db, src.id, prompt, k=1)
        best = top[0]["score"] if top else 0.0
        best_heading = top[0]["heading_path"] if top else None
        results.append({
            "source_id": src.id,
            "display_name": src.display_name,
            "best_score": best,
            "best_heading_path": best_heading,
        })
    results.sort(key=lambda r: (-r["best_score"], r["source_id"]))
    return {"prompt": prompt, "suggestions": results}


@router.get("/aip/assist/sources/ingest-logs")
def list_ingest_logs(source_id: Optional[str] = Query(None), db: Session = Depends(get_db)):
    q = db.query(AcsIngestLog)
    if source_id:
        q = q.filter(AcsIngestLog.source_id == source_id)
    logs = q.order_by(AcsIngestLog.seq).all()
    return {"count": len(logs), "logs": [
        {
            "id": l.id, "source_id": l.source_id, "event_type": l.event_type,
            "chunk_count": l.chunk_count, "status": l.status,
            "error_detail": l.error_detail, "created_at": l.created_at,
        } for l in logs
    ]}


@router.get("/aip/assist/sources/{source_id}", response_model=SourceRead)
def get_source(source_id: str, db: Session = Depends(get_db)):
    return _get_source_or_404(db, source_id)


@router.patch("/aip/assist/sources/{source_id}", response_model=SourceRead)
def update_source(source_id: str, body: SourceUpdate, db: Session = Depends(get_db)):
    src = _get_source_or_404(db, source_id)
    now = int(time.time())
    if body.display_name is not None:
        src.display_name = body.display_name
    if body.description is not None:
        src.description = body.description
    if body.content is not None:
        _ingest_source(db, src, body.content, event_type="updated")
    src.updated_at = now
    db.commit()
    db.refresh(src)
    return src


@router.delete("/aip/assist/sources/{source_id}")
def delete_source(source_id: str, db: Session = Depends(get_db)):
    src = _get_source_or_404(db, source_id)
    now = int(time.time())
    db.query(AcsChunk).filter(AcsChunk.source_id == source_id).delete()
    db.query(AcsVisibility).filter(AcsVisibility.source_id == source_id).delete()
    db.add(AcsIngestLog(
        id=uuid.uuid4().hex, source_id=source_id, event_type="deleted",
        chunk_count=0, status="INGESTED", error_detail=None, created_at=now,
    ))
    # Preserve the source identity so its append-only ingest log remains valid.
    src.ingestion_status = "DELETED"
    src.raw_content = None
    src.updated_at = now
    db.commit()
    return {"deleted": True, "source_id": source_id}


# ---------------------------------------------------------------------------
# Visibility
# ---------------------------------------------------------------------------


@router.put("/aip/assist/sources/{source_id}/visibility", response_model=VisibilityRead)
def set_visibility(source_id: str, body: VisibilityUpdate, db: Session = Depends(get_db)):
    _get_source_or_404(db, source_id)
    if body.scope_type not in VALID_SCOPE_TYPES:
        raise HTTPException(status_code=422, detail=f"scope_type must be one of {sorted(VALID_SCOPE_TYPES)}")
    now = int(time.time())
    vis = _visibility_for(db, source_id)
    if vis is None:
        vis = AcsVisibility(id=uuid.uuid4().hex, source_id=source_id, updated_at=now)
        db.add(vis)
    vis.scope_type = body.scope_type
    vis.resource_ids = body.resource_ids
    vis.updated_at = now
    db.commit()
    db.refresh(vis)
    return vis


@router.get("/aip/assist/sources/{source_id}/visibility", response_model=VisibilityRead)
def get_visibility(source_id: str, db: Session = Depends(get_db)):
    _get_source_or_404(db, source_id)
    vis = _visibility_for(db, source_id)
    if vis is None:
        raise HTTPException(status_code=404, detail="visibility not configured")
    return vis


# ---------------------------------------------------------------------------
# Content / reingest
# ---------------------------------------------------------------------------


@router.get("/aip/assist/sources/{source_id}/content")
def get_content(source_id: str, db: Session = Depends(get_db)):
    src = _get_source_or_404(db, source_id)
    chunks = db.query(AcsChunk).filter(AcsChunk.source_id == source_id) \
        .order_by(AcsChunk.sequence_index).all()
    return {
        "source_id": source_id,
        "ingestion_status": src.ingestion_status,
        "raw_content": src.raw_content,
        "chunk_count": len(chunks),
        "chunks": [
            {
                "id": c.id, "heading_path": c.heading_path, "section_title": c.section_title,
                "text": c.text, "sequence_index": c.sequence_index,
            } for c in chunks
        ],
    }


@router.post("/aip/assist/sources/{source_id}/reingest")
def reingest_source(source_id: str, body: Optional[SourceUpdate] = None, db: Session = Depends(get_db)):
    src = _get_source_or_404(db, source_id)
    content = (body.content if body and body.content is not None else src.raw_content) or ""
    summary = _ingest_source(db, src, content, event_type="reingested")
    db.commit()
    return {"source_id": source_id, **summary}


# ---------------------------------------------------------------------------
# Retrieval / assist integration
# ---------------------------------------------------------------------------


@router.post("/aip/assist/sources/{source_id}/retrieve")
def retrieve(source_id: str, body: RetrieveRequest, db: Session = Depends(get_db)):
    src = _get_source_or_404(db, source_id)
    if not _is_in_scope(db, source_id, body.scope_context):
        return {"source_id": source_id, "in_scope": False, "results": [], "count": 0}
    results = _retrieve(db, source_id, body.query, body.k)
    return {
        "source_id": source_id,
        "in_scope": True,
        "query": body.query,
        "count": len(results),
        "results": results,
    }


@router.post("/aip/assist/query-with-sources")
def query_with_sources(body: QueryWithSourcesRequest, db: Session = Depends(get_db)):
    """Retrieve from each in-scope source, synthesize a deterministic templated answer
    with citations {source_id, heading_path}."""
    if body.source_ids:
        sources = []
        for sid in body.source_ids:
            sources.append(_get_source_or_404(db, sid))
    else:
        sources = db.query(AcsSource).filter(AcsSource.ingestion_status == "INGESTED").all()

    collected: List[Dict[str, Any]] = []
    for src in sources:
        if src.ingestion_status != "INGESTED":
            continue
        if not _is_in_scope(db, src.id, body.scope_context):
            continue
        for r in _retrieve(db, src.id, body.prompt, body.k):
            collected.append(r)

    collected.sort(key=lambda r: (-r["score"], r["source_id"], r["sequence_index"]))
    top = collected[: max(1, body.k)] if collected else []

    citations = [{"source_id": r["source_id"], "heading_path": r["heading_path"]} for r in top]
    if top:
        snippets = " ".join(r["text"] for r in top)
        answer = f"Based on {len(top)} retrieved passage(s): {snippets}"
    else:
        answer = "No relevant content sources found for this prompt."

    return {
        "prompt": body.prompt,
        "answer": answer,
        "citations": citations,
        "retrieved": top,
    }
