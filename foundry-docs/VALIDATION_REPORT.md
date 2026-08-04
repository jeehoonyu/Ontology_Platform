# Docs-Grounded Validation Report

## Summary

This repository implements a local deterministic analog of public Palantir Foundry/AIP concepts. It does not copy Palantir code, claim proprietary API compatibility, or reproduce managed Foundry infrastructure. Validation is based on public docs, the local `foundry-docs` and `foundry-docs-full` corpus, and executable behavior tests.

Current result:

- Breadth: strong coverage across ontology, actions, AIP Logic, Workshop, Object Explorer, Pipeline Builder, GIS, data health, modeling, ModelOps, decision intelligence, ops, investigations, reliability, security, governance, global search, eventing, policies, timelines, and graph overview.
- Outcome proof: the Asset Reliability Command Center provides one complete local workflow from raw maintenance data to governed operational decision, incident, and report.
- Authoring fidelity: Pipeline Builder has project-owned graphs, backend-enforced read/edit/execute/deploy permissions, structured transforms, lineage, previews, spatial/MGRS execution, project-bound queued execution, and explicit ontology write contracts with field lineage and quarantine. Ontology Manager provides drag/drop mapping, hydration preview, impact confirmation, governed packages, immutable reviewed releases, health evaluation, policy simulation, a semantic registry, JSON Schema export, and generated TypeScript/Python clients. Workshop is project-owned through authoring, rendering, events, publication, and recovery. Action Types, approvals, AIP Logic, Agent Studio, model endpoints, objectives, submissions, checks, releases, deployments, adapters, monitors, prediction logs, and both evaluation runtimes share project-bound resource validation, authenticated attribution, durable evidence, migration backfill, and snapshot recovery.
- User data path: project-owned CSV/JSON import jobs infer schemas, preview records, validate template mappings, upload local files without extra dependencies, and promote reviewed data into project-tagged datasets and governed Ontology Generator drafts. Backend permissions prevent cross-project reads and mutations, and authenticated principals are recorded in audit evidence.
- Onboarding depth: import jobs support mapping suggestions, type coercion, enum cleanup, timestamp normalization, unit normalization, derived geo points, MGRS-to-point conversion, duplicate detection, connector preview, and connector-to-import generation. Live REST, PostgreSQL, S3-compatible, SFTP, and Kafka sources use encrypted write-only credentials where required, transport/read-only guards, durable fetch evidence and cursors, and project-scoped jobs with leases, retries, idempotency, budgets, telemetry, and dead-letter recovery.
- Frontend direction: a React/Vite/TypeScript shell now serves typed core evaluator workspaces when built, including Pipeline, Ontology, Imports, Command Center, Object Explorer, a real Leaflet GIS Map, ModelOps, Decision Intelligence, Operational Control, Graph, and Validation. Workspaces are lazy-loaded; `?legacy=1` remains an explicit compatibility aid rather than the evaluator default.
- Guided evaluator flow: Command Center now has UI-state, workflow-state, a persistent flow indicator, evaluator summary, clean state/warning cards, clickable proof trail, import-to-ontology draft generation, project-owned promoted-dataset compilation, human approval/rejection, idempotent action execution, backend-backed report export, and linked evidence IDs. Both the sample path and the project-owned data path complete Connect-to-Report through visible React controls without raw JSON; the latter atomically publishes a validated immutable production revision and typed registry contract, materializes normalized semantic definitions, and preserves revision/project ownership through hydration, risk, agent citations, approval, temporal mutation, outbox, incident, investigation, and report evidence.
- Trust dashboard: `/workspace/validation` and `/project/validate` surface matrix status, priority gaps, runtime schema health, persisted migration records, event consistency, route health, and extended project snapshot evidence.
- Readiness: `/project/readiness`, `/ui-state/imports`, and `/ui-state/validation` expose human-facing checks and sections for technical evaluators.
- Runtime operations: durable jobs now emit project-scoped correlated observations for queue, claim, heartbeat, retry, recovery, success, failure, and cancellation. Request-hashed, database-unique receipts prevent bounded-history and cross-replica duplicate enqueue while rejecting changed requests behind reused keys. Stale-job reapers use row locking, emit dedicated recovery spans/audit/Ops evidence, and fence abandoned lease tokens. Rolling budgets gate admission, SLO evaluations emit breach events, and the Control Panel exposes human-readable latency, availability, usage, and cost evidence. Independently deployable worker daemons use hashed, project-scoped service tokens and add capability scope, concurrent polling, health endpoints, graceful drain, fair project queues, atomic lease contention handling, and stale-worker fencing.
- OntologyOS runtime core: normalized semantic definitions, append-only object changes, typed temporal/GIS object queries, bounded graph queries, immutable Parquet/JSONL snapshots, compiled pipeline plans, real DuckDB/Arrow snapshot previews, a provider-neutral governed model gateway, and versioned durable agent tasks are available through additive `/api/v1` contracts.
- Streaming runtime: stream-scoped atomic arrival sequences, partition-local watermarks, late/invalid-data quarantine, tumbling aggregations, stable output IDs, producer backpressure, durable jobs, transactional rollback, snapshot recovery, and PostgreSQL concurrent-publisher/processor fencing are executable through `/api/v1/streams/processors/*`.
- Collaborative authoring: visual artifacts expose revision-anchored comments and governed change proposals. Approved non-overlapping edits rebase under a server lock, overlapping edits become durable conflicts, and the React builder provides review and apply controls without exposing command JSON.
- Collaboration and identity scale: the PostgreSQL command path refreshes state after row-lock waits and atomically commits artifact revision, idempotency receipt, and collaboration event. Two consecutive two-replica rehearsals applied 20 simultaneous disjoint edits without loss at 206.458 ms and 224.866 ms p95, then returned identical committed state to 200 simultaneous readers. The authenticated WebSocket resumes from durable cursors; process termination/restart recovered with zero missed or duplicate events and 209.067 ms maximum reconnect. A separate clean production run authenticated 200 distinct Keycloak PKCE identities across both replicas at login p95 4,582.792 ms and enforced 200 mutation denials.
- Ontology query scale: typed object masking is batched, governed PostgreSQL `BTREE_EXPRESSION_V3` indexes combine planner-compatible JSONB expressions with stable object-ID ordering, and CI inspects physical plans over 100k objects/500k links. The refreshed strict 10M-object/50M-link run measured lookup p95 8.718 ms, range/order p95 11.830 ms, and two-hop graph p95 13.721 ms. A strict mixed run sustained 213.932 state/event writes per second under eight readers at 53.635 ms read p95, with rollback, vacuum, process-restart, fresh-volume restore, streaming replay, and failover evidence.
- Pipeline scale: bounded local or S3-compatible Parquet registration avoids row hydration, recovers Hive fields, and records immutable per-file manifests; S3 snapshots use an integrity-checked, quota-bounded, lease-aware execution cache with operational metrics and coordinated concurrent downloads; compiled DuckDB plans use order-independent named parameters and SQL-native branches, reshape, validation, window, point/radius, MGRS, polygon-geofence, and spatial-join operations; atomic Hive-partitioned delivery records every source snapshot and is idempotent by execution job. The strict local profile processed eight files/10M fact rows through stable IDs, radius GIS, MGRS, polygon containment, a dimension join, and a partitioned window with preview p95 3,663.405 ms, delivery 4,046.026 ms, 20 output partitions, and only 20 Python result rows. A separate real-MinIO loopback profile measured one-million-row registration at 281.585 ms, cold query at 128.102 ms, warm query p95 at 87.243 ms, cold pipeline at 351.269 ms, and warm pipeline p95 at 49.161 ms. Representative remote-provider latency, large-to-large spatial plans, and distributed execution remain open.
- Production acceptance: `.github/workflows/ci.yml` automatically gates pull requests with the current backend scripts, 70-row docs conformance matrix, dependency audit, SQLite/PostgreSQL migrations through `0033_async_plugin_execution`, a real digest-pinned plugin OCI rehearsal, isolated executor image build, ontology query and mixed-workload plans, a partitioned 1M-row advanced snapshot pipeline smoke benchmark, two-replica collaboration scale and WebSocket chaos rehearsals, responsive WCAG browser acceptance, Compose validation, and production image builds. `scripts/rehearse-production-acceptance.ps1` remains the final release rehearsal: it deploys digest-pinned Keycloak/Postgres fixtures with two API replicas, validates real OIDC claims, browser WebSockets, and backend RBAC, provisions 200 distinct scale identities, exercises 50 authenticated readers, cross-replica collaboration, worker recovery, API restart, and fresh-volume backup/restore.
- Fidelity: high for local behavioral workflows; intentionally different for hosted infrastructure, proprietary UI internals, and LLM/model routing.
- Evidence: `foundry-docs/VALIDATION_MATRIX.md`, `docs/GOAL_ACCEPTANCE_2026-07-28.md`, `oms/test_docs_conformance.py`, and focused production/runtime tests.

## Domain Scores

| Domain | Fidelity | Evidence |
|---|---:|---|
| Ontology and actions | High | Normalized definitions, typed query/graph APIs, object/link/action CRUD, temporal changes, validation, approvals, audit, snapshots |
| AIP Logic and agents | High local analog | Project-owned blocks, tools, traces, asynchronous jobs, proposed actions, approval gates, deterministic LLM substitute |
| Workshop | High | Variables, widgets, events, live render, publish, restore |
| Object Explorer | High | Typed React query workbench, facets, risk badges, profiles, saved explorations, selection, and governed actions |
| Pipeline and DataOps | High | React DAG workbench, immutable Parquet/JSONL snapshots, branching snapshot-native DuckDB plans with joins/unions, reshape, validation, windows, point/radius GIS and spatial joins, durable preview/delivery, multi-source lineage, idempotent output recovery, and a strict 10M-row advanced benchmark |
| Ontology Generator and Manager | High local analog | Dataset schema inference, drag/drop property mapping, type compatibility, hydrated object preview, primary/title keys, visual links, property/action editors, archived recovery, change impact, reviewed immutable releases, health evaluation, policy simulation, schema registry, and generated typed clients |
| GIS and Map | High | Leaflet/OpenStreetMap workbench, ontology GeoJSON overlays, accessible feature selection, risk styling, MGRS, radius/geofence, and persistent map layers |
| ModelOps | High local analog | Typed React lifecycle for project-owned objectives, training, eval gates, releases, deployments, structured inference, prediction logs, drift/quality monitors, RBAC, migration, and snapshot recovery; browser-tested end to end |
| Platform cohesion | Medium-high | Unified events, global search, policy evaluation/simulation, shared activity timeline, visual graph overview |
| Operational MVP | High | Asset Reliability Command Center bootstrap/import, UI-state, workflow-state, evaluator summary, proof trail, triage, human approval/rejection, governed action execution, incident, action-linked report export, validation dashboard, responsive browser proof |
| Data import and project portability | High local analog | CSV/JSON/file import jobs, semantic mapping, transforms, connector previews, stream replay, import-to-ontology drafts, audit/ops events, and version 3 project-scoped snapshot export/import with dependency closure, foreign-reference rejection, and clean-database restore evidence |
| Connectors and streaming | High local analog | Live REST/PostgreSQL/S3-compatible/SFTP/Kafka adapters, encrypted credentials, SigV4, pinned SSH hosts, TLS/SASL, SSRF/read-only protections, durable cursors, event-time watermarks/windows, quarantine, backpressure, exactly-once processor receipts, budgets, dead letters, and recovery evidence |
| Runtime observability and worker control | High local analog | Correlated durable-job spans, p95 latency/queue summaries, project budgets, SLO evaluation, registered worker fleets, fair queues, drain/resume, concurrent claim safety, stale-token fencing, and snapshot recovery |
| Frontend product foundation | High | Typed and lazy React/Vite evaluator shell, persistent flow indicator, clean state primitives, Pipeline and Ontology workbenches, Object Explorer, operational GIS Map, ModelOps lifecycle, and four-viewport WCAG/overflow acceptance |
| Collaborative visual authoring | High local analog | Server-authoritative command sequence, leases, target-scoped rebasing, revision comments, reviewed proposals, conflict evidence, audit, snapshot recovery, and React review controls |
| Decision/Ops/Investigations | Local extension | Built on ontology, actions, audit, timelines, alerts, incidents, evidence, reports |
| Security/governance | High local analog | Real Keycloak OIDC rehearsal, organization/project isolation, persisted memberships, cross-tenant administration denial, package integrity, markings, restricted views, scanners, retention, and audit |

## Known Limitations

- This is not Palantir Foundry API compatibility. Endpoint names and payloads are local.
- LLM and model behavior is deterministic. There is no hosted model catalog, GPU runtime, model router, or paid external API dependency.
- Pipeline Builder retains local Python execution for its broad transform catalog. Its scalable DuckDB path directly executes branching Parquet transforms including joins/unions, pivot/unpivot, windows, validation, radius filtering, SQL-native MGRS, polygon geofencing, and spatial joins, not Spark-backed distributed transforms; multi-worker partition execution remains outside that path.
- The typed query compiler pushes filters, ordering, aggregates, spatial bounds, temporal selection, and keyset pagination into SQL, with governed PostgreSQL expression indexes and bounded graph traversal. The strict 10M-object/50M-link profile measures exact lookup at 8.718 ms p95, range/order at 11.830 ms p95, and two-hop graph traversal at 13.721 ms p95. A strict mixed run committed 100,000 state/event transitions under eight readers at 53.635 ms read p95 and 213.932 writes/s. Vacuum/process restart recovered in 2.714 s; a 36.59 GB physical backup completed in 50.917 s and restored readiness from a fresh volume in 1.144 s; streaming replication replayed a committed probe in 0.015 s and promoted after source loss in 0.686 s without probe loss.
- Local snapshot backup sidecars cover the mounted filesystem backend. S3-compatible deployments require bucket versioning and provider-native backup procedures.
- UI workspaces are Foundry-style local approximations, not copied Foundry frontends. The typed React shell covers the primary evaluator path, including ontology exploration, GIS operations, governed ModelOps, explainable Decision Intelligence, and event-to-incident operational control.
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

1. Extend the achieved strict 10-million-object/50-million-link mixed, fresh-volume backup, and streaming-failover profiles with longer-duration saturation and repeated scheduled recovery evidence; add projections or partitioning only where measurements require them.
2. Extend the implemented Kafka/Redpanda outbox transport beyond verified interruption and stable-ID duplicate recovery with measured backpressure, partition saturation, and downstream consumer-lag rehearsals.
3. Retire compatibility pages only after their non-evaluator utility routes have equivalent typed coverage and documented migration guidance.
4. Run the implemented OIDC plugin-executor loss/recovery, governed-egress, signed custom-CA HTTPS, and clean ontology SDK installation gates for each release candidate; promote verified SDK archives to an external registry only when an organization configures one.
5. Extend the achieved two-replica 20-editor, authenticated WebSocket process-loss recovery, and 200-distinct-OIDC-user gates with sustained rolling-deployment/network-partition evidence and two independent evaluator-team trials.
