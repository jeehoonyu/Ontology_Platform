# Docs-Grounded Validation Report

## Summary

This repository implements a local deterministic analog of public Palantir Foundry/AIP concepts. It does not copy Palantir code, claim proprietary API compatibility, or reproduce managed Foundry infrastructure. Validation is based on public docs, the local `foundry-docs` and `foundry-docs-full` corpus, and executable behavior tests.

Current result:

- Breadth: strong coverage across ontology, actions, AIP Logic, Workshop, Object Explorer, Pipeline Builder, GIS, data health, modeling, ModelOps, decision intelligence, ops, investigations, reliability, security, governance, global search, eventing, policies, timelines, and graph overview.
- Outcome proof: the Asset Reliability Command Center provides one complete local workflow from raw maintenance data to governed operational decision, incident, and report.
- Authoring fidelity: Pipeline Builder has project-owned graphs, backend-enforced read/edit/execute/deploy permissions, structured transforms, lineage, previews, spatial/MGRS execution, and project-bound queued execution. Ontology Manager provides drag/drop mapping, hydration preview, impact confirmation, and governed packages. Workshop is project-owned through authoring, rendering, events, publication, and recovery. Action Types, approvals, AIP Logic, Agent Studio, model endpoints, and both evaluation runtimes share project-bound resource validation, authenticated attribution, durable execution evidence, and snapshot recovery.
- User data path: project-owned CSV/JSON import jobs infer schemas, preview records, validate template mappings, upload local files without extra dependencies, and promote reviewed data into project-tagged datasets and governed Ontology Generator drafts. Backend permissions prevent cross-project reads and mutations, and authenticated principals are recorded in audit evidence.
- Onboarding depth: import jobs support mapping suggestions, type coercion, enum cleanup, timestamp normalization, unit normalization, derived geo points, MGRS-to-point conversion, duplicate detection, connector preview, and connector-to-import generation. Live REST, PostgreSQL, S3-compatible, SFTP, and Kafka sources use encrypted write-only credentials where required, transport/read-only guards, durable fetch evidence and cursors, and project-scoped jobs with leases, retries, idempotency, budgets, telemetry, and dead-letter recovery.
- Frontend direction: a React/Vite/TypeScript shell now serves typed core evaluator workspaces when built, with reusable contracts for pipeline, ontology, imports, command center, graph, and validation while the legacy static UI remains as a migration fallback.
- Guided evaluator flow: Command Center now has UI-state, workflow-state, a persistent flow indicator, evaluator summary, clean state/warning cards, clickable proof trail, import-to-ontology draft generation, backend-backed report export, and linked evidence IDs.
- Trust dashboard: `/workspace/validation` and `/project/validate` surface matrix status, priority gaps, runtime schema health, persisted migration records, event consistency, route health, and extended project snapshot evidence.
- Readiness: `/project/readiness`, `/ui-state/imports`, and `/ui-state/validation` expose human-facing checks and sections for technical evaluators.
- Runtime operations: durable jobs now emit project-scoped correlated observations for queue, claim, heartbeat, retry, recovery, success, failure, and cancellation. Request-hashed, database-unique receipts prevent bounded-history and cross-replica duplicate enqueue while rejecting changed requests behind reused keys. Stale-job reapers use row locking, emit dedicated recovery spans/audit/Ops evidence, and fence abandoned lease tokens. Rolling budgets gate admission, SLO evaluations emit breach events, and the Control Panel exposes human-readable latency, availability, usage, and cost evidence. Independently deployable worker daemons use hashed, project-scoped service tokens and add capability scope, concurrent polling, health endpoints, graceful drain, fair project queues, atomic lease contention handling, and stale-worker fencing.
- Production acceptance: `scripts/rehearse-production-acceptance.ps1` deploys digest-pinned Keycloak/Postgres fixtures with two API replicas, validates real OIDC tenant claims and backend RBAC, and proves project-owned imports, ontology generation, pipelines, Workshop, actions, AIP Logic, asynchronous agents, model endpoints, and evaluation runs. It rejects cross-project creation and viewer execution, then exercises 50 authenticated readers, cross-replica collaboration and job idempotency, abandoned-worker recovery, serialized migration startup, API restart, and fresh-volume backup/restore.
- Fidelity: high for local behavioral workflows; intentionally different for hosted infrastructure, proprietary UI internals, and LLM/model routing.
- Evidence: `foundry-docs/VALIDATION_MATRIX.md`, `oms/test_docs_conformance.py`, and existing focused tests.

## Domain Scores

| Domain | Fidelity | Evidence |
|---|---:|---|
| Ontology and actions | High | Object/link/action CRUD, validation, approvals, audit, snapshots |
| AIP Logic and agents | High local analog | Project-owned blocks, tools, traces, asynchronous jobs, proposed actions, approval gates, deterministic LLM substitute |
| Workshop | High | Variables, widgets, events, live render, publish, restore |
| Object Explorer | High | Query, facets, histograms, profiles, saved explorations, actions |
| Pipeline and DataOps | High | React DAG workbench, structured configuration forms, selected-node schema/preview, field lineage, typed validation, spatial/MGRS transforms, output rail, deliver, transactions, and recovery |
| Ontology Generator and Manager | High local analog | Dataset schema inference, drag/drop property mapping, type compatibility, hydrated object preview, primary/title keys, visual links, property/action editors, archived recovery, and change impact |
| GIS and Map | High | GeoJSON overlays, MGRS, radius/geofence, map layers |
| ModelOps | Medium-high | Objectives, training, eval gates, releases, deployments, inference logs, drift monitors |
| Platform cohesion | Medium-high | Unified events, global search, policy evaluation/simulation, shared activity timeline, visual graph overview |
| Operational MVP | High | Asset Reliability Command Center bootstrap/import, UI-state, workflow-state, evaluator summary, proof trail, triage, approval, action execution, incident, report, validation dashboard |
| Data import and project portability | High local analog | CSV/JSON/file import jobs, semantic mapping, transforms, connector previews, stream replay, import-to-ontology drafts, audit/ops events, extended JSON snapshot export/import |
| Connectors and streaming | High local analog | Live REST/PostgreSQL/S3-compatible/SFTP/Kafka adapters, encrypted credentials, SigV4, pinned SSH hosts, TLS/SASL, SSRF/read-only protections, project-scoped source/sync/stream resources, durable file/object/partition cursors, budgets, dead letters, and fetch evidence |
| Runtime observability and worker control | High local analog | Correlated durable-job spans, p95 latency/queue summaries, project budgets, SLO evaluation, registered worker fleets, fair queues, drain/resume, concurrent claim safety, stale-token fencing, and snapshot recovery |
| Frontend product foundation | Medium-high | Typed React/Vite core evaluator shell, persistent flow indicator, split workspaces/components, clean state primitives, close-analog pipeline workbench, ontology manager, and legacy fallback |
| Decision/Ops/Investigations | Local extension | Built on ontology, actions, audit, timelines, alerts, incidents, evidence, reports |
| Security/governance | High local analog | Real Keycloak OIDC rehearsal, organization/project isolation, persisted memberships, cross-tenant administration denial, package integrity, markings, restricted views, scanners, retention, and audit |

## Known Limitations

- This is not Palantir Foundry API compatibility. Endpoint names and payloads are local.
- LLM and model behavior is deterministic. There is no hosted model catalog, GPU runtime, model router, or paid external API dependency.
- Pipeline Builder compiles to local Python logic and local datasets, not Spark-backed Foundry transforms.
- UI workspaces are Foundry-style local approximations, not copied Foundry frontends. The React shell covers the evaluator path first and uses screenshot-grounded layout ideas without proprietary assets or internals; legacy workspaces remain during migration.
- REST, PostgreSQL, S3-compatible, SFTP, and Kafka adapters execute live locally. The Kafka adapter uses durable next-offset cursors per partition and production transport guards; portable project snapshots omit connector secrets and require credential rebinding after import.
- Private tenant pages are not automated validation sources unless the user provides screenshots or exported documents.
- Browser screenshot validation depends on available local browser tooling. If unavailable, route smoke checks are still required and visual checks are marked manual.

## Validation Commands

Run the primary docs conformance test:

```bash
cd oms
python test_docs_conformance.py
python test_worker_fleet_control.py
```

Run the matrix summary helper:

```bash
cd oms
python validate_docs_conformance.py
```

Recommended focused regression set:

```bash
cd oms
cd ../frontend && npm run build && cd ../oms
python test_deep_foundry_programs.py
python test_decision_intelligence.py
python test_modelops.py
python test_ops_investigations_reliability.py
python test_unified_platform.py
python test_asset_reliability_command_center.py
python test_productized_platform.py
python test_human_ui_readiness.py
python test_ontology_generator_pipeline_canvas.py
python test_ui_state_pipeline_ontology.py
python test_foundry_gis_features.py
python test_ontology_validation.py
python test_aip_logic.py
python test_docs_conformance.py
```

## Next Priorities

1. Add browser screenshot capture for `/workspace/command-center`, `/workspace/pipeline`, `/workspace/ontology`, `/workspace/graph`, and `/workspace/validation` when Playwright or Chrome control is available.
2. Continue React migration for Object Explorer, Workshop, Map, ModelOps, Ops, and Investigations after the evaluator path is stable.
3. Isolate live connector execution into separately sandboxed worker pools and rehearse Kafka TLS/SASL against a production-like broker profile.
4. Expand visual conformance notes for Workshop, Pipeline Builder, Object Explorer, Ontology Generator, Graph, Validation, and Map using user-provided screenshots.
5. Keep public source links current because Palantir documentation changes over time.
