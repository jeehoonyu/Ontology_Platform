from pydantic import BaseModel, ConfigDict
from typing import Optional, Dict, Any, List

# --- COMMON ---
class ResourceBase(BaseModel):
    id: str
    display_name: str
    description: Optional[str] = None

# --- OBJECT TYPES ---
class ObjectTypeCreate(ResourceBase):
    properties: Dict[str, Any]

class ObjectType(ObjectTypeCreate):
    created_at: int
    updated_at: int
    
    model_config = ConfigDict(from_attributes=True)

# --- LINK TYPES ---
class LinkTypeCreate(ResourceBase):
    source_object_type_id: str
    target_object_type_id: str
    cardinality: str # ONE_TO_ONE, ONE_TO_MANY, MANY_TO_MANY

class LinkType(LinkTypeCreate):
    model_config = ConfigDict(from_attributes=True)

# --- ACTION TYPES ---
class ActionTypeCreate(ResourceBase):
    parameters: Dict[str, Any]
    rules: Dict[str, Any]

class ActionType(ActionTypeCreate):
    model_config = ConfigDict(from_attributes=True)

# --- ACTION EXECUTION ---
class ActionExecutionRequest(BaseModel):
    action_type_id: str
    parameters: Dict[str, Any]
    idempotency_key: str

class ActionExecutionResponse(BaseModel):
    status: str
    message: str
    outbox_event_id: Optional[str] = None
