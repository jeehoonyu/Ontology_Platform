"""
marketplace.py — Foundry DEVOPS PRODUCTS + MARKETPLACE module.

Tables:
  - devops_products        : publishable product bundles with resource manifests
  - product_releases       : versioned releases (stable/beta channels) per product
  - product_installations  : installations of a specific release into a target project
"""
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import JSON, Boolean, Integer, String
from sqlalchemy.orm import Mapped, Session, mapped_column

from . import models, models_action
from .database import Base, get_db

# ---------------------------------------------------------------------------
# SQLAlchemy ORM Models
# ---------------------------------------------------------------------------


VALID_INSTALL_MODES = {"production", "bootstrap", "singleton"}
# Hierarchical release channels: a "release" install tracks everything, "test"
# tracks test+stable, "stable" only takes stable-tagged versions. This mirrors the
# Foundry Marketplace channel hierarchy (Release >= Test/Pre-Stable >= Stable).
VALID_RELEASE_CHANNELS = {"release", "test", "stable"}
# Which release channels a tracking channel accepts (release-tag hierarchy).
_CHANNEL_ACCEPTS: Dict[str, set] = {
    "stable": {"stable"},
    "test": {"stable", "test", "beta"},
    "release": {"stable", "test", "beta", "release"},
}


class DevopsProduct(Base):
    """A publishable DevOps product bundle."""

    __tablename__ = "devops_products"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    resources: Mapped[list] = mapped_column(JSON, default=list)
    publisher: Mapped[str] = mapped_column(String, nullable=False, default="system")
    # production | bootstrap | singleton — set by the product builder; controls the
    # default lock + auto-upgrade behavior of installations. Defaults to the unlocked
    # 'bootstrap' starting point so a plain install stays immediately modifiable
    # (production/singleton are opt-in and lock by default).
    mode: Mapped[str] = mapped_column(String, nullable=False, default="bootstrap")
    created_at: Mapped[int] = mapped_column(Integer)


class ProductRelease(Base):
    """A versioned release of a DevOps product."""

    __tablename__ = "product_releases"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    product_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    version: Mapped[str] = mapped_column(String, nullable=False)
    channel: Mapped[str] = mapped_column(String, nullable=False, default="stable")
    notes: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer)


class ProductInstallation(Base):
    """An installation of a product release into a target project."""

    __tablename__ = "product_installations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    product_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    release_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    target_project: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="installed")
    input_mappings: Mapped[dict] = mapped_column(JSON, default=dict)
    # Installation lifecycle metadata (Foundry Marketplace install settings).
    mode: Mapped[str] = mapped_column(String, nullable=False, default="production")
    release_channel: Mapped[str] = mapped_column(String, nullable=False, default="stable")
    auto_upgrade: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------


class ResourceRef(BaseModel):
    kind: str
    id: str


class DevopsProductCreate(BaseModel):
    id: Optional[str] = None
    display_name: str
    description: Optional[str] = None
    resources: Optional[List[ResourceRef]] = Field(default_factory=list)
    publisher: Optional[str] = "system"
    mode: Optional[str] = "bootstrap"
    actor: Optional[str] = "system"


class DevopsProductRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    display_name: str
    description: Optional[str] = None
    resources: List[Any]
    publisher: str
    mode: str
    created_at: int


class ProductReleaseCreate(BaseModel):
    id: Optional[str] = None
    version: str
    channel: Optional[str] = "stable"
    notes: Optional[str] = None
    actor: Optional[str] = "system"


class ProductReleaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    product_id: str
    version: str
    channel: str
    notes: Optional[str] = None
    created_at: int


class MarketplaceEntry(BaseModel):
    id: str
    display_name: str
    description: Optional[str] = None
    publisher: str
    resources: List[Any]
    created_at: int
    latest_release: Optional[ProductReleaseRead] = None


class InstallRequest(BaseModel):
    target_project: str
    release_id: Optional[str] = None
    input_mappings: Optional[Dict[str, Any]] = Field(default_factory=dict)
    # Consolidated with install-resolved: apply the same prefix/suffix semantics.
    prefix: Optional[str] = None
    suffix: Optional[str] = None
    # Installation lifecycle settings. When omitted, defaults are derived from the
    # product's install mode (bootstrap => unlocked + no auto-upgrade; production/
    # singleton => locked + auto-upgrade encouraged).
    mode: Optional[str] = None
    release_channel: Optional[str] = None
    auto_upgrade: Optional[bool] = None
    locked: Optional[bool] = None
    actor: Optional[str] = "system"


class ProductInstallationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    product_id: str
    release_id: str
    target_project: str
    status: str
    input_mappings: Dict[str, Any]
    mode: str
    release_channel: str
    auto_upgrade: bool
    locked: bool
    created_at: int
    updated_at: int


class UpgradeRequest(BaseModel):
    release_id: str
    actor: Optional[str] = "system"


class LockRequest(BaseModel):
    actor: Optional[str] = "system"


class AutoUpgradeRequest(BaseModel):
    auto_upgrade: bool
    actor: Optional[str] = "system"


class ReleaseChannelRequest(BaseModel):
    release_channel: str
    actor: Optional[str] = "system"


class UninstallRequest(BaseModel):
    # Foundry requires typing a confirmation string ("delete installation").
    # We accept either an explicit confirm flag or the confirmation phrase.
    confirm: bool = False
    confirm_text: Optional[str] = None
    actor: Optional[str] = "system"


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(tags=["marketplace"])


def _now() -> int:
    return int(time.time())


def _gen_id() -> str:
    return uuid.uuid4().hex


def _append_audit(
    db: Session,
    *,
    actor: str,
    event_type: str,
    subject_type: str,
    subject_id: str,
    payload: Dict[str, Any],
) -> None:
    db.add(
        models_action.AuditLog(
            id=_gen_id(),
            actor=actor,
            event_type=event_type,
            subject_type=subject_type,
            subject_id=subject_id,
            payload=payload,
        )
    )


# ---------------------------------------------------------------------------
# DevOps Products Endpoints
# ---------------------------------------------------------------------------


@router.post("/devops/products", response_model=DevopsProductRead)
def create_devops_product(
    body: DevopsProductCreate,
    db: Session = Depends(get_db),
) -> DevopsProduct:
    product_id = body.id or _gen_id()
    existing = db.query(DevopsProduct).filter(DevopsProduct.id == product_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="DevopsProduct already exists")

    mode = (body.mode or "production").lower()
    if mode not in VALID_INSTALL_MODES:
        raise HTTPException(
            status_code=400,
            detail=f"mode must be one of {sorted(VALID_INSTALL_MODES)}",
        )

    resources_data = [
        r.model_dump() if isinstance(r, ResourceRef) else r
        for r in (body.resources or [])
    ]
    db_obj = DevopsProduct(
        id=product_id,
        display_name=body.display_name,
        description=body.description,
        resources=resources_data,
        publisher=body.publisher or "system",
        mode=mode,
        created_at=_now(),
    )
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj


@router.get("/devops/products", response_model=List[DevopsProductRead])
def list_devops_products(db: Session = Depends(get_db)) -> List[DevopsProduct]:
    return db.query(DevopsProduct).order_by(DevopsProduct.created_at.desc()).all()


@router.get("/devops/products/{product_id}", response_model=DevopsProductRead)
def get_devops_product(
    product_id: str,
    db: Session = Depends(get_db),
) -> DevopsProduct:
    obj = db.query(DevopsProduct).filter(DevopsProduct.id == product_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail=f"DevopsProduct '{product_id}' not found")
    return obj


@router.post("/devops/products/{product_id}/releases", response_model=ProductReleaseRead)
def create_product_release(
    product_id: str,
    body: ProductReleaseCreate,
    db: Session = Depends(get_db),
) -> ProductRelease:
    product = db.query(DevopsProduct).filter(DevopsProduct.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail=f"DevopsProduct '{product_id}' not found")

    channel = body.channel or "stable"
    if channel not in ("stable", "beta"):
        raise HTTPException(status_code=400, detail="channel must be 'stable' or 'beta'")

    release_id = body.id or _gen_id()
    existing = db.query(ProductRelease).filter(ProductRelease.id == release_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="ProductRelease already exists")

    db_obj = ProductRelease(
        id=release_id,
        product_id=product_id,
        version=body.version,
        channel=channel,
        notes=body.notes,
        created_at=_now(),
    )
    db.add(db_obj)
    _append_audit(
        db,
        actor=body.actor or "system",
        event_type="marketplace.release.created",
        subject_type="product_release",
        subject_id=release_id,
        payload={
            "product_id": product_id,
            "version": body.version,
            "channel": channel,
        },
    )
    db.commit()
    db.refresh(db_obj)
    return db_obj


# ---------------------------------------------------------------------------
# Marketplace Endpoints
# ---------------------------------------------------------------------------


@router.get("/marketplace", response_model=List[MarketplaceEntry])
def list_marketplace(db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    """List all products with their latest stable (or beta) release."""
    products = db.query(DevopsProduct).order_by(DevopsProduct.created_at.desc()).all()
    result: List[Dict[str, Any]] = []
    for product in products:
        latest = (
            db.query(ProductRelease)
            .filter(ProductRelease.product_id == product.id)
            .order_by(ProductRelease.created_at.desc())
            .first()
        )
        entry: Dict[str, Any] = {
            "id": product.id,
            "display_name": product.display_name,
            "description": product.description,
            "publisher": product.publisher,
            "resources": product.resources or [],
            "created_at": product.created_at,
            "latest_release": ProductReleaseRead.model_validate(latest) if latest else None,
        }
        result.append(entry)
    return result


def _install_defaults_for_mode(mode: str) -> Dict[str, Any]:
    """Default lifecycle settings derived from the product's install mode.

    Mirrors Foundry guidance: production/singleton installations are locked and
    track the stable channel (auto-upgrade encouraged); bootstrap installations are
    unlocked starting points with auto-upgrade disabled by default.
    """
    if mode == "bootstrap":
        return {"locked": False, "auto_upgrade": False, "release_channel": "stable"}
    # production + singleton
    return {"locked": True, "auto_upgrade": True, "release_channel": "stable"}


@router.post("/marketplace/{product_id}/install", response_model=ProductInstallationRead)
def install_product(
    product_id: str,
    body: InstallRequest,
    db: Session = Depends(get_db),
) -> ProductInstallation:
    """Install a product into a target project, defaulting to the latest release.

    Consolidated with ``/marketplace/{id}/install-resolved``: this endpoint now runs
    the same requirement validation (missing/unresolved inputs are rejected with 422)
    and applies the same prefix (ontology entities) / suffix (target project) rules,
    then records the full installation lifecycle metadata (mode, release_channel,
    auto_upgrade, locked).
    """
    product = db.query(DevopsProduct).filter(DevopsProduct.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail=f"DevopsProduct '{product_id}' not found")

    # Reuse marketplace_ops requirement validation (imported lazily to avoid the
    # marketplace_ops -> marketplace circular import at module load time).
    from . import marketplace_ops as _ops

    input_mappings = {str(k): str(v) for k, v in (body.input_mappings or {}).items()}
    missing, unresolved, resolved = _ops._validate(db, product_id, input_mappings)
    if missing or unresolved:
        raise HTTPException(
            status_code=422,
            detail={"missing_inputs": missing, "unresolved_inputs": unresolved},
        )

    if body.release_id:
        release = db.query(ProductRelease).filter(
            ProductRelease.id == body.release_id,
            ProductRelease.product_id == product_id,
        ).first()
        if not release:
            raise HTTPException(
                status_code=404,
                detail=f"ProductRelease '{body.release_id}' not found for product '{product_id}'",
            )
    else:
        release = (
            db.query(ProductRelease)
            .filter(ProductRelease.product_id == product_id)
            .order_by(ProductRelease.created_at.desc())
            .first()
        )
        if not release:
            raise HTTPException(
                status_code=400,
                detail=f"No releases available for product '{product_id}'",
            )

    # Resolve lifecycle settings (explicit body overrides mode-derived defaults).
    mode = (body.mode or product.mode or "production").lower()
    if mode not in VALID_INSTALL_MODES:
        raise HTTPException(
            status_code=400,
            detail=f"mode must be one of {sorted(VALID_INSTALL_MODES)}",
        )
    defaults = _install_defaults_for_mode(mode)
    release_channel = (body.release_channel or defaults["release_channel"]).lower()
    if release_channel not in VALID_RELEASE_CHANNELS:
        raise HTTPException(
            status_code=400,
            detail=f"release_channel must be one of {sorted(VALID_RELEASE_CHANNELS)}",
        )
    auto_upgrade = (
        body.auto_upgrade if body.auto_upgrade is not None else defaults["auto_upgrade"]
    )
    locked = body.locked if body.locked is not None else defaults["locked"]

    # Singleton mode: only one installation of the product per target project.
    if mode == "singleton":
        dup = (
            db.query(ProductInstallation)
            .filter(
                ProductInstallation.product_id == product_id,
                ProductInstallation.target_project == body.target_project + (body.suffix or ""),
            )
            .first()
        )
        if dup:
            raise HTTPException(
                status_code=409,
                detail="singleton product already installed in this target",
            )

    # Apply the same prefix/suffix semantics as install-resolved.
    created_content = []
    for res in (product.resources or []):
        name = res.get("id") if isinstance(res, dict) else None
        kind = res.get("kind") if isinstance(res, dict) else None
        final = name
        if body.prefix and kind in ("object_type", "action_type", "link_type"):
            final = f"{body.prefix}{name}"
        created_content.append({"kind": kind, "source_id": name, "installed_as": final})

    now = _now()
    install_id = _gen_id()
    db_obj = ProductInstallation(
        id=install_id,
        product_id=product_id,
        release_id=release.id,
        target_project=body.target_project + (body.suffix or ""),
        status="installed",
        input_mappings=input_mappings,
        mode=mode,
        release_channel=release_channel,
        auto_upgrade=bool(auto_upgrade),
        locked=bool(locked),
        created_at=now,
        updated_at=now,
    )
    db.add(db_obj)
    _append_audit(
        db,
        actor=body.actor or "system",
        event_type="marketplace.product.installed",
        subject_type="product_installation",
        subject_id=install_id,
        payload={
            "product_id": product_id,
            "release_id": release.id,
            "target_project": db_obj.target_project,
            "version": release.version,
            "mode": mode,
            "release_channel": release_channel,
            "resolved_inputs": len(resolved),
            "created_content": created_content,
        },
    )
    db.commit()
    db.refresh(db_obj)
    return db_obj


# ---------------------------------------------------------------------------
# Installations Endpoints
# ---------------------------------------------------------------------------


def _get_installation(db: Session, installation_id: str) -> ProductInstallation:
    installation = (
        db.query(ProductInstallation)
        .filter(ProductInstallation.id == installation_id)
        .first()
    )
    if not installation:
        raise HTTPException(
            status_code=404, detail=f"ProductInstallation '{installation_id}' not found"
        )
    return installation


@router.get("/installations", response_model=List[ProductInstallationRead])
def list_installations(
    product_id: Optional[str] = None,
    db: Session = Depends(get_db),
) -> List[ProductInstallation]:
    """List installations, optionally filtered by product."""
    q = db.query(ProductInstallation)
    if product_id:
        q = q.filter(ProductInstallation.product_id == product_id)
    return q.order_by(ProductInstallation.created_at.desc()).all()


@router.get("/installations/{installation_id}", response_model=ProductInstallationRead)
def get_installation(
    installation_id: str,
    db: Session = Depends(get_db),
) -> ProductInstallation:
    return _get_installation(db, installation_id)


@router.post("/installations/{installation_id}/upgrade", response_model=ProductInstallationRead)
def upgrade_installation(
    installation_id: str,
    body: UpgradeRequest,
    db: Session = Depends(get_db),
) -> ProductInstallation:
    """Upgrade an existing installation to a different release."""
    installation = _get_installation(db, installation_id)
    if installation.locked:
        raise HTTPException(
            status_code=409,
            detail="installation is locked; unlock it before upgrading",
        )

    release = db.query(ProductRelease).filter(
        ProductRelease.id == body.release_id,
        ProductRelease.product_id == installation.product_id,
    ).first()
    if not release:
        raise HTTPException(
            status_code=404,
            detail=f"ProductRelease '{body.release_id}' not found for product '{installation.product_id}'",
        )

    old_release_id = installation.release_id
    installation.release_id = body.release_id
    installation.status = "installed"
    installation.updated_at = _now()
    _append_audit(
        db,
        actor=body.actor or "system",
        event_type="marketplace.installation.upgraded",
        subject_type="product_installation",
        subject_id=installation_id,
        payload={
            "product_id": installation.product_id,
            "old_release_id": old_release_id,
            "new_release_id": body.release_id,
            "target_project": installation.target_project,
            "new_version": release.version,
        },
    )
    db.commit()
    db.refresh(installation)
    return installation


@router.post("/installations/{installation_id}/lock", response_model=ProductInstallationRead)
def lock_installation(
    installation_id: str,
    body: LockRequest = LockRequest(),
    db: Session = Depends(get_db),
) -> ProductInstallation:
    """Lock an installation to prevent edits to downstream content (safe upgrades)."""
    installation = _get_installation(db, installation_id)
    installation.locked = True
    installation.updated_at = _now()
    _append_audit(
        db,
        actor=body.actor or "system",
        event_type="marketplace.installation.locked",
        subject_type="product_installation",
        subject_id=installation_id,
        payload={"product_id": installation.product_id},
    )
    db.commit()
    db.refresh(installation)
    return installation


@router.post("/installations/{installation_id}/unlock", response_model=ProductInstallationRead)
def unlock_installation(
    installation_id: str,
    body: LockRequest = LockRequest(),
    db: Session = Depends(get_db),
) -> ProductInstallation:
    """Unlock an installation so its installed resources may be modified."""
    installation = _get_installation(db, installation_id)
    installation.locked = False
    installation.updated_at = _now()
    _append_audit(
        db,
        actor=body.actor or "system",
        event_type="marketplace.installation.unlocked",
        subject_type="product_installation",
        subject_id=installation_id,
        payload={"product_id": installation.product_id},
    )
    db.commit()
    db.refresh(installation)
    return installation


@router.post("/installations/{installation_id}/auto-upgrade", response_model=ProductInstallationRead)
def set_auto_upgrade(
    installation_id: str,
    body: AutoUpgradeRequest,
    db: Session = Depends(get_db),
) -> ProductInstallation:
    """Toggle automatic upgrades for an installation."""
    installation = _get_installation(db, installation_id)
    installation.auto_upgrade = bool(body.auto_upgrade)
    installation.updated_at = _now()
    _append_audit(
        db,
        actor=body.actor or "system",
        event_type="marketplace.installation.auto_upgrade_set",
        subject_type="product_installation",
        subject_id=installation_id,
        payload={"product_id": installation.product_id, "auto_upgrade": installation.auto_upgrade},
    )
    db.commit()
    db.refresh(installation)
    return installation


@router.post("/installations/{installation_id}/release-channel", response_model=ProductInstallationRead)
def set_release_channel(
    installation_id: str,
    body: ReleaseChannelRequest,
    db: Session = Depends(get_db),
) -> ProductInstallation:
    """Set which (hierarchical) release channel an installation tracks for upgrades."""
    installation = _get_installation(db, installation_id)
    channel = (body.release_channel or "").lower()
    if channel not in VALID_RELEASE_CHANNELS:
        raise HTTPException(
            status_code=400,
            detail=f"release_channel must be one of {sorted(VALID_RELEASE_CHANNELS)}",
        )
    installation.release_channel = channel
    installation.updated_at = _now()
    _append_audit(
        db,
        actor=body.actor or "system",
        event_type="marketplace.installation.release_channel_set",
        subject_type="product_installation",
        subject_id=installation_id,
        payload={"product_id": installation.product_id, "release_channel": channel},
    )
    db.commit()
    db.refresh(installation)
    return installation


@router.delete("/installations/{installation_id}")
def delete_installation(
    installation_id: str,
    body: UninstallRequest = UninstallRequest(),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Permanently delete (uninstall) an installation.

    Mirrors Foundry's irreversible delete: a confirmation is required. Accept either
    ``confirm=true`` or the confirmation phrase ``"delete installation"``. Without
    confirmation the request is rejected with 400.
    """
    installation = _get_installation(db, installation_id)
    confirmed = bool(body.confirm) or (
        (body.confirm_text or "").strip().lower() == "delete installation"
    )
    if not confirmed:
        raise HTTPException(
            status_code=400,
            detail="uninstall requires confirm=true or confirm_text='delete installation'",
        )

    product_id = installation.product_id
    target_project = installation.target_project
    db.delete(installation)
    _append_audit(
        db,
        actor=body.actor or "system",
        event_type="marketplace.installation.deleted",
        subject_type="product_installation",
        subject_id=installation_id,
        payload={"product_id": product_id, "target_project": target_project},
    )
    db.commit()
    return {
        "deleted": True,
        "installation_id": installation_id,
        "product_id": product_id,
        "target_project": target_project,
    }
