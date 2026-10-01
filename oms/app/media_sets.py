import uuid
import time
from typing import Optional, List, Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import String, Integer, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, Session, relationship
from pydantic import BaseModel, ConfigDict, Field

from .database import Base, get_db
from . import models, models_action, production_auth, semantic_scope, tenancy

# ---------------------------------------------------------------------------
# SQLAlchemy models
# ---------------------------------------------------------------------------

class MediaSet(Base):
    """
    An unstructured-content container grouping related media items by type.
    Mirrors the Foundry Media Sets concept for images, PDFs, audio, video, etc.
    """
    __tablename__ = "media_sets"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    # The project that owns the set (GOAL_FOUNDATIONS A5). Sets created before sets had
    # projects have none: only a principal holding every project reaches them until one
    # is assigned (the owner's decision, 2026-09-26).
    project_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
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

    id: Mapped[str] = mapped_column(String, primary_key=True)
    media_set_id: Mapped[str] = mapped_column(String, ForeignKey("media_sets.id"), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String, nullable=False)
    mime_type: Mapped[str] = mapped_column(String, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    # Storage URI of the uploaded binary (when ingested via .../items/upload). Nullable
    # so text-only / metadata-only media items remain valid.
    storage_uri: Mapped[Optional[str]] = mapped_column(String, nullable=True)
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
    project_id: str = "default"
    display_name: str
    media_type: str = Field(..., description="image | pdf | audio | video | document")
    description: Optional[str] = None


class MediaSetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: Optional[str] = None
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


class MediaSetProjectAssign(BaseModel):
    project_id: str


def _authorize_set(db: Session, principal: production_auth.Principal, media_set: MediaSet, permission: str) -> None:
    """A set's project decides who reaches it and its items (GOAL_FOUNDATIONS A5).

    The list, get, items, upload and extraction read every tenant's sets before this. A set
    with no project predates projects on sets; only a principal who holds every project
    reaches it, until one is assigned.
    """
    caller = semantic_scope.effective_principal(principal)
    if media_set.project_id is None:
        if tenancy.accessible_project_ids(db, caller, permission) is not None:
            raise HTTPException(status_code=403, detail="This media set is not assigned to a project")
        return
    tenancy.assert_project_permission(db, caller, media_set.project_id, permission)


def media_set_for(db: Session, principal: production_auth.Principal, media_set_id: str, permission: str) -> MediaSet:
    media_set = db.get(MediaSet, media_set_id)
    if not media_set:
        _not_found("MediaSet", media_set_id)
    _authorize_set(db, principal, media_set, permission)
    return media_set


def media_item_for(db: Session, principal: production_auth.Principal, media_item_id: str, permission: str) -> MediaItem:
    item = db.get(MediaItem, media_item_id)
    if not item:
        _not_found("MediaItem", media_item_id)
    _authorize_set(db, principal, item.media_set, permission)
    return item


# POST /media-sets — create a new media set
@router.post("/media-sets", response_model=MediaSetRead, status_code=201)
def create_media_set(body: MediaSetCreate, db: Session = Depends(get_db),
                     principal: production_auth.Principal = Depends(production_auth.require_permission("edit"))):
    tenancy.assert_project_permission(db, semantic_scope.effective_principal(principal), body.project_id, "edit")
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
        project_id=body.project_id,
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
        payload={"display_name": body.display_name, "media_type": body.media_type, "project_id": body.project_id},
    ))
    db.commit()
    db.refresh(db_obj)
    return db_obj


# GET /media-sets — list all media sets
@router.get("/media-sets", response_model=List[MediaSetRead])
def list_media_sets(db: Session = Depends(get_db),
                    principal: production_auth.Principal = Depends(production_auth.require_permission("view"))):
    query = db.query(MediaSet)
    projects = tenancy.accessible_project_ids(db, semantic_scope.effective_principal(principal), "view")
    if projects is not None:
        # An unassigned set (project_id NULL) is in no project, so it falls out here.
        query = query.filter(MediaSet.project_id.in_(projects)) if projects else query.filter(MediaSet.id == "__none__")
    return query.order_by(MediaSet.created_at.desc()).all()


# POST /media-sets/{id}/project — assign a set to a project. Reaching an unassigned set
# takes every project, so this is how an administrator gives one an owner.
@router.post("/media-sets/{media_set_id}/project", response_model=MediaSetRead)
def assign_media_set_project(media_set_id: str, body: MediaSetProjectAssign, db: Session = Depends(get_db),
                             principal: production_auth.Principal = Depends(production_auth.require_permission("edit"))):
    media_set = media_set_for(db, principal, media_set_id, "edit")
    tenancy.assert_project_permission(db, semantic_scope.effective_principal(principal), body.project_id, "edit")
    previous = media_set.project_id
    media_set.project_id = body.project_id
    db.add(models_action.AuditLog(
        id=uuid.uuid4().hex,
        actor=semantic_scope.principal_id(principal),
        event_type="media_set.project_assigned",
        subject_type="media_set",
        subject_id=media_set_id,
        payload={"from": previous, "to": body.project_id},
    ))
    db.commit()
    db.refresh(media_set)
    return media_set


# GET /media-sets/{id} — get a single media set
@router.get("/media-sets/{media_set_id}", response_model=MediaSetRead)
def get_media_set(media_set_id: str, db: Session = Depends(get_db),
                  principal: production_auth.Principal = Depends(production_auth.require_permission("view"))):
    return media_set_for(db, principal, media_set_id, "view")


# POST /media-sets/{id}/items — register a media item in a set
@router.post("/media-sets/{media_set_id}/items", response_model=MediaItemRead, status_code=201)
def register_media_item(
    media_set_id: str,
    body: MediaItemCreate,
    db: Session = Depends(get_db),
    principal: production_auth.Principal = Depends(production_auth.require_permission("edit")),
):
    media_set_for(db, principal, media_set_id, "edit")

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
def list_media_items(media_set_id: str, db: Session = Depends(get_db),
                     principal: production_auth.Principal = Depends(production_auth.require_permission("view"))):
    media_set_for(db, principal, media_set_id, "view")
    return db.query(MediaItem).filter(MediaItem.media_set_id == media_set_id).order_by(MediaItem.created_at).all()


# GET /media-items/{id} — get a single media item
@router.get("/media-items/{media_item_id}", response_model=MediaItemRead)
def get_media_item(media_item_id: str, db: Session = Depends(get_db),
                   principal: production_auth.Principal = Depends(production_auth.require_permission("view"))):
    return media_item_for(db, principal, media_item_id, "view")


# POST /media-items/{id}/extract — deterministic local extraction
@router.post("/media-items/{media_item_id}/extract", response_model=MediaExtractionResult)
def extract_media_item(media_item_id: str, db: Session = Depends(get_db),
                       principal: production_auth.Principal = Depends(production_auth.require_permission("view"))):
    item = media_item_for(db, principal, media_item_id, "view")
    # Read before the commit below expires the item; reading it after loaded the row again.
    media_set_id = item.media_set_id

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
            media_set_id=media_set_id,
            media_item_id=media_item_id,
        ),
    )
