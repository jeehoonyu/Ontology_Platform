# Ontology Platform

An enterprise-scale operational platform that maps data, logic, action, and security into a unified computational graph. This architecture acts as a kinetic "digital twin" of the organization, allowing both human operators and autonomous AI agents to interact with a consistent, auditable "world model" in real-time.

## Architecture Highlights
Based on modern ontology-driven principles (conceptually aligned with systems like Palantir AIP), this backend segregates reading and writing to safely power LLM workflows.

1. **Ontology Metadata Service (OMS)**
   - Built with **FastAPI** and **SQLAlchemy**.
   - Defines the exact semantics of reality via `ObjectType`, `LinkType`, and `ActionType` models.
2. **Kinetic Action Engine**
   - Implements the **Transactional Outbox Pattern** to prevent the "Dual-Write Problem" (ensuring internal ontology states and external network calls, like REST webhooks, never fall out of sync).
   - Utilizes strict **Idempotency Key Engine** caching to guarantee mutations only fire exactly once, even during network retry spikes.
3. **Agent Tooling (AIP Studio Mechanics)**
   - `ObjectQueryTool`: Grounds LLMs with explicitly linked "Context Packs" instead of unstructured vector text searches (Ontology-Aware Generation).
   - `ActionTool`: Safely exposes enterprise actions to the LLM agent, bounded by a strict **Human-in-the-Loop (HITL)** approval mechanism for high-impact mutations.

## Project Structure
- `docker-compose.yml`: Scaffolding for the Data / Materialization Planes (PostgreSQL Bitemporal DB, ClickHouse, Kafka, Debezium CDC).
- `init-db.sql`: PostgreSQL initialization script deploying GiST indices for Bitemporal History state tracking.
- `oms/`: The core Python backend directory housing the `FastAPI` instance.
  - `oms/app/main.py`: Rest API Endpoints.
  - `oms/app/models.py` & `models_action.py`: Database tables and Outbox/Idempotency abstractions.
  - `oms/AgentStudio.py`: Pydantic structured SDK Tools for LLM-to-Ontology mapping.

## Setup & Running Locally

1. **Install Dependencies**
   ```bash
   cd oms
   python -m venv venv
   # On Windows:
   .\venv\Scripts\activate
   # On Mac/Linux:
   # source venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Run the Ontology Metadata API**
   Navigate into the `oms` directory and start the Uvicorn server:
   ```bash
   uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```
   *The Swagger UI is available at `http://127.0.0.1:8000/docs`.*

3. **Test the Idempotency & Action Plane**
   While the server is running, open a new terminal and execute the test scripts:
   ```bash
   cd oms
   python test_actions.py
   ```

4. **Test the Agentic Tooling**
   Simulates LLM function-calling workflows triggering the Human-In-The-Loop mechanism:
   ```bash
   cd oms
   python AgentStudio.py
   ```

## Sample Examples

### 1. Creating an Object Type (REST API)
Creating the semantic definition for an "Employee".
```bash
curl -X 'POST' \
  'http://127.0.0.1:8000/object-types' \
  -H 'Content-Type: application/json' \
  -d '{
  "id": "employee",
  "display_name": "Employee",
  "description": "A company employee",
  "properties": {
    "first_name": {"type": "string"},
    "role": {"type": "string"}
  }
}'
```

### 2. Executing a Kinetic Action (Python)
Showing the Idempotency Key in action to prevent double-execution:
```python
import requests
import uuid

# 1. Generate Idempotency Key for this specific action attempt
idem_key = f"idem_{uuid.uuid4()}"

payload = {
    "action_type_id": "promote_employee",
    "parameters": {"employee_id": "emp_123", "new_role": "Senior Engineer"},
    "idempotency_key": idem_key
}

# 2. First Execution (Succeeds and creates Outbox Event)
response1 = requests.post("http://127.0.0.1:8000/actions/execute", json=payload)
print(response1.json())
# Output: {'status': 'SUCCESS', 'message': 'Action processed and outbox event queued.', 'outbox_event_id': '...'}

# 3. Network Retry Simulation (Same idempotency key is safely caught)
response2 = requests.post("http://127.0.0.1:8000/actions/execute", json=payload)
print(response2.json())
# Output: {'status': 'SUCCESS_CACHED', 'message': 'Action previously executed.', 'outbox_event_id': '...'}
```

### 3. Agent Tool Execution (LLM SDK)
Simulating an LLM reading Context Packs and proposing a mutation.
```python
from AgentStudio import ObjectQueryTool, ActionTool

# 1. LLM reads structured relational graph context (Ontology-Aware Generation)
query_tool = ObjectQueryTool()
context_pack = query_tool.execute("employee", {"role": "Engineer"})

# 2. LLM proposes a kinetic mutation, caught by Human-In-The-Loop (HITL)
action_tool = ActionTool()
result = action_tool.execute("promote_employee", {"employee_id": "obj_1"})
print(result)
# Output: {'status': 'REQUIRES_HUMAN_APPROVAL', 'message': "Action 'promote_employee' staged for HITL review dashboard."}
```
