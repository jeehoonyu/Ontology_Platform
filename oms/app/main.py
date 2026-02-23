from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
import time

from . import models, schemas, models_action
from .database import engine, get_db
import uuid

models.Base.metadata.create_all(bind=engine)
models_action.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Ontology Metadata Service (OMS)")

@app.get("/")
def read_root():
    return {"status": "ok", "service": "Ontology Metadata Service"}

# --- Object Type Endpoints ---

@app.post("/object-types", response_model=schemas.ObjectType)
def create_object_type(obj: schemas.ObjectTypeCreate, db: Session = Depends(get_db)):
    db_obj = db.query(models.ObjectType).filter(models.ObjectType.id == obj.id).first()
    if db_obj:
        raise HTTPException(status_code=400, detail="ObjectType already exists")
    
    now = int(time.time())
    db_model = models.ObjectType(**obj.model_dump(), created_at=now, updated_at=now)
    db.add(db_model)
    db.commit()
    db.refresh(db_model)
    return db_model

@app.get("/object-types", response_model=List[schemas.ObjectType])
def list_object_types(db: Session = Depends(get_db)):
    return db.query(models.ObjectType).all()

# --- Link Type Endpoints ---

@app.post("/link-types", response_model=schemas.LinkType)
def create_link_type(link: schemas.LinkTypeCreate, db: Session = Depends(get_db)):
    db_obj = db.query(models.LinkType).filter(models.LinkType.id == link.id).first()
    if db_obj:
        raise HTTPException(status_code=400, detail="LinkType already exists")
    
    db_model = models.LinkType(**link.model_dump())
    db.add(db_model)
    db.commit()
    db.refresh(db_model)
    return db_model

@app.get("/link-types", response_model=List[schemas.LinkType])
def list_link_types(db: Session = Depends(get_db)):
    return db.query(models.LinkType).all()

# --- Action Type Endpoints ---

@app.post("/action-types", response_model=schemas.ActionType)
def create_action_type(action: schemas.ActionTypeCreate, db: Session = Depends(get_db)):
    db_obj = db.query(models.ActionType).filter(models.ActionType.id == action.id).first()
    if db_obj:
        raise HTTPException(status_code=400, detail="ActionType already exists")
    
    db_model = models.ActionType(**action.model_dump())
    db.add(db_model)
    db.commit()
    db.refresh(db_model)
    return db_model

@app.get("/action-types", response_model=List[schemas.ActionType])
def list_action_types(db: Session = Depends(get_db)):
    return db.query(models.ActionType).all()

# --- Action Execution Engine ---

@app.post("/actions/execute", response_model=schemas.ActionExecutionResponse)
def execute_action(request: schemas.ActionExecutionRequest, db: Session = Depends(get_db)):
    # 1. Idempotency Check
    existing_key = db.query(models_action.IdempotencyKey).filter(
        models_action.IdempotencyKey.key == request.idempotency_key
    ).first()
    
    if existing_key:
        return schemas.ActionExecutionResponse(
            status="SUCCESS_CACHED",
            message="Action previously executed.",
            outbox_event_id=existing_key.response_payload.get("outbox_event_id") if existing_key.response_payload else None
        )
    
    # 2. Validate Action Type exists (In reality, also validate parameters against rules schema)
    action_type = db.query(models.ActionType).filter(models.ActionType.id == request.action_type_id).first()
    if not action_type:
        raise HTTPException(status_code=404, detail="ActionType not found")

    # 3. Transactional Outbox Pattern: Save state mutation + external event in single transaction
    outbox_id = str(uuid.uuid4())
    
    try:
        # Pseudo-code for state mutation:
        # object_state = update_internal_bitemporal_state(db, request.parameters)
        
        # Write Outbox Event for CDC to propagate to external systems
        outbox_event = models_action.OutboxEvent(
            id=outbox_id,
            action_type_id=request.action_type_id,
            payload=request.parameters,
            status=models_action.ActionStatus.PENDING
        )
        db.add(outbox_event)
        
        # Save Idempotency Key
        response_data = {"outbox_event_id": outbox_id}
        idemp_key = models_action.IdempotencyKey(
            key=request.idempotency_key,
            action_type_id=request.action_type_id,
            response_payload=response_data
        )
        db.add(idemp_key)
        
        # Atomic commit
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Action execution failed: {str(e)}")
        
    return schemas.ActionExecutionResponse(
        status="SUCCESS",
        message="Action processed and outbox event queued.",
        outbox_event_id=outbox_id
    )
