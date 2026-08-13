"""
Cipher — key rotation, reversible tokenization vault & bulk column transforms
(deep-fidelity pass 8, Security/Cipher).

Deepens Cipher beyond single-value encrypt/tokenize/decrypt with documented
mechanics: **key versions** (rotation), a **tokenization vault** (consistent,
reversible tokens), and **bulk column transforms** over a record set with governed
(license-gated) decryption. Additive; deterministic; local (not real cryptography).
"""
import binascii
import time
import uuid
from typing import Optional, List, Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import String, Integer, Boolean
from sqlalchemy.orm import Mapped, mapped_column, Session
from pydantic import BaseModel, Field

from .database import Base, get_db
from . import models_action, cipher as _cipher

router = APIRouter(tags=["cipher_ops"])


def _now() -> int:
    return int(time.time())


class CipherKeyVersion(Base):
    __tablename__ = "cipher_key_versions"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    channel_id: Mapped[str] = mapped_column(String, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    key_ref: Mapped[str] = mapped_column(String)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[int] = mapped_column(Integer)


class CipherToken(Base):
    __tablename__ = "cipher_token_vault"
    token: Mapped[str] = mapped_column(String, primary_key=True)
    channel_id: Mapped[str] = mapped_column(String, index=True)
    value: Mapped[str] = mapped_column(String)
    created_at: Mapped[int] = mapped_column(Integer)


def _enc(value: str) -> str:
    return "enc:" + value.encode("utf-8").hex()


def _dec(ciphertext: str) -> str:
    return bytes.fromhex(ciphertext[4:]).decode("utf-8") if ciphertext.startswith("enc:") else ciphertext


def _token(value: str) -> str:
    return "tok_" + format(binascii.crc32(value.encode("utf-8")) & 0xFFFFFFFF, "08x")


def _require_channel(db: Session, channel_id: str):
    ch = db.get(_cipher.CipherChannel, channel_id)
    if not ch:
        raise HTTPException(status_code=404, detail=f"Cipher channel '{channel_id}' not found")
    return ch


def _can_decrypt(db: Session, channel_id: str, principal: str) -> bool:
    return db.query(_cipher.CipherLicense).filter(
        _cipher.CipherLicense.channel_id == channel_id,
        _cipher.CipherLicense.principal == principal,
        _cipher.CipherLicense.can_decrypt == True,  # noqa: E712
    ).first() is not None


class BulkTransformRequest(BaseModel):
    channel_id: str
    records: List[Dict[str, Any]]
    field: str
    mode: str                       # encrypt | tokenize | decrypt
    principal: Optional[str] = None


@router.post("/cipher/channels/{channel_id}/rotate")
def rotate_key(channel_id: str, db: Session = Depends(get_db)):
    _require_channel(db, channel_id)
    versions = db.query(CipherKeyVersion).filter(CipherKeyVersion.channel_id == channel_id).all()
    for v in versions:
        v.active = False
    next_version = (max((v.version for v in versions), default=0)) + 1
    kv = CipherKeyVersion(id=uuid.uuid4().hex, channel_id=channel_id, version=next_version,
                          key_ref=f"key-v{next_version}-{uuid.uuid4().hex[:8]}", active=True, created_at=_now())
    db.add(kv)
    db.add(models_action.AuditLog(id=uuid.uuid4().hex, actor="system", event_type="cipher.key.rotated",
                                  subject_type="cipher_channel", subject_id=channel_id, payload={"version": next_version}))
    db.commit()
    return {"channel_id": channel_id, "active_version": next_version, "key_ref": kv.key_ref}


@router.get("/cipher/channels/{channel_id}/keys")
def list_keys(channel_id: str, db: Session = Depends(get_db)):
    _require_channel(db, channel_id)
    rows = db.query(CipherKeyVersion).filter(CipherKeyVersion.channel_id == channel_id).order_by(CipherKeyVersion.version.asc()).all()
    return [{"version": r.version, "key_ref": r.key_ref, "active": r.active, "created_at": r.created_at} for r in rows]


@router.post("/cipher/bulk-transform")
def bulk_transform(body: BulkTransformRequest, db: Session = Depends(get_db)):
    _require_channel(db, body.channel_id)
    if body.mode == "decrypt" and not _can_decrypt(db, body.channel_id, body.principal or ""):
        raise HTTPException(status_code=403, detail="principal lacks a decrypt license for this channel")

    out: List[Dict[str, Any]] = []
    transformed = 0
    for rec in body.records:
        new = dict(rec)
        if body.field in new and new[body.field] is not None:
            raw = str(new[body.field])
            if body.mode == "encrypt":
                new[body.field] = _enc(raw)
            elif body.mode == "tokenize":
                tok = _token(raw)
                if not db.get(CipherToken, tok):
                    db.add(CipherToken(token=tok, channel_id=body.channel_id, value=raw, created_at=_now()))
                new[body.field] = tok
            elif body.mode == "decrypt":
                if raw.startswith("enc:"):
                    new[body.field] = _dec(raw)
                elif raw.startswith("tok_"):
                    vault = db.get(CipherToken, raw)
                    new[body.field] = vault.value if vault else None
            else:
                raise HTTPException(status_code=422, detail=f"Unknown mode '{body.mode}'")
            transformed += 1
        out.append(new)

    db.add(models_action.AuditLog(id=uuid.uuid4().hex, actor=body.principal or "system",
                                  event_type=f"cipher.bulk.{body.mode}", subject_type="cipher_channel",
                                  subject_id=body.channel_id, payload={"field": body.field, "rows": transformed}))
    db.commit()
    return {"channel_id": body.channel_id, "mode": body.mode, "field": body.field,
            "transformed": transformed, "records": out}
