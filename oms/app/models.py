from typing import List, Optional
from sqlalchemy import String, Integer, JSON, ForeignKey, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base

class ObjectType(Base):
    """
    Semantic definition of a real-world entity or event (e.g., facility, employee)
    """
    __tablename__ = "object_types"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    display_name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String)
    properties: Mapped[dict] = mapped_column(JSON) # Schema of properties
    
    # Audit fields
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class LinkType(Base):
    """
    Semantic relationship between two object types.
    """
    __tablename__ = "link_types"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    display_name: Mapped[str] = mapped_column(String)
    source_object_type_id: Mapped[str] = mapped_column(String, ForeignKey("object_types.id"))
    target_object_type_id: Mapped[str] = mapped_column(String, ForeignKey("object_types.id"))
    cardinality: Mapped[str] = mapped_column(String) # ONE_TO_ONE, ONE_TO_MANY, MANY_TO_MANY
    
    source_type = relationship("ObjectType", foreign_keys=[source_object_type_id])
    target_type = relationship("ObjectType", foreign_keys=[target_object_type_id])


class ActionType(Base):
    """
    Kinetic 'verbs' of the system to safely mutate objects.
    """
    __tablename__ = "action_types"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    display_name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String)
    parameters: Mapped[dict] = mapped_column(JSON) # Expected input schema
    rules: Mapped[dict] = mapped_column(JSON) # Validation and execution logic / side-effects
