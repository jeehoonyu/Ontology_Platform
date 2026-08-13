# Visual Builder Operations

The visual builders are versioned, backend-connected authoring surfaces for Pipeline, Ontology, Workshop, and AIP Logic. They use local deterministic execution and do not require users to edit source code or JSON.

## Shared Editing Model

- Drag tools from the searchable library onto the canvas.
- Hold `Ctrl` or `Cmd` to select multiple nodes, or drag a marquee on an empty canvas area.
- Use `Ctrl/Cmd+C`, `Ctrl/Cmd+V`, and `Ctrl/Cmd+D` to copy, paste, and duplicate.
- Use `Delete` or `Backspace` to remove the current selection.
- Use `Ctrl/Cmd+Z` and `Ctrl/Cmd+Y` for undo and redo.
- Use **Layout** to arrange nodes on a stable grid and **Fit** to frame the graph.
- Drafts autosave through atomic command batches. The header reports unsaved, saving, saved, published, and conflicted states.
- Preview creates deterministic job evidence. Validation issues point to the relevant artifact, node, or field.
- Publish records an immutable revision. Version history can restore a prior revision without destroying later audit evidence.

Editing leases prevent accidental simultaneous overwrites. A `409` means the browser has an older lock version and should reload; a `423` means another principal holds the lease.

## Pipeline Builder

Pipeline nodes use structured forms in the selected-node rail. Supported groups include:

- datasets, imports, connectors, streams, and ontology inputs
- selection, rename, cast, formulas, missing values, normalization, deduplication, sorting, limiting, and validation
- joins, unions, aggregation, pivot, unpivot, windows, and deterministic IDs
- latitude/longitude, MGRS, geometry, radius/geofence, and spatial joins
- model inference, governed generation, dataset output, and ontology output

Each selected node exposes inferred schema, sample rows, configuration validation, upstream/downstream dependencies, and field lineage. **Propose** validates the DAG, **Preview** executes without output mutation, and **Deploy** writes the configured output with audit and lineage evidence.

## Ontology Designer

The manager combines object-type metadata, visual links, properties, actions, datasource mappings, observability, dependents, and guided evidence.

Dataset mapping workflow:

1. Choose a source dataset.
2. Generate normalized field suggestions.
3. Drag source fields onto object properties or use the accessible select control.
4. Resolve type mismatches and required-property errors.
5. Inspect hydrated object rows.
6. Save the audited mapping for use by an ontology output node.

Property removal archives the schema definition and preserves existing object values. The UI runs dependency impact analysis before confirmation and reports affected objects, pipelines, applications, and artifacts.

## Workshop

Workshop supports object tables, metrics, charts, maps, graphs, timelines, filters, forms, actions, risk panels, and AIP Assist. Each widget uses a typed configuration form. Desktop, tablet, and mobile breakpoint controls let authors inspect responsive composition before publication.

## AIP Logic

AIP Logic blocks expose typed ports and forms for object queries, functions, branches, models, risk, scenarios, alerts, incidents, runbooks, approvals, and actions. Preview traces include block inputs and outputs, revision citations, policy decisions, approval gates, and proposed mutation evidence. Preview never directly executes a governed high-risk action.

## Deployment Gate

Before publishing a release:

```powershell
cd frontend
npm run build
npm run test:e2e
cd ../oms
./venv312/Scripts/python.exe test_builder_kernel.py
./venv312/Scripts/python.exe test_pipeline_structured_config.py
./venv312/Scripts/python.exe test_ontology_mapping_impact.py
./venv312/Scripts/python.exe validate_docs_conformance.py
```

The complete backend script suite, OIDC rehearsal, backup/restore rehearsal, 250-node pipeline check, and 50-reader check remain release requirements. See [Production Pilot Operations](PRODUCTION_PILOT.md).
