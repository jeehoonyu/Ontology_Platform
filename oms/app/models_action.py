from sqlalchemy import Column, String, JSON, Integer, ForeignKey, Enum, Boolean
from .database import Base
import enum
import time

class ActionStatus(str, enum.Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

class OutboxEvent(Base):
    """
    Transactional Outbox Pattern for propagating state changes to external systems via CDC.
    """
    __tablename__ = "action_outbox"

    id = Column(String, primary_key=True, index=True) # UUID
    action_type_id = Column(String, index=True)
    payload = Column(JSON) # The parameters of the action
    status = Column(String, default=ActionStatus.PENDING)
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
