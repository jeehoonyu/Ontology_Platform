import uuid
import time
from typing import Optional, List, Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import String, Integer, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, Session, relationship
from pydantic import BaseModel, ConfigDict, Field

from .database import Base, get_db
from . import models, models_action

# ---------------------------------------------------------------------------
# SQLAlchemy models
# ---------------------------------------------------------------------------

class MediaSet(Base):
    """
    An unstructured-content container grouping related media items by type.
    Mirrors the Foundry Media Sets concept for images, PDFs, audio, video, etc.
    """
    __tablename__ = "media_sets"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    media_type: Mapped[str] = mapped_column(String, nullable=False)  # image/pdf/audio/video/document
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer, default=lambda: int(time.time()))

    items: Mapped[List["MediaItem"]] = relationship("MediaItem", back_populates="media_set", cascade="all, delete-orphan")


class MediaItem(Base):
    """
    A single media artifact registered within a MediaSet.
    text_content is optional and used for deterministic local extraction.
    """
    __tablename__ = "media_items"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    media_set_id: Mapped[str] = mapped_column(String, ForeignKey("media_sets.id"), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String, nullable=False)
    mime_type: Mapped[str] = mapped_column(String, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    text_content: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    item_metadata: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[int] = mapped_column(Integer, default=lambda: int(time.time()))

    media_set: Mapped["MediaSet"] = relationship("MediaSet", back_populates="items")


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

VALID_MEDIA_TYPES = {"image", "pdf", "audio", "video", "document", "multimodal"}


class MediaSetCreate(BaseModel):
    id: Optional[str] = None
    display_name: str
    media_type: str = Field(..., description="image | pdf | audio | video | document")
    description: Optional[str] = None


class MediaSetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    display_name: str
    media_type: str
    description: Optional[str]
    created_at: int


class MediaItemCreate(BaseModel):
    id: Optional[str] = None
    filename: str
    mime_type: str
    size_bytes: int = 0
    text_content: Optional[str] = None
    item_metadata: Dict[str, Any] = Field(default_factory=dict, alias="metadata")

    model_config = ConfigDict(populate_by_name=True)


class MediaItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    media_set_id: str
    filename: str
    mime_type: str
    size_bytes: int
    text_content: Optional[str]
    # Read from the ORM column attribute `item_metadata`; expose it as "metadata" in JSON.
    # (Using a validation alias of "metadata" would make from_attributes read SQLAlchemy's
    # reserved `.metadata` attribute instead of the column.)
    item_metadata: Dict[str, Any] = Field(default_factory=dict, serialization_alias="metadata")
    created_at: int


class MediaReferenceValue(BaseModel):
    media_set_id: str
    media_item_id: str


class MediaExtractionResult(BaseModel):
    media_item_id: str
    char_count: int
    word_count: int
    first_line: str
    has_text: bool
    media_reference: MediaReferenceValue


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(tags=["media_sets"])


def _not_found(resource: str, rid: str):
    raise HTTPException(status_code=404, detail=f"{resource} '{rid}' not found")


# POST /media-sets — create a new media set
@router.post("/media-sets", response_model=MediaSetRead, status_code=201)
def create_media_set(body: MediaSetCreate, db: Session = Depends(get_db)):
    if body.media_type not in VALID_MEDIA_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"media_type must be one of: {', '.join(sorted(VALID_MEDIA_TYPES))}",
        )
    set_id = body.id or uuid.uuid4().hex
    existing = db.query(MediaSet).filter(MediaSet.id == set_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="MediaSet already exists")

    db_obj = MediaSet(
        id=set_id,
        display_name=body.display_name,
        media_type=body.media_type,
        description=body.description,
        created_at=int(time.time()),
    )
    db.add(db_obj)
    db.add(models_action.AuditLog(
        id=uuid.uuid4().hex,
        actor="system",
        event_type="media_set.created",
        subject_type="media_set",
        subject_id=set_id,
        payload={"display_name": body.display_name, "media_type": body.media_type},
    ))
    db.commit()
    db.refresh(db_obj)
    return db_obj


# GET /media-sets — list all media sets
@router.get("/media-sets", response_model=List[MediaSetRead])
def list_media_sets(db: Session = Depends(get_db)):
    return db.query(MediaSet).order_by(MediaSet.created_at.desc()).all()


# GET /media-sets/{id} — get a single media set
@router.get("/media-sets/{media_set_id}", response_model=MediaSetRead)
def get_media_set(media_set_id: str, db: Session = Depends(get_db)):
    obj = db.query(MediaSet).filter(MediaSet.id == media_set_id).first()
    if not obj:
        _not_found("MediaSet", media_set_id)
    return obj


# POST /media-sets/{id}/items — register a media item in a set
@router.post("/media-sets/{media_set_id}/items", response_model=MediaItemRead, status_code=201)
def register_media_item(
    media_set_id: str,
    body: MediaItemCreate,
    db: Session = Depends(get_db),
):
    media_set = db.query(MediaSet).filter(MediaSet.id == media_set_id).first()
    if not media_set:
        _not_found("MediaSet", media_set_id)

    item_id = body.id or uuid.uuid4().hex
    existing = db.query(MediaItem).filter(MediaItem.id == item_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="MediaItem already exists")

    db_item = MediaItem(
        id=item_id,
        media_set_id=media_set_id,
        filename=body.filename,
        mime_type=body.mime_type,
        size_bytes=body.size_bytes,
        text_content=body.text_content,
        item_metadata=body.item_metadata if body.item_metadata is not None else {},
        created_at=int(time.time()),
    )
    db.add(db_item)
    db.add(models_action.AuditLog(
        id=uuid.uuid4().hex,
        actor="system",
        event_type="media_item.registered",
        subject_type="media_item",
        subject_id=item_id,
        payload={"media_set_id": media_set_id, "filename": body.filename, "mime_type": body.mime_type},
    ))
    db.commit()
    db.refresh(db_item)
    return db_item


# GET /media-sets/{id}/items — list items in a media set
@router.get("/media-sets/{media_set_id}/items", response_model=List[MediaItemRead])
def list_media_items(media_set_id: str, db: Session = Depends(get_db)):
    media_set = db.query(MediaSet).filter(MediaSet.id == media_set_id).first()
    if not media_set:
        _not_found("MediaSet", media_set_id)
    return db.query(MediaItem).filter(MediaItem.media_set_id == media_set_id).order_by(MediaItem.created_at).all()


# GET /media-items/{id} — get a single media item
@router.get("/media-items/{media_item_id}", response_model=MediaItemRead)
def get_media_item(media_item_id: str, db: Session = Depends(get_db)):
    item = db.query(MediaItem).filter(MediaItem.id == media_item_id).first()
    if not item:
        _not_found("MediaItem", media_item_id)
    return item


# POST /media-items/{id}/extract — deterministic local extraction
@router.post("/media-items/{media_item_id}/extract", response_model=MediaExtractionResult)
def extract_media_item(media_item_id: str, db: Session = Depends(get_db)):
    item = db.query(MediaItem).filter(MediaItem.id == media_item_id).first()
    if not item:
        _not_found("MediaItem", media_item_id)

    text = item.text_content or ""
    has_text = bool(text.strip())
    char_count = len(text)

    words = text.split() if has_text else []
    word_count = len(words)

    lines = text.splitlines()
    first_line = lines[0].strip() if lines else ""

    db.add(models_action.AuditLog(
        id=uuid.uuid4().hex,
        actor="system",
        event_type="media_item.extracted",
        subject_type="media_item",
        subject_id=media_item_id,
        payload={
            "char_count": char_count,
            "word_count": word_count,
            "has_text": has_text,
        },
    ))
    db.commit()

    return MediaExtractionResult(
        media_item_id=media_item_id,
        char_count=char_count,
        word_count=word_count,
        first_line=first_line,
        has_text=has_text,
        media_reference=MediaReferenceValue(
            media_set_id=item.media_set_id,
            media_item_id=media_item_id,
        ),
    )
