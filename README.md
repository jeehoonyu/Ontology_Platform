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
