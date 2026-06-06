import uuid
import os
import tempfile

tmpdir = tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'actions.db')}"

from app.database import SessionLocal, engine
from app import models, models_action
from app.schemas import ActionExecutionRequest
from app.main import execute_action

models.Base.metadata.create_all(bind=engine)
models_action.Base.metadata.create_all(bind=engine)

db = SessionLocal()

# 1. Create an Action Type
action_id = "promote_employee"
existing_action = db.query(models.ActionType).filter_by(id=action_id).first()
if not existing_action:
    action = models.ActionType(
        id=action_id,
        display_name="Promote Employee",
        parameters={"employee_id": "string", "new_role": "string"},
        rules={}
    )
    db.add(action)
    db.commit()

# 2. Execute Action (First time) - should create outbox event
idem_key = f"idem_{uuid.uuid4()}"
req = ActionExecutionRequest(
    action_type_id="promote_employee",
    parameters={"employee_id": "emp_123", "new_role": "Senior Engineer"},
    idempotency_key=idem_key
)

print("--- INITIAL EXECUTION ---")
res1 = execute_action(req, db)
print("Response:", res1.model_dump())

# Check Outbox
outbox_events = db.query(models_action.OutboxEvent).all()
print(f"Total Outbox Events: {len(outbox_events)}")
assert len(outbox_events) == 1

# 3. Execute Action Again (Same Idempotency Key) - should return cached
print("\n--- RETRY EXECUTION (IDEMPOTENCY) ---")
res2 = execute_action(req, db)
print("Response:", res2.model_dump())
assert res2.status == "SUCCESS_CACHED"

db.close()
engine.dispose()
tmpdir.cleanup()
print("\nTest passing if second response has status SUCCESS_CACHED.")
