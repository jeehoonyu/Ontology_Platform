<table><tr>
<td style="background:#111418;color:#fff;padding:14px 18px;border-left:6px solid #2D72D2">
<b style="color:#8ABBFF">FOUNDRY · DATA INTEGRATION</b><br>
<span style="font-size:22px"><b>Data Lineage</b></span><br>
<span style="color:#ABB3BF">An interactive graph application that tracks and visualises how every dataset, transform, and pipeline in Foundry is connected — from raw source to final output.</span>
</td></tr></table>

## What it is

Data Lineage is a first-class Palantir Foundry application that records the provenance of every data asset: which input datasets were consumed by which transforms to produce which outputs. It surfaces these relationships as a navigable, interactive directed-acyclic graph (DAG), giving engineers, data owners, and analysts a single place to inspect data flow, diagnose staleness, manage builds and schedules, check permissions, and roll back pipelines or individual datasets without leaving the lineage view.

## How it works

Foundry continuously maintains a platform-level metadata graph that captures every read/write relationship between datasets and the transforms that connect them. The following steps describe the end-to-end mechanics.

1. **Automatic relationship capture.** Every time a Foundry transform (Code Repositories using Python, Java, or SQL; Pipeline Builder jobs; Contour/Quiver/etc.) reads an input dataset and writes an output dataset, the platform records a directed edge: `input dataset → transform → output dataset`. No manual annotation is required.

2. **Asset nodes.** The graph contains distinct node types for each tracked resource: datasets (tabular or file-based), transform/pipeline nodes (the code or logic that produced an output), ontology objects (Object Types backed by datasets), Marketplace artifacts, and schedule nodes. Each node carries metadata such as resource identifier (RID), last-build timestamp, and staleness state.

3. **Staleness propagation.** When an upstream dataset is rebuilt with new data, all downstream nodes are flagged as **stale/out-of-date**. This propagation is automatic and recursive: a change in a raw ingest dataset marks every derived dataset downstream as pending until they are rebuilt.

4. **Graph assembly on demand.** When a user opens Data Lineage and searches for a resource, the application fetches the stored metadata edges for that node and renders the local sub-graph. The user can then expand parents (upstream) or children (downstream) iteratively, building up as large or small a view as needed.

5. **Build and schedule execution.** From within the lineage graph a user can trigger a manual build of a selected dataset or pipeline. The platform enqueues the build job, executes the transform, writes the output, and updates the build timeline and staleness flags — all reflected live in the graph.

6. **Rollback.** Foundry stores versioned snapshots of dataset contents and pipeline configurations. A pipeline rollback reverts the pipeline definition to a previous version; a dataset rollback restores the dataset content to a prior build snapshot. Both operations are recorded in the build timeline.

7. **Permissions and marking impact.** Data Lineage can surface which principals have access to each node. The "marking impact" view shows how applying or changing a data marking (sensitivity label) would propagate restrictions through the downstream graph before the change is committed.

8. **Branch awareness.** When code branches are active in Code Repositories, the lineage graph can be filtered to a specific branch, showing only the edges and builds that belong to that branch's view of the pipeline.

## User interface

The Data Lineage application opens as a full-screen canvas experience inside the Foundry navigation shell.

**Overall layout**

- <span style="color:#8ABBFF">**Left sidebar — Search & Add panel**</span> (`background:#1C2127`, `border-right:1px solid #383E47`): A free-text search field lets users find any resource by name or RID. Results appear as a browsable tree; clicking a result or using the "Add all" button places node(s) onto the central canvas.
- <span style="color:#8ABBFF">**Central canvas**</span> (`background:#111418`): The interactive DAG. Nodes are connected by directional arrows representing transformations. The canvas supports pan, zoom, and selection. Upstream nodes appear to the left; downstream to the right.
- <span style="color:#8ABBFF">**Right sidebar — Properties helper**</span> (`background:#1C2127`): When a single node is selected, this panel shows resource details: name, RID, last-build status, schema summary, owning project, and quick-action buttons (Build, View in editor, Roll back, Check permissions).
- <span style="color:#8ABBFF">**Top toolbar**</span>: Controls for graph layout, node coloring rules, branch selector, save/share, and export to SVG.

**Node states — what you see**

<table style="border-collapse:collapse;background:#1C2127;color:#fff;font-size:13px">
<tr style="border-bottom:1px solid #383E47">
  <th style="padding:8px 12px;text-align:left;color:#ABB3BF">Visual chip</th>
  <th style="padding:8px 12px;text-align:left;color:#ABB3BF">Meaning</th>
</tr>
<tr style="border-bottom:1px solid #383E47">
  <td style="padding:8px 12px"><span style="color:#238551"><b>● Up to date</b></span></td>
  <td style="padding:8px 12px">Dataset has been successfully built against current upstream inputs</td>
</tr>
<tr style="border-bottom:1px solid #383E47">
  <td style="padding:8px 12px"><span style="color:#C87619"><b>● Stale / out-of-date</b></span></td>
  <td style="padding:8px 12px">An upstream input has changed; this node needs to be rebuilt</td>
</tr>
<tr style="border-bottom:1px solid #383E47">
  <td style="padding:8px 12px"><span style="color:#CD4246"><b>● Build failed</b></span></td>
  <td style="padding:8px 12px">The most recent build attempt ended in error</td>
</tr>
<tr style="border-bottom:1px solid #383E47">
  <td style="padding:8px 12px"><span style="color:#2D72D2"><b>● Building</b></span></td>
  <td style="padding:8px 12px">A build is currently in progress</td>
</tr>
<tr>
  <td style="padding:8px 12px"><span style="color:#ABB3BF"><b>● Never built</b></span></td>
  <td style="padding:8px 12px">Dataset exists but has not yet had a successful build</td>
</tr>
</table>

**Key interactions**

- **Expand upstream/downstream**: Clicking the <span style="color:#8ABBFF">left arrow chevron</span> on any node reveals its direct parents; the <span style="color:#8ABBFF">right arrow chevron</span> reveals children. Nodes can be collapsed again to keep the canvas tidy.
- **Node coloring**: Rules can be set to colour nodes by project, owner, staleness age, or custom tags, making large graphs easier to reason about at a glance.
- **Dataset preview**: Selecting a dataset node and choosing "Preview" in the properties sidebar opens a tabular sample of the data alongside the transformation logic (SQL, Python, etc.) that produced it — without leaving the lineage view.
- **Build timeline**: A chronological list of every past build for a selected dataset, showing start time, duration, input transaction IDs consumed, and success/failure status.
- **Find column**: A search across the visible graph (or the entire platform) that locates every dataset containing a column with a given name — useful for cross-cutting schema discovery.
- **Save and share**: Graphs can be saved as named views, opened by collaborators, or exported as a static SVG or a shareable read-only URL.

## Worked example

**Scenario**: A data engineer notices that a downstream analytics dataset named `flights_enriched` is marked stale and wants to trace the root cause and trigger a fix.

1. The engineer opens the **Data Lineage** app and types `flights_enriched` in the left search panel. The node appears on the canvas with a <span style="color:#C87619"><b>stale</b></span> indicator.
2. They click the left chevron on `flights_enriched` to expand its parents. Two upstream datasets appear: `flights_raw` (<span style="color:#CD4246"><b>failed</b></span>) and `airports_reference` (<span style="color:#238551"><b>up to date</b></span>).
3. The engineer selects `flights_raw` in the properties sidebar, sees "Last build: FAILED — 2 h ago" and clicks **View in editor** to open Code Repositories, where they identify a schema mismatch in the ingest transform.
4. After pushing a fix on a feature branch, they return to Data Lineage, switch the branch selector to the feature branch, and verify the branch-scoped graph shows the corrected edge.
5. Once merged, they click **Build** on `flights_raw` from the properties panel. The canvas updates in real time: `flights_raw` turns <span style="color:#2D72D2"><b>building</b></span>, then <span style="color:#238551"><b>up to date</b></span>, after which `flights_enriched` is automatically re-queued per its schedule and clears its stale flag.

## Documentation map

The following sub-pages live beneath Data Lineage in the Foundry docs:

- **Overview** — introduction and capability summary
- **Navigation** — how to use the canvas controls, tools, and settings
- **Branching data lineage** — working with lineage on non-main code branches
- **FAQ** — common questions and edge-case guidance
- **Graphs / Explore data lineage** — step-by-step graph exploration
- **Graphs / Explore artifacts and ontology entities** — extending the graph to Marketplace artifacts and Object Types
- **Graphs / Save and share a graph** — persisting named views and generating shareable links
- **Graphs / Node coloring** — configuring visual colour rules for nodes
- **Graphs / Graph elements reference** — full reference for all node and edge types
- **Understand and manage datasets / View dataset preview and logic** — inline data preview and transform code
- **Understand and manage datasets / View build timeline** — per-dataset build history
- **Understand and manage datasets / Understand out-of-date datasets** — staleness semantics
- **Understand and manage datasets / Find datasets with a given column** — cross-platform column search
- **Understand and manage datasets / Build datasets** — manually triggering builds
- **Understand and manage datasets / Manage schedules** — viewing and editing refresh schedules
- **Understand and manage datasets / Roll back a pipeline** — reverting pipeline configurations
- **Understand and manage datasets / Roll back a dataset** — restoring dataset snapshots
- **Understand and manage datasets / Check permissions** — resource-level access inspection
- **Understand and manage datasets / Understand the impact of marking changes** — pre-flight marking impact analysis

## Official documentation

- [Data Lineage · Overview](https://www.palantir.com/docs/foundry/data-lineage/overview)
- [Data Lineage · Graphs · Explore data lineage](https://www.palantir.com/docs/foundry/data-lineage/explore-lineage)
- [Data Lineage · Navigation](https://www.palantir.com/docs/foundry/data-lineage/navigation)
- [Data Lineage · Understand and manage datasets · Build datasets](https://www.palantir.com/docs/foundry/data-lineage/build-datasets)
- [Data Lineage · Understand and manage datasets · View dataset preview and logic](https://www.palantir.com/docs/foundry/data-lineage/dataset-preview-logic)
- [Data Lineage · Graphs · Graph elements reference](https://www.palantir.com/docs/foundry/data-lineage/elements-reference)
- [Data Lineage · Graphs · Explore artifacts and ontology entities](https://www.palantir.com/docs/foundry/data-lineage/explore-artifacts)
- [Data Lineage · FAQ](https://www.palantir.com/docs/foundry/data-lineage/faq)
- [Introduction to Data Lineage (learning course)](https://learn.palantir.com/introduction-to-data-lineage)
