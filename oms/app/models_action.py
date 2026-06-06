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

    id = Column(String, primary_key=True, index=True) # UUID
    action_type_id = Column(String, index=True)
    payload = Column(JSON) # The parameters of the action
    status = Column(String, default=ActionStatus.PENDING.value)
    created_at = Column(Integer, default=lambda: int(time.time()))

class IdempotencyKey(Base):
    """
    Strict Idempotency Validation to prevent dual-writes on network retries.
    """
    __tablename__ = "idempotency_keys"

    key = Column(String, primary_key=True, index=True)
    action_type_id = Column(String, nullable=False)
    response_payload = Column(JSON, nullable=True) # Cached success response
    created_at = Column(Integer, default=lambda: int(time.time()))

class ApprovalRequest(Base):
    """
    Human-in-the-loop gate for high-impact actions proposed by users or agents.
    """
    __tablename__ = "approval_requests"

    id = Column(String, primary_key=True, index=True)
    action_type_id = Column(String, ForeignKey("action_types.id"), index=True, nullable=False)
    requester = Column(String, nullable=False, default="system")
    parameters = Column(JSON, nullable=False)
    status = Column(String, default=ApprovalStatus.PENDING.value)
    reason = Column(String, nullable=True)
    created_at = Column(Integer, default=lambda: int(time.time()))
    decided_at = Column(Integer, nullable=True)

class AuditLog(Base):
    """
    Append-only control plane log for lineage, governance, and observability.
    """
    __tablename__ = "audit_logs"

    id = Column(String, primary_key=True, index=True)
    actor = Column(String, nullable=False, default="system")
    event_type = Column(String, index=True, nullable=False)
    subject_type = Column(String, index=True, nullable=False)
    subject_id = Column(String, index=True, nullable=False)
    payload = Column(JSON, nullable=True)
    created_at = Column(Integer, default=lambda: int(time.time()))
