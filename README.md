# Ontology Artificial Intelligence Platform

An enterprise-scale operational platform that maps data, logic, action, AI agents, and security into a unified computational graph. This architecture acts as a kinetic "digital twin" of the organization, allowing both human operators and autonomous AI agents to interact with a consistent, auditable world model.

This is an open local implementation of public AIP/Foundry-style architecture patterns. It does not implement Palantir's proprietary platform internals. The design maps public concepts such as ontology objects/links/actions, pipeline hydration, governed action execution, agent tools, evals, lineage, and audit into a compact FastAPI service.

## Architecture Highlights
Based on modern ontology-driven principles, this backend separates the data plane, ontology plane, action plane, and agent plane so AI workflows can read operational context and propose mutations without bypassing governance.

1. **Ontology Metadata Service (OMS)**
   - Built with **FastAPI** and **SQLAlchemy**.
   - Defines the exact semantics of reality via `ObjectType`, `LinkType`, and `ActionType` models.
   - Stores live `ObjectInstance` and `LinkInstance` records as the current operational twin.
   - Adds Object Set filtering, grouped aggregation, and Search Around traversal over ontology links.
   - Supports GIS-ready ontology properties using GeoJSON `geometry` fields.
   - Persists Saved Object Sets for reusable application, map, and agent contexts.
   - Compiles legacy object/link/action metadata into normalized, project-scoped semantic definitions.
   - Records append-only object changes with actor, source, transaction time, valid time, and evidence references.
   - Exposes versioned typed object and graph queries at `/api/v1` with filters, aggregates, temporal reads, GIS radius constraints, masking, and cursor pagination.
2. **Data Plane and Pipeline Builder**
   - `DataAsset` remains the compatibility metadata/resource model; immutable dataset snapshots store bulk rows as Parquet or JSONL in local or S3-compatible storage.
   - Compiled pipeline execution plans preserve schema, field lineage, validation evidence, and optimistic graph-version checks.
   - `PipelineDefinition` steps support `filter`, `normalize`, `classify`, `summarize`, `derive`, `derive_geo_point`, `project`, `map_to_ontology`, and `link_objects`.
   - `PipelineRun` records capture lineage, step metrics, output datasets, and ontology hydration counts.
   - Data Health expectations validate required fields, uniqueness, allowed values, regexes, ranges, types, and row counts.
3. **GIS and Spatial Intelligence**
   - Stores GeoJSON directly on ontology objects for portable map layers.
   - Provides radius search, bounding-box filtering, polygon geofence evaluation, and GeoJSON FeatureCollection export.
   - Supports MGRS encode/decode and MGRS enrichment during pipeline hydration.
   - Persists Foundry-style map layer definitions backed by object types or saved object sets.
   - Docker uses a PostGIS-ready PostgreSQL image and creates an optional `ontology_geometries` mirror table for indexed production materialization.
4. **Kinetic Action Engine**
   - Implements the **Transactional Outbox Pattern** to prevent the "Dual-Write Problem" (ensuring internal ontology states and external network calls, like REST webhooks, never fall out of sync).
   - Utilizes strict **Idempotency Key Engine** caching to guarantee mutations only fire exactly once, even during network retry spikes.
   - Supports `rules.requires_approval`, `rules.risk_level`, and declarative `object_mutations` for governed state changes.
5. **Agent Studio Mechanics**
   - `AgentDefinition` scopes allowed object types, allowed actions, and optional model endpoint metadata.
   - `AgentSession` builds ontology context packs and stages allowed actions for human review.
   - `EvalSuite` and `EvalRun` provide deterministic checks for retrieval and action-proposal behavior.
   - A provider-neutral model gateway supports the deterministic local adapter and explicitly enabled OpenAI-compatible HTTP providers without persisting secrets.
   - `/api/v1/agents/*/tasks` exposes durable, cancellable, retryable agent execution over the shared worker control plane.
6. **Governance, Lineage, and Observability**
   - `ApprovalRequest` enforces human-in-the-loop approval for high-risk actions.
   - `AuditLog` records ontology changes, pipeline runs, approvals, agent sessions, eval runs, and action execution.
   - `ModelEndpoint` stores governed model/provider metadata and retention policy, while the local runtime remains deterministic by default.

## Project Structure
- `docker-compose.yml`: Scaffolding for the Data / Materialization Planes (PostgreSQL Bitemporal DB, ClickHouse, Kafka, Debezium CDC).
- `init-db.sql`: PostgreSQL initialization script deploying GiST indices for Bitemporal History state tracking.
- `oms/`: The core Python backend directory housing the `FastAPI` instance.
  - `oms/app/main.py`: Rest API Endpoints.
  - `oms/app/models.py` & `models_action.py`: Database tables, runtime graph, pipelines, agents, evals, outbox, approvals, and audit abstractions.
  - `oms/app/runtime.py`: Validation, object sets, data health, pipeline execution, ontology hydration, action mutation, context packing, and eval scoring logic.
  - `oms/ontology_cli.py`: generates typed Python and npm SDK artifacts from a published ontology revision (`GET /ontology/registry/{entry_id}/sdk/{language}`).
  - `oms/test_aip_runtime.py`: End-to-end local scenario covering pipeline hydration, agent proposal, approval, action execution, idempotency, and evals.
  - `oms/test_gis_runtime.py`: Spatial scenario covering GeoJSON hydration, radius search, bbox filtering, FeatureCollection export, and geofence evaluation.
  - `oms/test_foundry_gis_features.py`: Foundry-style scenario covering MGRS, saved object sets, map layers, and object profiles.
  - `oms/test_ontology_validation.py`: Conformance scenario covering ontology validation, object-set search, aggregation, Search Around, data expectations, and intentional graph corruption detection.

## Setup & Running Locally

For what this project is trying to reach and how completion is judged, see the tiered
[Goal](docs/GOAL_2026-08-03.md), its [Tier B execution plan](docs/GOAL_TIER_B_2026-08-03.md),
and the [Measurement Contract](docs/TIER_B_MEASUREMENT_CONTRACT.md) that fixes what the
gates mean. The [Standing Goal](docs/GOAL_STANDING.md) is the ongoing discipline that keeps
those claims from outliving their proof; `python oms/audit_evidence_corpus.py` reports how
far the evidence has drifted from the current migration head.

For a self-hosted team pilot with OIDC, TLS, migrations, backup, restore, and upgrade procedures, see [Production Pilot Operations](docs/PRODUCTION_PILOT.md).

For the independent own-data Connect-to-Report acceptance run and tamper-evident two-team evidence gate, see [Independent Evaluator Guide](docs/EXTERNAL_EVALUATOR_GUIDE.md).

For drag/drop editing, typed Pipeline transforms, ontology mappings, Workshop breakpoints, AIP traces, versioning, and recovery, see [Visual Builder Operations](docs/VISUAL_BUILDERS.md).

For durable worker claims, heartbeats, retries, cancellation, timeout recovery, and queue monitoring, see [Asynchronous Execution Runtime](docs/ASYNC_EXECUTION.md).

For normalized semantic definitions, temporal object events, snapshot storage, typed `/api/v1` queries, pipeline plans, and the model gateway, see [OntologyOS Runtime Core](docs/ONTOLOGYOS_RUNTIME_CORE.md). For partition watermarks, late-data quarantine, windows, backpressure, and recoverable stream workers, see [Durable Event-Time Stream Processing](docs/DURABLE_STREAM_PROCESSING.md).

For signed connector, transform, widget, ontology-package, and model-provider extensions, typed SDK contracts, OCI isolation, and the real container rehearsal, see [Signed Plugin Runtime](docs/SIGNED_PLUGIN_RUNTIME.md).

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

3. **Run with Docker Compose**
   The Compose stack now includes the OMS API plus PostGIS-enabled Postgres, ClickHouse, Kafka, and Debezium:
   ```bash
   docker compose up --build oms-api postgres
   ```
   The API is exposed at `http://127.0.0.1:8000/docs`. To run the full data-plane scaffold:
   ```bash
   docker compose up --build
   ```
   If you already initialized `pgdata` with the earlier plain Postgres image, run `CREATE EXTENSION IF NOT EXISTS postgis;` manually or recreate the local `pgdata` volume before relying on native PostGIS tables.

4. **Open the Workspaces**
   The API also serves a compact local operator UI:
   - Map Workspace: `http://127.0.0.1:8000/workspace/map`
   - AIP Workspace: `http://127.0.0.1:8000/workspace/aip`

   Use **Bootstrap** in the top bar to load the maintenance ontology, GIS features, saved object set, map layer, agents, and eval suite. The map workspace uses Leaflet basemaps with local ontology overlays for MGRS decode, radius search, geofence evaluation, feature collections, and object profiles. Basemap tiles require network access; operational overlays and the canvas fallback still render from local API data. The AIP workspace exercises ontology context loading, Assist, Agent Sessions, Pipeline Builder, approvals, and evals.

5. **Test the Runtime**
   Run the end-to-end AIP-like scenario and the legacy action idempotency check:
   ```bash
   cd oms
   python test_foundry_gis_features.py
   python test_gis_runtime.py
   python test_ontology_validation.py
   python test_aip_runtime.py
   python test_maintenance_copilot.py
   python test_sentinel_operations_graph.py
   python test_actions.py
   ```

6. **Test the Agentic Tooling**
   Exercises the durable agent path: scoped invocation, staged action proposals, and the
   approval gate that stands between a proposal and a mutation.
   ```bash
   cd oms
   python test_aip_agent_async_execution.py
   python test_agent_task_graph.py
   ```

## Sample Examples

### 1. Creating Object Types (REST API)

#### Example A: Employee
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

#### Example B: Buildings & Real Estate
Defining a physical structure like an office building.
```bash
curl -X 'POST' \
  'http://127.0.0.1:8000/object-types' \
  -H 'Content-Type: application/json' \
  -d '{
  "id": "building",
  "display_name": "Corporate Building",
  "description": "A commercial property asset",
  "properties": {
    "facility_code": {"type": "string"},
    "square_footage": {"type": "integer"},
    "max_occupancy": {"type": "integer"},
    "has_helipad": {"type": "boolean"}
  }
}'
```

#### Example C: Agricultural Goods (Fruits)
Modeling perishables for supply chain tracking.
```bash
curl -X 'POST' \
  'http://127.0.0.1:8000/object-types' \
  -H 'Content-Type: application/json' \
  -d '{
  "id": "fruit_batch",
  "display_name": "Fruit Batch",
  "description": "A shipment of agricultural fruit",
  "properties": {
    "fruit_type": {"type": "string"},
    "origin_country": {"type": "string"},
    "harvest_date": {"type": "integer"},
    "is_organic": {"type": "boolean"},
    "weight_kg": {"type": "integer"}
  }
}'
```

#### Example D: Natural Disasters (Events)
Tracking external events that might disrupt the operational twin (e.g., affecting the `building` or delaying the `fruit_batch`).
```bash
curl -X 'POST' \
  'http://127.0.0.1:8000/object-types' \
  -H 'Content-Type: application/json' \
  -d '{
  "id": "natural_disaster",
  "display_name": "Natural Disaster Event",
  "description": "An atmospheric or geographical anomaly affecting operations",
  "properties": {
    "disaster_type": {"type": "string"},  // e.g. "Hurricane", "Earthquake"
    "severity_category": {"type": "integer"}, // e.g. Category 1-5
    "affected_zip_codes": {"type": "json"},
    "active": {"type": "boolean"}
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

### 3. Agent Tool Execution (HTTP)
A scoped agent retrieves governed ontology context and answers from it. Actions are
proposed, never executed inline — a tool bound to an action with `requires_approval` or a
high `risk_level` stages an `ApprovalRequest` and returns it unexecuted.
```python
import requests

requests.post("http://127.0.0.1:8000/domains/maintenance/bootstrap", json={})
invoke = requests.post(
    "http://127.0.0.1:8000/aip/agents/maintenance_ops_agent/invoke",
    json={"prompt": "which work orders are overdue?", "limit": 5},
).json()

print(sorted(invoke))
# ['agent_id', 'answer', 'created_at', 'execution_job_id', 'idempotent_replay',
#  'policy_summary', 'prompt', 'proposed_actions', 'retrieval', 'run_id', 'tool_calls']

print(invoke["proposed_actions"])
# [] — the bootstrap agent has no action tool bound, so it proposes nothing.
# With one bound, each entry carries action_type_id, parameters, requires_approval,
# policy_decision, approval_request_id and executed=False. `oms/test_aip_runtime.py`
# is the worked example, from proposal through approval to execution.
```

## AIP-Style API Surface

The core runtime is available from Swagger at `http://127.0.0.1:8000/docs`.

- `POST /domains/maintenance/bootstrap`: create and optionally hydrate the Maintenance Operations Copilot MVP.
- `GET /domains/maintenance/summary`: inspect facilities, assets, technicians, parts, work orders, and purchase requests.
- `POST /domains/sentinel/bootstrap`: create the Sentinel Operations Graph ontology and governed analyst tools.
- `GET /domains/sentinel/summary`: inspect Sentinel case and evidence object counts.
- `POST /cases`, `GET /cases`, `GET /cases/{case_id}`: create and inspect lawful investigation/incident cases.
- `POST /cases/{case_id}/evidence`: ingest evidence text, extract entities, and preserve provenance.
- `POST /cases/{case_id}/tasks`, `POST /cases/{case_id}/findings`: create analyst tasks and evidence-backed findings.
- `GET /cases/{case_id}/graph`, `GET /cases/{case_id}/timeline`, `GET /cases/{case_id}/provenance`: inspect graph, timeline, and chain-of-custody style metadata.
- `POST /cases/{case_id}/agent/summarize`, `/agent/missing-evidence`, `/agent/suggest-next-steps`, `/agent/draft-report`: analyst copilot helpers.
- `POST /graph/neighbors`, `POST /graph/shortest-path`: graph traversal APIs.
- `POST /object-types`, `POST /link-types`, `POST /action-types`: define ontology semantics.
- `POST /objects`, `POST /links`: create runtime object and link instances.
- `POST /object-sets/search`: Foundry-style object set filtering over object properties, metadata, and lineage.
- `POST /object-sets/aggregate`: grouped count/sum/avg/min/max style metrics over object sets.
- `POST /object-sets/search-around`: generic ontology Search Around traversal over link instances.
- `POST /object-sets/saved`, `GET /object-sets/saved/{id}/objects`: persist and evaluate reusable object sets.
- `GET /ontology/validate`: validate schemas, object instances, links, cardinality, actions, pipelines, agents, logic, automations, and eval suites.
- `GET /objects/{object_type_id}/{object_id}/profile`: object-centric profile with linked objects, link metrics, and spatial metadata.
- `POST /gis/spatial-query`: query ontology objects by GeoJSON geometry, radius, bbox, polygon, and normal object filters.
- `POST /gis/feature-collection`: export spatial ontology objects as a GeoJSON `FeatureCollection`.
- `POST /gis/geofence/evaluate`: evaluate which spatial objects fall inside or outside a polygon or bbox geofence.
- `POST /gis/mgrs/encode`, `POST /gis/mgrs/decode`: convert between WGS84 latitude/longitude and MGRS grid references.
- `POST /gis/map-layers`, `GET /gis/map-layers/{layer_id}/features`: define and render Foundry-style ontology map layers.
- `POST /data-assets`: register JSON datasets.
- `POST /data-assets/{asset_id}/expectations/run`: run Data Health expectations against a registered dataset.
- `POST /pipelines`, `POST /pipelines/{pipeline_id}/run`: clean, enrich, classify, summarize, and hydrate datasets into ontology objects.
- `POST /actions/execute`: validate parameters, stage high-risk actions for approval, mutate objects, write outbox events, and cache idempotent responses.
- `GET /approvals`, `POST /approvals/{approval_id}/decision`: approve or reject high-impact action requests.
- `POST /agents`, `POST /agents/{agent_id}/sessions`: create scoped ontology-grounded agents and generate context/action plans.
- `GET /aip/tools`: inspect the implemented local equivalents of public AIP tools.
- `POST /aip/assist/query`: context-aware local AIP Assist equivalent.
- `POST /aip/pipeline-builder/generate`: prompt-to-pipeline-step suggestions.
- `POST /aip/document-intelligence/extract`: schema/regex document extraction.
- `POST /aip/notepad/transform`: local spellcheck/shorten/modify/translate-intent transforms.
- `GET /mcp/context`: MCP-style context export for external agents/IDEs.
- `POST /threads`, `POST /threads/{thread_id}/messages`: AIP Threads-style ad-hoc workspaces.
- `POST /logic-functions`, `POST /logic-functions/{logic_id}/run`: AIP Logic-style block workflows.
- `POST /automations`, `POST /automations/{automation_id}/run`: Automate-style condition/effect evaluation.
- `POST /scheduler/generate-cron`: prompt-to-cron helper.
- `POST /eval-suites`, `POST /eval-suites/{suite_id}/run`: evaluate agent retrieval and action proposal behavior.
- `GET /audit-logs`: inspect governance and lineage events.

## Public AIP Tool Coverage

Public Palantir docs list AIP Assist, AIP Logic, AIP Chatbot Studio, AIP Evals, AIP Threads, Palantir MCP, AIP Model Catalog, AIP Document Intelligence, AIP features in Pipeline Builder, Automate integration, Scheduler, and Notepad features. This repo implements local equivalents for those tools with deterministic Python logic and ontology-backed state:

- AIP Assist: `/aip/assist/query`
- AIP Chatbot Studio / Agent Studio: `/agents`, `/agents/{agent_id}/sessions`
- AIP Logic: `/logic-functions`, `/logic-functions/{logic_id}/run`
- AIP Evals: `/eval-suites`, `/eval-suites/{suite_id}/run`
- AIP Threads: `/threads`
- Palantir MCP-style context: `/mcp/context`
- AIP Model Catalog: `/model-endpoints`
- AIP Document Intelligence: `/aip/document-intelligence/extract`
- Pipeline Builder AIP assistance: `/aip/pipeline-builder/generate`
- Automate and Scheduler: `/automations`, `/scheduler/generate-cron`
- Notepad AIP transforms: `/aip/notepad/transform`
- Ontology Object Sets and Search Around: `/object-sets/search`, `/object-sets/aggregate`, `/object-sets/search-around`
- Data Health Expectations: `/data-assets/{asset_id}/expectations/run`
- Ontology Integrity Validation: `/ontology/validate`
- GIS Spatial Intelligence: `/gis/spatial-query`, `/gis/feature-collection`, `/gis/geofence/evaluate`
- MGRS Grid Reference: `/gis/mgrs/encode`, `/gis/mgrs/decode`
- Foundry-style Map Layers and Saved Object Sets: `/object-sets/saved`, `/gis/map-layers`
- Object Views: `/objects/{object_type_id}/{object_id}/profile`

These endpoints are intentionally local approximations. They provide the same architectural roles for development and testing, but they do not claim compatibility with Palantir's proprietary APIs, model-routing plane, UI builders, security services, or managed infrastructure.

## Extended Foundry Tool Coverage (New Modules)

To complete the public Foundry tool surface, the platform adds 18 self-contained router modules under `oms/app/`. Each follows the existing conventions (shared `Base`, SQLAlchemy 2.0 models, `APIRouter`, deterministic local logic) and is mounted in `main.py`. A full docs-vs-implementation matrix lives in [`foundry-docs/COVERAGE.md`](foundry-docs/COVERAGE.md), and end-to-end behavior is verified by `oms/test_foundry_tools.py` (82 endpoint assertions).

**Ontology depth**
- `ontology_interfaces.py` — Interfaces (polymorphic contracts) & shared property types: `/interfaces`, `/interfaces/{id}/implementers`, `/interfaces/{id}/check-object-type`, `/shared-property-types`.
- `ontology_value_types.py` — Value types & structs with constraint validation: `/value-types`, `/value-types/{id}/validate`.
- `ontology_versioning.py` — Ontology Manager branches & proposals: `/ontology/branches`, `/ontology/proposals`, `.../submit`, `.../decision`, `.../merge`.
- `ontology_functions.py` — Typed Functions on Objects: `/ontology-functions`, `/ontology-functions/{id}/run`.

**Data integration**
- `connectivity.py` — Data Connection sources, syncs, exports: `/connections/sources`, `/connections/sources/{id}/syncs`, `/connections/syncs/{id}/run`, `/connections/exports`.
- `streaming.py` — Streams: `/streams`, `/streams/{id}/publish`, `/streams/{id}/records`, `/streams/{id}/archive`.
- `schedules.py` — Schedules & builds: `/schedules`, `/schedules/{id}/trigger`, `/builds`.
- `media_sets.py` — Media sets & extraction: `/media-sets`, `/media-sets/{id}/items`, `/media-items/{id}/extract`.
- `lineage.py` — Cross-resource lineage graph: `/lineage/graph`, `/lineage/resource/{kind}/{id}`.

**Analytics & applications**
- `analytics.py` — Contour, Quiver, Fusion: `/analytics/contour(.../run)`, `/analytics/quiver(.../compute)`, `/analytics/fusion(.../evaluate)`.
- `apps.py` — Workshop, Slate, Carbon: `/apps/workshop(.../render)`, `/apps/slate`, `/apps/carbon`.

**Modeling**
- `modeling.py` — Modeling Objectives, training, deployments: `/modeling/objectives(.../train,.../release)`, `/modeling/deployments(.../infer)`.

**Observability**
- `observability.py` — Monitoring views, traces, metrics: `/observability/monitoring-views(.../evaluate)`, `/observability/traces`, `/observability/metrics`, `/observability/summary`.

**Security & governance**
- `security_access.py` — Projects, roles, permissions: `/projects`, `/roles`, `/projects/{id}/grants`, `/access/check`.
- `security_data.py` — Markings, restricted views, scanner, retention, checkpoints: `/markings(.../grant)`, `/restricted-views(.../apply)`, `/governance/scan`, `/retention-policies`, `/checkpoints`.
- `cipher.py` — Encrypt/tokenize/decrypt with licenses: `/cipher/channels`, `/cipher/encrypt`, `/cipher/tokenize`, `/cipher/decrypt`.

**Delivery & dev toolchain**
- `marketplace.py` — DevOps products & Marketplace: `/devops/products(.../releases)`, `/marketplace`, `/marketplace/{id}/install`, `/installations/{id}/upgrade`.
- `aip_extras.py` — AIP Model Catalog/BYOM, Compute Modules, OSDK generator: `/aip/model-catalog`, `/aip/model-catalog/byom`, `/compute-modules(.../invoke)`, `/osdk/generate`.
- `dev_toolchain.py` — Code Repositories, Workspaces, Workbook: `/code-repositories` (branches, files, commits, `.../checks/run`, `.../merge`), `/code-workspaces(.../status)`, `/code-workbooks(.../run)`.
- `notepad.py` — Notepad documents & reports with live ontology embeds: `/notepad/documents`, `.../blocks`, `.../render`, `.../export`.

> With these two modules added, **every tool documented in `foundry-docs-full/` has a working local equivalent** (100% breadth). The app now exposes **~796 routes** across **~209 tables**, verified by **70 test files (all green)** — see `foundry-docs/COVERAGE.md` for the full pass-by-pass ledger.

## Enhancements — query pagination, real file upload, operator UI

- **Object-set query pushdown + pagination.** `POST /object-sets/search` narrows simple equality predicates in SQL (`json_extract`) before the Python filter pass (identical results, faster), and supports `offset` / opaque `cursor` pagination with an opt-in `with_total` (set `with_total: false` to skip the full-scan count). The response adds `next_cursor`.
- **Real file upload + object storage.** `POST /data-assets/{id}/upload` ingests **CSV / JSON / JSONL / Parquet** (multipart) into `records` with an inferred `asset_schema`, keeping the raw file in object storage; `GET /data-assets/{id}/download` returns it. `POST /media-sets/{id}/items/upload` stores binary media; `GET /media-items/{id}/content` streams it. Storage root is configurable via `STORAGE_DIR` (default `./storage`). Requires `python-multipart`; Parquet needs the optional `pyarrow`.
- **React operator workspaces.** The React shell (served at `/workspace`) gains eight new operator UIs over the API: **Control Panel** (orgs/users/groups/roles/tokens), **Security & Governance** (markings/CBAC/projects/cipher), **Automate**, **Data & Media** (file upload), **Vertex** (graph explorer), **Fusion** (spreadsheet), **Analytics** (Object Explorer charts + Contour), and **Delivery** (Marketplace/DevOps/code). Build with `cd frontend && npm ci && npm run build`; the built bundle is served by the FastAPI process.

> Note on local environment: the bundled `oms/venv` was created for Python 3.13 on another machine and does not run here. Use Python 3.12 (`venv312`) or recreate the venv with `python -m venv venv && pip install -r requirements.txt`. The full suite runs with: `for t in test_*.py; do python $t; done`.

## Ontology Validation Strategy

The fastest way to determine whether this project works like the intended idea is not to compare proprietary code. It is to define behavioral contracts and run them continuously:

- `GET /ontology/validate` proves that object types, object instances, link types, link instances, action mutations, pipelines, agents, logic functions, automations, and eval suites refer to real resources and obey declared cardinality.
- `POST /data-assets/{asset_id}/expectations/run` proves that pipeline inputs and outputs satisfy data contracts before they hydrate the ontology.
- `POST /object-sets/search` and `/object-sets/search-around` prove that applications and agents can retrieve the same operational graph context through generic tools, not one-off domain code.
- `oms/test_ontology_validation.py` includes both a healthy graph assertion and an intentional broken-link insertion to verify that the validator catches corrupted ontology state.

## GIS Spatial Layer

GIS is implemented as a first-class ontology capability. Any object type can declare a GeoJSON field:

```json
{
  "geometry": {"type": "geometry"}
}
```

The geometry value follows GeoJSON coordinate order:

```json
{
  "type": "Point",
  "coordinates": [-122.4012, 37.7924]
}
```

The pipeline DSL can derive that geometry from raw longitude/latitude fields:

```json
{
  "operation": "derive_geo_point",
  "longitude_field": "longitude",
  "latitude_field": "latitude",
  "target_field": "geometry"
}
```

The same record can also derive MGRS:

```json
{
  "operation": "derive_mgrs",
  "geometry_field": "geometry",
  "target_field": "mgrs",
  "precision": 5
}
```

This keeps the reference implementation portable across SQLite and PostgreSQL. For heavier workloads, Docker now uses `postgis/postgis:15-3.4`, enables the `postgis` extension, and creates `ontology_geometries` as an optional native spatial mirror with a GiST index.

Useful checks:

- `python oms/test_foundry_gis_features.py`: validates MGRS, saved object sets, map layer rendering, object profiles, and validator coverage.
- `python oms/test_gis_runtime.py`: validates GIS hydration, radius query, bbox query, FeatureCollection export, and geofence evaluation.
- `GET /ontology/validate`: validates declared `geometry` fields as GeoJSON.
- `POST /gis/feature-collection`: returns map-ready GeoJSON for any spatial object type.
- `POST /gis/mgrs/encode`: returns an MGRS grid reference for a latitude/longitude.

## Foundry-Style Application Layer

The platform now includes three reusable application-building primitives inspired by public Foundry application patterns:

- Saved Object Sets: persist object type plus filters so an exploration can be reused in dashboards, agents, and map layers.
- Map Layers: define a geospatial object layer with `geometry_field`, optional saved object set, style metadata, and FeatureCollection rendering.
- Object Profiles: return object properties, inbound/outbound links, linked objects, basic metrics, and spatial/MGRS metadata for an object-centric view.

Example map layer flow:

```bash
curl -X POST "http://127.0.0.1:8000/object-sets/saved" \
  -H "Content-Type: application/json" \
  -d '{"id":"critical_assets","display_name":"Critical Assets","object_type_id":"asset","filters":{"criticality":"high"}}'

curl -X POST "http://127.0.0.1:8000/gis/map-layers" \
  -H "Content-Type: application/json" \
  -d '{"id":"critical_asset_layer","display_name":"Critical Asset Layer","object_type_id":"asset","saved_object_set_id":"critical_assets","style":{"marker_color":"#d43f3a"}}'

curl "http://127.0.0.1:8000/gis/map-layers/critical_asset_layer/features"
```

## Maintenance Operations Copilot MVP

The first focused product direction is a maintenance/facilities operations copilot. It turns raw asset and work-order data into an operational ontology, then lets an agent propose governed actions.

Bootstrap the domain:
```bash
curl -X POST "http://127.0.0.1:8000/domains/maintenance/bootstrap" \
  -H "Content-Type: application/json" \
  -d '{"actor": "demo", "run_pipelines": true}'
```

The bootstrap creates:

- Object types: `facility`, `asset`, `technician`, `part`, `work_order`, `purchase_request`
- Link types: facility-to-asset, asset-to-work-order, technician-to-work-order
- Actions: `assign_technician`, `escalate_work_order`, `create_purchase_request`, `close_work_order`
- Seed datasets and hydration pipelines, including GeoJSON facility/asset locations
- Agent: `maintenance_ops_agent`
- Logic workflow: `maintenance_triage_logic`
- Eval suite: `maintenance_ops_agent_eval`
- Automation: `maintenance_critical_work_order_monitor`

Validate the product loop:
```text
Raw maintenance data
→ pipeline classification and summarization
→ ontology objects
→ agent context
→ proposed assignment/escalation/procurement action
→ approval gate for high-risk changes
→ object mutation, outbox event, audit log, eval result
```

Run the focused conformance test:
```bash
cd oms
python test_maintenance_copilot.py
```

## Sentinel Operations Graph MVP

The second focused product direction is a Gotham-ish, lawful operational intelligence workspace for enterprise incident response, fraud review, cyber triage, disaster operations, compliance investigations, and maintenance command centers. It is not a surveillance, targeting, or enforcement system.

Bootstrap the domain:
```bash
curl -X POST "http://127.0.0.1:8000/domains/sentinel/bootstrap" \
  -H "Content-Type: application/json" \
  -d '{"actor": "demo"}'
```

The bootstrap creates:

- Object types: `sentinel_case`, `sentinel_evidence_document`, `sentinel_observation`, `sentinel_entity`, `sentinel_location`, `sentinel_event`, `sentinel_task`, `sentinel_finding`, `sentinel_decision`, `sentinel_report`
- Link types with provenance/confidence: `case_contains_evidence`, `evidence_mentions_entity`, `case_has_task`, `case_has_finding`, `case_has_decision`, `case_has_report`, `case_has_observation`, `case_has_event`, `evidence_supports_observation`, `observation_supports_finding`, `finding_supports_decision`, `event_occurred_at_location`, `entity_associated_with_entity`
- Governed actions: `publish_sentinel_report`, `close_sentinel_case`
- Agent: `sentinel_analyst_agent`
- Eval suite: `sentinel_analyst_eval`

Validate the intelligence loop:
```text
Raw evidence text
→ document extraction
→ entity objects
→ provenance-bearing graph links
→ case graph / timeline / shortest path
→ analyst copilot summary and missing-evidence checks
→ draft report
→ approval-gated publication
→ audit log and eval result
```

Run the focused conformance test:
```bash
cd oms
python test_sentinel_operations_graph.py
```

## Public Design Inputs

The implementation is based on public Palantir documentation patterns:

- Foundry data flow: source systems to datasets, transforms, ontology objects/links, applications, decisions, and actions.
- Ontology backend: semantic elements such as objects/properties/links and kinetic elements such as actions/functions/security.
- AIP: Assist, Chatbot Studio, Logic, Evals, Threads, MCP, Model Catalog, Document Intelligence, Pipeline Builder assistance, Notepad, Scheduler, Automate, and governance.
- Architecture: secure model integration, observability, action logging, chained workflow tracing, and ontology-backed automation.
