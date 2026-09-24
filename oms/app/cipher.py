"""
Foundry CIPHER — column / value-level cryptographic operations governed by Channels
and Licenses.

Docs (palantir.com/docs/foundry/cipher):
  * A Cipher Channel describes a protocol: an encryption algorithm + key parameters,
    or a hashing algorithm + secret.
  * A Cipher License is a Foundry resource that controls which cryptographic
    operations a principal may run against a Channel. License TYPES:
        - operational_user : encrypt/decrypt/hash INDIVIDUAL values (decrypt + hash here)
        - data_manager     : full column encrypt + decrypt + hash
        - admin            : manage channels (+ all operations) and key access
  * Encrypted values use the canonical wrapper string:
        CIPHER::<channel-rid>::<ciphertext>::CIPHER
  * Decryption requires a JUSTIFICATION (audit trail / accountability).
  * Supported hashing algorithms: sha256, sha512.

This module PRESERVES the original endpoints/behavior and ADDS the governance,
justification, hashing, and canonical-wrapper features.

Who is asking (R15 of GOAL_REPAIR_2026-08-23). Every operation authorizes the calling
principal against a licence *that principal* holds on the channel. A request body used
to name the principal instead: encrypt and hash skipped the check when it named nobody,
decrypt let an administrator name anyone, and a licence id matched whoever held it.
Granting a licence answered to `edit`, so an editor could issue themselves an `admin`
licence and pass every check after it. Now the grant and channel creation require
`administer`, the operations require `execute` and the caller's own licence, and a
body may name the caller and no one else.
"""

import binascii
import hashlib
import time
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from . import models_action, production_auth
from .database import Base, get_db

router = APIRouter(tags=["cipher"])


# ---------------------------------------------------------------------------
# License types & the operations they govern
# ---------------------------------------------------------------------------

LICENSE_TYPES = {"operational_user", "data_manager", "admin"}

# operation -> set of license types permitted to run it
OPERATION_PERMISSIONS = {
    "encrypt": {"data_manager", "admin"},
    # A token is reversible through the vault (bulk decrypt), so issuing one is an
    # encrypt-class operation.
    "tokenize": {"data_manager", "admin"},
    "decrypt": {"operational_user", "data_manager", "admin"},
    "hash": {"operational_user", "data_manager", "admin"},
    "manage_channels": {"admin"},
}

VALID_HASH_ALGORITHMS = {"sha256", "sha512"}


# ---------------------------------------------------------------------------
# SQLAlchemy models
# ---------------------------------------------------------------------------

class CipherChannel(Base):
    __tablename__ = "cipher_channels"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    mode: Mapped[str] = mapped_column(String, nullable=False)          # "encrypt" | "tokenize"
    key_ref: Mapped[str] = mapped_column(String, nullable=False)
    # The channel's cryptographic algorithm (e.g. "AES-GCM", "sha256"). New column;
    # nullable so existing rows / minimal creates remain valid.
    algorithm: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # When True the channel requires a justification on decrypt (audited). Default
    # False so existing channels / minimal creates stay backward compatible.
    require_justification: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[int] = mapped_column(Integer, default=lambda: int(time.time()))

    licenses: Mapped[List["CipherLicense"]] = relationship(
        "CipherLicense", back_populates="channel", cascade="all, delete-orphan"
    )


class CipherLicense(Base):
    __tablename__ = "cipher_licenses"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    channel_id: Mapped[str] = mapped_column(String, ForeignKey("cipher_channels.id"), nullable=False, index=True)
    principal: Mapped[str] = mapped_column(String, nullable=False)
    # License type governs which operations the grant permits. Defaults to
    # "operational_user" so legacy grants (decrypt-only callers) keep working.
    license_type: Mapped[str] = mapped_column(String, nullable=False, default="operational_user")
    can_decrypt: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[int] = mapped_column(Integer, default=lambda: int(time.time()))

    channel: Mapped["CipherChannel"] = relationship("CipherChannel", back_populates="licenses")


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class CipherChannelCreate(BaseModel):
    id: Optional[str] = None
    display_name: str
    mode: str          # "encrypt" | "tokenize"
    key_ref: str
    algorithm: Optional[str] = None
    require_justification: bool = False


class CipherChannelRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    display_name: str
    mode: str
    key_ref: str
    algorithm: Optional[str] = None
    require_justification: bool = False
    created_at: int


class CipherLicenseCreate(BaseModel):
    principal: str
    license_type: str = "operational_user"
    can_decrypt: bool = True


class CipherLicenseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    channel_id: str
    principal: str
    license_type: str
    can_decrypt: bool
    created_at: int


class EncryptRequest(BaseModel):
    channel_id: str
    value: str
    # The caller is who the authenticated request says. `principal` may repeat the
    # caller's own id and is refused when it names anyone else; `license_id` narrows
    # the check to one of the caller's own licences.
    license_id: Optional[str] = None
    principal: Optional[str] = None


class EncryptResponse(BaseModel):
    ciphertext: str


class TokenizeRequest(BaseModel):
    channel_id: str
    value: str
    license_id: Optional[str] = None
    principal: Optional[str] = None


class TokenizeResponse(BaseModel):
    token: str


class HashRequest(BaseModel):
    channel_id: str
    value: str
    algorithm: str = "sha256"   # sha256 | sha512
    license_id: Optional[str] = None
    principal: Optional[str] = None


class HashResponse(BaseModel):
    algorithm: str
    digest: str


class DecryptRequest(BaseModel):
    channel_id: str
    ciphertext: str
    principal: Optional[str] = None
    # Required only when the channel sets require_justification=True (audited).
    justification: Optional[str] = None
    license_id: Optional[str] = None


class DecryptResponse(BaseModel):
    value: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_channel_or_404(channel_id: str, db: Session) -> CipherChannel:
    channel = db.query(CipherChannel).filter(CipherChannel.id == channel_id).first()
    if not channel:
        raise HTTPException(status_code=404, detail=f"CipherChannel '{channel_id}' not found")
    return channel


def caller_named(caller: production_auth.Principal, named: Optional[str]) -> None:
    """A request may name its caller, and no one else."""
    if named and named != caller.id:
        raise HTTPException(
            status_code=403,
            detail=(f"Cipher operations are authorized for the calling principal '{caller.id}'; "
                    f"a request may not name '{named}'"),
        )


def authorize(
    operation: str,
    channel_id: str,
    db: Session,
    caller: production_auth.Principal,
    license_id: Optional[str] = None,
    named: Optional[str] = None,
) -> CipherLicense:
    """
    The caller's own licence on the channel that permits `operation`, or 403.

    Only licences whose `principal` is the caller count; `license_id` narrows to one of
    them and never reaches someone else's. A decrypt also needs `can_decrypt`.
    """
    caller_named(caller, named)
    query = db.query(CipherLicense).filter(
        CipherLicense.channel_id == channel_id,
        CipherLicense.principal == caller.id,
    )
    if license_id:
        query = query.filter(CipherLicense.id == license_id)
    held = query.all()
    if not held:
        raise HTTPException(
            status_code=403,
            detail=f"Principal '{caller.id}' holds no Cipher license on this channel to perform '{operation}'",
        )
    permitted = OPERATION_PERMISSIONS.get(operation, set())
    usable = [lic for lic in held
              if lic.license_type in permitted and (operation != "decrypt" or lic.can_decrypt)]
    if not usable:
        types = sorted({lic.license_type for lic in held})
        raise HTTPException(
            status_code=403,
            detail=(
                f"License type {', '.join(repr(t) for t in types)} is not permitted to perform "
                f"'{operation}' (requires one of {sorted(permitted)}"
                + (" with decrypt enabled" if operation == "decrypt" else "") + ")"
            ),
        )
    return usable[0]


# ---------------------------------------------------------------------------
# Endpoints — Channels & Licenses
# ---------------------------------------------------------------------------

@router.post("/cipher/channels", response_model=CipherChannelRead)
def create_cipher_channel(body: CipherChannelCreate, db: Session = Depends(get_db),
                          caller: production_auth.Principal = Depends(
                              production_auth.require_permission("administer"))):
    if body.mode not in {"encrypt", "tokenize"}:
        raise HTTPException(status_code=422, detail="mode must be 'encrypt' or 'tokenize'")
    channel_id = body.id or uuid.uuid4().hex
    existing = db.query(CipherChannel).filter(CipherChannel.id == channel_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="CipherChannel already exists")
    channel = CipherChannel(
        id=channel_id,
        display_name=body.display_name,
        mode=body.mode,
        key_ref=body.key_ref,
        algorithm=body.algorithm,
        require_justification=body.require_justification,
        created_at=int(time.time()),
    )
    db.add(channel)
    db.add(models_action.AuditLog(
        id=uuid.uuid4().hex, actor=caller.id, event_type="cipher.channel.created",
        subject_type="cipher_channel", subject_id=channel_id,
        payload={"mode": body.mode, "algorithm": body.algorithm},
    ))
    db.commit()
    db.refresh(channel)
    return channel


@router.get("/cipher/channels", response_model=List[CipherChannelRead])
def list_cipher_channels(db: Session = Depends(get_db)):
    return db.query(CipherChannel).all()


@router.post("/cipher/channels/{channel_id}/licenses", response_model=CipherLicenseRead)
def create_cipher_license(
    channel_id: str,
    body: CipherLicenseCreate,
    db: Session = Depends(get_db),
    caller: production_auth.Principal = Depends(production_auth.require_permission("administer")),
):
    """Grant `body.principal` a licence. Answers to `administer`: a licence is what every
    operation checks, so whoever can issue one holds every operation."""
    _get_channel_or_404(channel_id, db)
    if body.license_type not in LICENSE_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"license_type must be one of {sorted(LICENSE_TYPES)}",
        )
    license_id = uuid.uuid4().hex
    lic = CipherLicense(
        id=license_id,
        channel_id=channel_id,
        principal=body.principal,
        license_type=body.license_type,
        can_decrypt=body.can_decrypt,
        created_at=int(time.time()),
    )
    db.add(lic)
    db.add(models_action.AuditLog(
        id=uuid.uuid4().hex, actor=caller.id, event_type="cipher.license.granted",
        subject_type="cipher_channel", subject_id=channel_id,
        payload={"license_id": license_id, "principal": body.principal,
                 "license_type": body.license_type, "can_decrypt": body.can_decrypt},
    ))
    db.commit()
    db.refresh(lic)
    return lic


# ---------------------------------------------------------------------------
# Endpoints — Operations
# ---------------------------------------------------------------------------

@router.post("/cipher/encrypt", response_model=EncryptResponse)
def encrypt_value(body: EncryptRequest, db: Session = Depends(get_db),
                  caller: production_auth.Principal = Depends(
                      production_auth.require_permission("execute"))):
    channel = _get_channel_or_404(body.channel_id, db)
    if channel.mode != "encrypt":
        raise HTTPException(status_code=422, detail="Channel mode is not 'encrypt'")
    authorize("encrypt", body.channel_id, db, caller, license_id=body.license_id, named=body.principal)

    inner = "enc:" + body.value.encode().hex()
    # Canonical wrapper: CIPHER::<rid>::<ciphertext>::CIPHER
    ciphertext = f"CIPHER::{channel.id}::{inner}::CIPHER"
    return EncryptResponse(ciphertext=ciphertext)


@router.post("/cipher/tokenize", response_model=TokenizeResponse)
def tokenize_value(body: TokenizeRequest, db: Session = Depends(get_db),
                   caller: production_auth.Principal = Depends(
                       production_auth.require_permission("execute"))):
    channel = _get_channel_or_404(body.channel_id, db)
    if channel.mode != "tokenize":
        raise HTTPException(status_code=422, detail="Channel mode is not 'tokenize'")
    authorize("tokenize", body.channel_id, db, caller, license_id=body.license_id, named=body.principal)
    crc = binascii.crc32(body.value.encode()) & 0xFFFFFFFF
    token = "tok_" + format(crc, "08x")
    return TokenizeResponse(token=token)


@router.post("/cipher/hash", response_model=HashResponse)
def hash_value(body: HashRequest, db: Session = Depends(get_db),
               caller: production_auth.Principal = Depends(
                   production_auth.require_permission("execute"))):
    """Deterministic hash of a value, peppered by the channel key_ref. sha256|sha512."""
    channel = _get_channel_or_404(body.channel_id, db)
    if body.algorithm not in VALID_HASH_ALGORITHMS:
        raise HTTPException(
            status_code=422,
            detail=f"algorithm must be one of {sorted(VALID_HASH_ALGORITHMS)}",
        )

    # Every licence type may hash, but only with a licence of the caller's own.
    authorize("hash", body.channel_id, db, caller, license_id=body.license_id, named=body.principal)

    # Pepper with the channel's key reference so digests are channel-scoped yet
    # deterministic for identical (value, channel) pairs.
    material = (body.value + "::" + (channel.key_ref or "")).encode()
    hasher = hashlib.sha256 if body.algorithm == "sha256" else hashlib.sha512
    digest = hasher(material).hexdigest()
    return HashResponse(algorithm=body.algorithm, digest=digest)


@router.post("/cipher/decrypt", response_model=DecryptResponse)
def decrypt_value(body: DecryptRequest, db: Session = Depends(get_db),
                  principal: production_auth.Principal = Depends(
                      production_auth.require_permission("execute"))):
    channel = _get_channel_or_404(body.channel_id, db)
    if channel.mode != "encrypt":
        raise HTTPException(status_code=422, detail="Channel mode is not 'encrypt'")

    # Channels may require a justification on decrypt (audited). Backward compatible:
    # channels without require_justification keep working without one.
    if channel.require_justification and (not body.justification or not body.justification.strip()):
        raise HTTPException(status_code=422, detail="justification is required to decrypt on this channel")

    # The caller's own licence. T3 of GOAL_TENANCY_2026-08-27 stopped a body naming
    # just anyone, and kept naming another principal for `administer` as delegation.
    # R15 removes that too: an administrator who must decrypt grants themselves a
    # licence, which is audited, rather than borrowing someone else's.
    lic = authorize("decrypt", body.channel_id, db, principal,
                    license_id=body.license_id, named=body.principal)

    # Accept both the canonical wrapper and the legacy "enc:" form.
    inner = body.ciphertext
    if inner.startswith("CIPHER::") and inner.endswith("::CIPHER"):
        middle = inner[len("CIPHER::"):-len("::CIPHER")]
        parts = middle.split("::", 1)
        if len(parts) != 2:
            raise HTTPException(status_code=422, detail="Invalid ciphertext format")
        rid, inner = parts
        if rid != body.channel_id:
            raise HTTPException(status_code=422, detail="Ciphertext channel rid mismatch")

    if not inner.startswith("enc:"):
        raise HTTPException(status_code=422, detail="Invalid ciphertext format")
    hex_part = inner[4:]
    try:
        plaintext = bytes.fromhex(hex_part).decode()
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=422, detail=f"Ciphertext decode failed: {exc}")

    db.add(
        models_action.AuditLog(
            id=uuid.uuid4().hex,
            actor=principal.id,
            event_type="cipher.decrypt",
            subject_type="cipher_channel",
            subject_id=body.channel_id,
            payload={
                "principal": principal.id,
                "license_id": lic.id,
                "channel_id": body.channel_id,
                "justification": body.justification,
                "license_type": lic.license_type,
            },
        )
    )
    db.commit()
    return DecryptResponse(value=plaintext)
