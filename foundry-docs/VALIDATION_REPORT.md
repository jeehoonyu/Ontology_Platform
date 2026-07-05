# Docs-Grounded Validation Report

## Summary

This repository implements a local deterministic analog of public Palantir Foundry/AIP concepts. It does not copy Palantir code, claim proprietary API compatibility, or reproduce managed Foundry infrastructure. Validation is based on public docs, the local `foundry-docs` and `foundry-docs-full` corpus, and executable behavior tests.

Current result:

- Breadth: strong coverage across ontology, actions, AIP Logic, Workshop, Object Explorer, Pipeline Builder, GIS, data health, modeling, ModelOps, decision intelligence, ops, investigations, reliability, security, governance, global search, eventing, policies, timelines, and graph overview.
- Outcome proof: the Asset Reliability Command Center provides one complete local workflow from raw maintenance data to governed operational decision, incident, and report.
- Authoring fidelity: Pipeline Builder now has UI-state contracts, a React workbench canvas with grouped toolbar, edge insert actions, selected-node context menu, output rail, preview drawer, node-level details/preview/suggestions, and deterministic deliver; Ontology Manager now has a three-pane manager/walkthrough layout, object-type manager cards, section state, metadata/index actions, and dataset-to-object-type generation.
- User data path: CSV/JSON import jobs infer schemas, preview records, validate template mappings, upload local files without extra dependencies, and promote reviewed data into local datasets for the Ontology Generator and Command Center workflow.
- Onboarding depth: import jobs now support mapping suggestions, type coercion, enum cleanup, timestamp normalization, unit normalization, derived geo points, MGRS-to-point conversion, duplicate detection, connector preview, connector-to-import generation, sync validation, and deterministic stream replay.
- Frontend direction: a React/Vite/TypeScript shell now serves typed core evaluator workspaces when built, with reusable contracts for pipeline, ontology, imports, command center, graph, and validation while the legacy static UI remains as a migration fallback.
- Guided evaluator flow: Command Center now has UI-state, workflow-state, a persistent flow indicator, evaluator summary, clean state/warning cards, clickable proof trail, import-to-ontology draft generation, backend-backed report export, and linked evidence IDs.
- Trust dashboard: `/workspace/validation` and `/project/validate` surface matrix status, priority gaps, runtime schema health, persisted migration records, event consistency, route health, and extended project snapshot evidence.
- Readiness: `/project/readiness`, `/ui-state/imports`, and `/ui-state/validation` expose human-facing checks and sections for technical evaluators.
- Fidelity: high for local behavioral workflows; intentionally different for hosted infrastructure, proprietary UI internals, and LLM/model routing.
- Evidence: `foundry-docs/VALIDATION_MATRIX.md`, `oms/test_docs_conformance.py`, and existing focused tests.

## Domain Scores

| Domain | Fidelity | Evidence |
|---|---:|---|
| Ontology and actions | High | Object/link/action CRUD, validation, approvals, audit, snapshots |
| AIP Logic and agents | Medium-high | Blocks, variables, object tools, proposed actions, deterministic LLM substitute |
| Workshop | High | Variables, widgets, events, live render, publish, restore |
| Object Explorer | High | Query, facets, histograms, profiles, saved explorations, actions |
| Pipeline and DataOps | High | React DAG workbench, UI-state canvas contracts, selected-node details, output rail summaries, node insert/layout/preview/suggestions, validate/preview/deliver, ontology outputs, transactions, data expectations, lineage impact |
| Ontology Generator and Manager | High local analog | Dataset schema inference, primary/title key selection, profile/action scaffolding, generated pipeline graph, object-type overview/status/properties/cards, walkthrough, section state, metadata/index actions |
| GIS and Map | High | GeoJSON overlays, MGRS, radius/geofence, map layers |
| ModelOps | Medium-high | Objectives, training, eval gates, releases, deployments, inference logs, drift monitors |
| Platform cohesion | Medium-high | Unified events, global search, policy evaluation/simulation, shared activity timeline, visual graph overview |
| Operational MVP | High | Asset Reliability Command Center bootstrap/import, UI-state, workflow-state, evaluator summary, proof trail, triage, approval, action execution, incident, report, validation dashboard |
| Data import and project portability | High local analog | CSV/JSON/file import jobs, semantic mapping, transforms, connector previews, stream replay, import-to-ontology drafts, audit/ops events, extended JSON snapshot export/import |
| Frontend product foundation | Medium-high | Typed React/Vite core evaluator shell, persistent flow indicator, split workspaces/components, clean state primitives, close-analog pipeline workbench, ontology manager, and legacy fallback |
| Decision/Ops/Investigations | Local extension | Built on ontology, actions, audit, timelines, alerts, incidents, evidence, reports |
| Security/governance | Medium | Local roles, markings, restricted views, scanners, retention, audit |

## Known Limitations

- This is not Palantir Foundry API compatibility. Endpoint names and payloads are local.
- LLM and model behavior is deterministic. There is no hosted model catalog, GPU runtime, model router, or paid external API dependency.
- Pipeline Builder compiles to local Python logic and local datasets, not Spark-backed Foundry transforms.
- UI workspaces are Foundry-style local approximations, not copied Foundry frontends. The React shell covers the evaluator path first and uses screenshot-grounded layout ideas without proprietary assets or internals; legacy workspaces remain during migration.
- Hybrid connector previews use deterministic sample records by default. Optional Docker/local service demos are not required for test pass.
- Private tenant pages are not automated validation sources unless the user provides screenshots or exported documents.
- Browser screenshot validation depends on available local browser tooling. If unavailable, route smoke checks are still required and visual checks are marked manual.

## Validation Commands

Run the primary docs conformance test:

```bash
cd oms
python test_docs_conformance.py
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
3. Add optional Docker fixtures for Postgres and mock REST connector demos without making tests depend on those services.
4. Expand visual conformance notes for Workshop, Pipeline Builder, Object Explorer, Ontology Generator, Graph, Validation, and Map using user-provided screenshots.
5. Keep public source links current because Palantir documentation changes over time.
