from sqlalchemy import Column, String, JSON, Integer, ForeignKey, Enum, Boolean
from .database import Base
import enum
import time

class ActionStatus(str, enum.Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

class ApprovalStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"

class OutboxEvent(Base):
    """
    Transactional Outbox Pattern for propagating state changes to external systems via CDC.
    """
    __tablename__ = "action_outbox"

    id = Column(String, primary_key=True) # UUID
    project_id = Column(String, default="default", index=True, nullable=False)
    action_type_id = Column(String, index=True)
    payload = Column(JSON) # The parameters of the action
    status = Column(String, default=ActionStatus.PENDING.value)
    created_at = Column(Integer, default=lambda: int(time.time()))

# How long an action's idempotency key answers a retry with its first result (R11).
IDEMPOTENCY_TTL_SECONDS = 24 * 60 * 60


class IdempotencyKey(Base):
    """
    Strict Idempotency Validation to prevent dual-writes on network retries.

    A key is a project's, and lasts a day (R11 of GOAL_REPAIR_2026-08-23). It was one global
    namespace that never expired: a key another project had used was refused with a message
    saying so, and a key used once was held forever.
    """
    __tablename__ = "idempotency_keys"

    project_id = Column(String, default="default", index=True, nullable=False, primary_key=True)
    key = Column(String, primary_key=True)
    action_type_id = Column(String, nullable=False)
    response_payload = Column(JSON, nullable=True) # Cached success response
    created_at = Column(Integer, default=lambda: int(time.time()))
    expires_at = Column(Integer, nullable=True, index=True)

class ApprovalRequest(Base):
    """
    Human-in-the-loop gate for high-impact actions proposed by users or agents.
    """
    __tablename__ = "approval_requests"

    id = Column(String, primary_key=True)
    project_id = Column(String, default="default", index=True, nullable=False)
    action_type_id = Column(String, ForeignKey("action_types.id"), index=True, nullable=False)
    requester = Column(String, nullable=False, default="system")
    parameters = Column(JSON, nullable=False)
    status = Column(String, default=ApprovalStatus.PENDING.value)
    reason = Column(String, nullable=True)
    created_at = Column(Integer, default=lambda: int(time.time()))
    decided_at = Column(Integer, nullable=True)
    # When the approved action ran, and the outbox event that records it. An approval runs
    # its action once; it was checked only for being APPROVED, so it ran again under every
    # new idempotency key (R11). `status` stays APPROVED, which callers read as the decision.
    consumed_at = Column(Integer, nullable=True)
    consumed_by_outbox_event_id = Column(String, nullable=True)

class AuditLog(Base):
    """
    Append-only control plane log for lineage, governance, and observability.
    """
    __tablename__ = "audit_logs"

    id = Column(String, primary_key=True)
    actor = Column(String, nullable=False, default="system")
    event_type = Column(String, index=True, nullable=False)
    subject_type = Column(String, index=True, nullable=False)
    subject_id = Column(String, index=True, nullable=False)
    payload = Column(JSON, nullable=True)
    created_at = Column(Integer, default=lambda: int(time.time()))
