# Platform-wide Foundry UI review and improvement plan

Reviewed September 11, 2026. Companion to the [initial canvas plan](FOUNDRY_UI_IMPROVEMENT_PLAN_2026-09-11.md).

## Scope and evidence

The authenticated application's launcher exposed 61 application entries. I opened all 61 entry points and inspected their rendered UI. These include three IDE-specific links to the shared Code Workspaces application; 61 entries does not mean 61 distinct editors.

Deeper inspection covered the existing Pipeline Builder graph from the initial review, Workshop's Common Operating Picture in both runtime and editor modes, Object Explorer's Route Alert exploration and custom-layout menu, and Ontology Manager's object overview and property inspector. Visual inspection also covered Home, Map, AIP Analyst, and these detailed workspaces. The remaining application reviews primarily used rendered accessibility/DOM content and visible controls.

This is breadth coverage of all launcher entries, not an exhaustive test of every nested page, dialog, or workflow. Empty recent lists do not establish that an application has no resources. Carbon reported no available workspace/access; Model Studio opened a file-creation dialog that was canceled; Sensitive Data Scanner required space selection. Those deeper editors remain unverified. No example was installed, no AI prompt or query was submitted, and no artifact changes were saved or deployed.

Local findings are source-based. The running local frontend has not been visually tested in this review. Existing uncommitted pane/drag work is part of the inspected baseline and should be preserved.

## Main design decision

Adopt one consistent workspace shell with several content-specific interaction models:

| Surface | Movement model | Expected feedback |
| --- | --- | --- |
| Pipeline, logic, ontology relationships, investigations | Freely positioned nodes, optional snapping, pan/zoom, selection, connected ports | Ghost position, compatible ports, live edges, selection bounds |
| Workshop and operational dashboards | Nested rows/columns/sections, widget reorder and resize, Auto/Absolute/Flex sizing | Insertion line, target-container outline, size preview, parent breadcrumb |
| Analytics and object exploration | Reorderable/resizable chart cards, persistent filters, linked results | Card placeholder, retained filters, shared selected-object state |
| Maps | Geographic pan/zoom with surrounding movable panels and reorderable layers | Layer-order preview, highlighted feature, preserved map extent |
| Tables and spreadsheets | Column/sheet reorder, resize, cell/range selection; optional row reorder only when meaningful | Column insertion marker, width guide, range highlight |
| Administration and review queues | Resizable list/detail panes, sortable tables, explicit actions | Selected-row detail, persistent filters, clear scope and action status |
| All workspaces | Header-only pane dragging, docking, hide/restore, keyboard alternatives | Dock preview, focus retention, one-step cancellation, reset layout |

Free movement should serve the task. Moving a dashboard widget changes application composition; moving an inspector changes the person's workspace preference. These need different persistence and undo boundaries.

## Observations that change the original plan

### Workshop is a page composer

The [Workshop editor](https://digitalglobe.usw-17.palantirfoundry.com/workspace/module/splash) displayed a live page between two resizable side regions. Selecting a section exposed contextual Move, Above, Below, Split section, and header controls. The inspector exposed Auto (max), Absolute, and Flex height; width override; tabs; collapsibility; conditional visibility; padding; row/column direction; and scrolling. The page offered explicit Add widget and Set layout entry points.

The existing Common Operating Picture combined left filters, top metrics, a large central map, and a bottom table. Builder chrome and runtime chrome were clearly different. This is stronger evidence for nested composition than the initial generic graph-based recommendation.

**Plan:** Implement a section tree and real rendered widgets for local Workshop. Drag between sections, reorder within rows/columns, resize with bounds, and show where the widget will land. Keep bindings and widget IDs stable when moving. Add keyboard Move before/after/into and sizing controls. Use explicit Edit and View modes. A breakpoint dropdown must produce actual reflow and a usable runtime preview.

### Object exploration combines charts, filters, and results

[Object Explorer](https://digitalglobe.usw-17.palantirfoundry.com/workspace/hubble) exposed multiple exploration tabs, property search, categorical charts, numeric filters, Explore/Results modes, a results rail, linked objects, Compare, and Open in. Its Custom layout menu offered to save the current charts and sorts as a layout. Saving and dragging that layout were not tested.

**Plan:** Keep selection and filters stable across chart, table, map, and detail views. Let users rearrange analysis cards and save a view definition. Keep analysis configuration separate from personal panel docking. A dropped property should offer compatible chart/filter choices rather than silently choosing an arbitrary representation.

### Ontology Manager follows the selected resource

[Ontology Manager](https://digitalglobe.usw-17.palantirfoundry.com/workspace/ontology) exposed resource navigation, branch selection, counts, and search. Object details linked Overview, Properties, Security, Datasources, Observability, Capabilities, Object views, Interfaces, Materializations, Automations, Usage, and History. Selecting a property opened a detail rail with General, Source, Display, Interaction, and Dependents. Properties also exposed Column mapping and a mapped-column count.

**Plan:** Make resource selection persistent. Use a searchable resource tree, a central list/graph, and a property inspector. Keep mapping source, destination, type compatibility, and errors visible together. Show dependencies before schema changes and link issues to the exact property or mapping.

### Maps and lineage preserve a large central surface

[Map](https://digitalglobe.usw-17.palantirfoundry.com/workspace/map) exposed compact Layers/Legend/Histogram controls, a collapsible panel, selection tools, fit/zoom/reset-bearing, and Timeline. [Data Lineage](https://digitalglobe.usw-17.palantirfoundry.com/workspace/monocle) exposed pan/select, layout, snapping, parent/child expansion, grouping/color, minimap, and bottom Preview/SQL/History/Code/Build timeline/Data health tabs. The lineage graph was empty, so resource-specific behavior was not tested.

**Plan:** Consolidate graph navigation but preserve domain semantics: lineage expansion adds existing dependencies; pipeline connection authors executable flow. Layer reordering changes rendering order; moving a map inspector must not move geographic objects. Prevent routine data refreshes from unexpectedly fitting the map again.

### Tables, review queues, and catalogs are first-class workspaces

[Projects & files](https://digitalglobe.usw-17.palantirfoundry.com/workspace/compass) had type/project/tag filters, a resizable region, sortable columns, role information, and separate All files/Shared/Data Catalog/Trash tabs. [Approvals](https://digitalglobe.usw-17.palantirfoundry.com/workspace/approvals-app), Builds, and Issues emphasized status, scope, dates, ownership, search, and filters. [Model Catalog](https://digitalglobe.usw-17.palantirfoundry.com/workspace/model-catalog) offered lifecycle/capability/provider filters and comparison.

**Plan:** Build a reusable full data grid for resource lists and results: explicit schema, visible totals, paging or virtualization, column visibility/reorder/resize/pin, sorting, filtering, selection, and detail opening. Preserve a compact preview table for small summaries, labeled with the displayed count. Review actions remain explicit buttons with a readable consequence; dragging is for arranging the view.

### AI and SQL keep context close to the work

[AIP Analyst](https://digitalglobe.usw-17.palantirfoundry.com/workspace/aip-analyst) exposed analysis saving, chat tabs, context/tools, model selection, and outline. [AI FDE](https://digitalglobe.usw-17.palantirfoundry.com/workspace/ai-fde) exposed context categories, tool approval, session outline, and a resizable region. [SQL Studio](https://digitalglobe.usw-17.palantirfoundry.com/workspace/sql-studio/) exposed a resource explorer, worksheet tabs, editor, results region, history, and explicit Run.

**Plan:** Use a context rail, central conversation/editor, and resizable evidence/results region. Drag a known resource into context with a visible resource chip and scope; keep Run/Send explicit. Distinguish a proposed action, an execution trace, and a completed mutation.

### Discovery and empty states need a common pattern

Most resource-oriented applications had a consistent header, primary create action, Recents/Favorites, searchable lists, and examples. [Data Connection](https://digitalglobe.usw-17.palantirfoundry.com/workspace/data-ingestion-app) distinguished connecting a live system, uploading static data, and manually generating data. Many first visits opened release-note overlays.

**Plan:** Use consistent list pages and distinguish no recent items, no results for current filters, no permission, and no configured resources. Each should offer an appropriate next step. Keep learning material accessible through a compact help region; avoid repeatedly interrupting the primary task with large onboarding overlays.

## Concrete local gaps

| Source | Verified source finding | Required change |
| --- | --- | --- |
| `frontend/src/components/data/DataDisplay.tsx` | Shared DataTable renders `safeRows.slice(0, 40)`; column discovery samples the first ten rows and first eight keys per sampled row. It has no built-in paging or column controls. | Introduce the full grid and explicitly label limited previews. Do not silently omit records or fields from full result views. |
| `frontend/src/App.tsx` | Workshop, AIP Logic, Investigations, and Entity Resolution all route to VisualBuilder. | Separate page composition and review semantics from graph authoring while sharing the shell. |
| `frontend/src/workspaces/VisualBuilder.tsx` | Central content uses React Flow; snapping is always enabled; preview/validation/evidence header includes static spans. | Give each artifact its appropriate editor; wire true tabs; expose snapping and pan/select modes. |
| `frontend/src/workspaces/MapWorkspace.tsx` | MapViewport calls fitBounds when the collection changes. | Fit on first load or explicit Fit; retain manual extent through refresh and panel changes unless the user requests follow-selection. |
| `frontend/src/workspaces/Fusion.tsx` | The grid declares fixed columns A through H. | Plan scalable column geometry, column resizing, sheet navigation, range selection, and formula feedback; verify API limits before expanding. |
| `frontend/src/components/layout/Pane.tsx` and `frontend/src/lib/paneLayout.ts` | Existing work implements slots, hide/collapse/restore, side sizing, local persistence, and pipeline integration. | Extend this work to other workspaces; add bottom-height resizing, ordering, docking previews, and presets. |
| `frontend/src/App.tsx` | Navigation renders all NAV_ITEMS with hints and a visible legacy section; a command palette and recent views already exist. | Group navigation by task, support compact editing mode and favorites, and expose migration routes through secondary navigation. Reuse existing search/history. |
| `frontend/src/components/canvas/PipelineCanvas.tsx` | Custom zoom controls lack handlers; clicked edges do not identify themselves to insertion callbacks. | Complete these interactions before broader canvas polish. |

These observations describe the inspected source, not a claim that tests failed. Generated pane-audit documentation and live source were in transition; do not use the generated counts as a final rollout baseline without regenerating them during implementation.

## Plan for every local workspace

All entries below are proposed local improvements. Correspondence to a Foundry app is an interaction reference, not feature-parity certification.

| Local workspace | Target layout and movement | First useful increment |
| --- | --- | --- |
| Command Center | Reorderable KPI/feed cards with clear drill-down | Saved personal overview; restore default |
| Imports / Data onboarding | Source chooser, schema/sample preview, mapping region | Separate live connection/upload/manual entry; show drop target and validation |
| Pipeline | Canvas, searchable tools, inspector, preview/output regions | Reliable drop math, pan/zoom, exact-edge insertion, undo |
| Ontology | Resource navigation, property grid/graph, inspector | Stable selection and field mapping with type feedback |
| Object Explorer | Filter/chart cards, results, object details | Saved analyses, column controls, linked selection |
| Map | Map-dominant canvas, layer rail, feature inspector, time controls | Preserve extent; resize rails; reorder layers when multiple layers are supported |
| Models | Catalog, comparison, objective/deployment detail, run evidence | Search/filter/sort by capability and lifecycle; compare selected models |
| Decision | Evidence, scenario inputs, recommendations, results | Resizable comparison panes; pin evidence; explicit scenario execution |
| Ops | Feed/incident queue plus selected-item detail and trends | Persistent filters and resizable list/detail split |
| Workshop | Section tree, real page preview, widget palette, inspector | Nested rows/columns; widget placement/reorder/resize; runtime mode |
| AIP Logic | Typed graph plus input, output, and execution trace | Shared graph gestures; selected-block trace; explicit run boundary |
| Investigations | Freely arranged entities and evidence with findings panel | Group/select/move; stable evidence links and undo |
| Entity Resolution | Candidate queue, side-by-side records, differences, decision panel | Explicit merge/split review; movable evidence panes and keyboard navigation |
| Platform Graph | Searchable dependency graph plus resource inspector | Expand neighbors, fit selection, saved view, clear graph-vs-resource removal |
| Validation | Issue queue, severity filters, selected failure evidence | Click an issue to focus the affected field/node; preserve filter state |
| Data & Media | Resource grid, schema/preview/content tabs, inspector | Full result access, column controls, visible upload progress |
| Automate | Condition/effect authoring and activity results | Typed clauses and ordered effects with meaningful reorder; explicit activate |
| Security | Scoped navigation, policy/marking lists, selected detail | Clear scope and effective access; resizable panes; explicit changes |
| Control Panel | Searchable settings categories and list/detail forms | Reuse command search; favorites; preserve filters and selected entity |
| Vertex | Relationship exploration graph, search-around, detail | Free node movement, grouping, neighbor expansion, undo |
| Fusion | Spreadsheet, formula bar, sheet tabs, data bindings | Column resizing, tab reorder, cell/range keyboard behavior |
| Analytics | Ordered transform boards and chart cards with results | Structured field/operator inputs; board reorder with downstream validation |
| Delivery | Product/version list, dependency view, installation status | Searchable versions; readable changes/dependencies; explicit publish/install |
| Global navigation, account, and help | Stable shell with compact rail, searchable app catalog, recents | Preserve location/context when switching; accessible focus restoration |

Do not apply persisted drag ordering to a sorted data result unless the data model defines an order. In those cases, rearrange columns or presentation cards instead.

## Delivery order and completion gates

1. **Shared reliability:** Finish pipeline movement, drag cancellation, keyboard alternatives, save-state feedback, and pane gesture ownership. One gesture must produce one undo command. Start the data-grid work alongside this because it affects most non-canvas screens.
2. **Core exploration:** Roll the grid and pane shell into Object Explorer, Data & Media, Ontology, and Map. Preserve filters, selected IDs, and viewport on transitions. Link object selection between charts, tables, maps, and inspectors.
3. **True Workshop composition:** Build section-tree layout, insertion previews, widget resize, binding preservation, and responsive runtime preview. Prototype the inspected filter/KPI/map/table arrangement as the acceptance example.
4. **Analysis and AI:** Apply the shared patterns to Analytics, Fusion, Vertex, Investigations, AIP Logic, Decision, and Models. Scope undo to the gesture or operation; make context and evidence discoverable.
5. **Operations and governance:** Apply reusable list/detail and search patterns to Ops, Automate, Validation, Delivery, Security, and Control Panel. Make state transitions explicit and preserve audit/review flows.
6. **Polish and rollout:** Standardize labels, density, empty/error/loading states, saved views, and narrow-screen layouts. Add floating panes only after docking/restore works reliably.

Acceptance must demonstrate the following outcomes:

- Graph drops land under their preview at multiple zoom levels and after panel resize. A single undo reverses an entire drag, including connected edge insertion.
- A widget can move between Workshop sections without losing configuration, bindings, or selection. Preview reflows at desktop/tablet/mobile widths rather than shrinking a graph.
- Table views expose every authorized row through paging/virtualization and every intended field through schema-driven columns. Show totals and any preview limit.
- A saved analysis restores filters/charts/sorts; personal docking changes do not rewrite a published artifact.
- Map refreshes and layer-panel resizing preserve a user's manually chosen geographic extent.
- Keyboard users can add, move, reorder, resize, cancel, restore, and inspect without relying solely on drag gestures.
- Pane drag, node drag, range selection, text selection, map pan, and list scrolling do not intercept one another.
- Failed persistence retains edits and presents a recoverable state. Closing a temporary panel restores focus to its invoking control.
- On narrow screens, useful content remains visible through drawers or tabs; panels cannot become permanently unreachable.
- Validate the existing drag, evaluator, and pane-layout suites plus focused grid/composition tests. Run build and applicable repository release checks when implementing. No runtime tests were run for this document-only review.

## Coverage ledger: all 61 launcher entries

“Entry” means rendered landing/list/setup UI was inspected, not that the editor was exercised. “Workspace” means content controls beyond a landing page were inspected. Empty means the displayed list or view was empty under its current scope.

| # | Application | Coverage / visible evidence |
| --- | --- | --- |
| 1 | Control Panel | Entry: settings search, organization scope, favorites, administration categories |
| 2 | Resource Management | Workspace: usage metrics/chart controls, time range, accounts, queues, reports |
| 3 | Upgrade Assistant | Workspace: assignee/admin views, filters, due dates, grouped upgrade table |
| 4 | AIP Analyst | Workspace: unsaved analysis, chat/input, model/context tools, outline; no prompt sent |
| 5 | Contour | Entry: empty Recents, Favorites, new analysis, examples; editor unverified |
| 6 | Fusion | Entry: empty Recents, Favorites, new spreadsheet; editor unverified |
| 7 | Insight | Entry: workbook/object-set tabs, object-type quick starts; workbook list empty |
| 8 | Map | Workspace: unsaved map, layer rail, select/zoom/timeline tools; no layers added |
| 9 | Notepad | Entry: document/template choices, search, lists, examples; editor unverified |
| 10 | Quiver | Entry: empty Recents, analysis creation and examples; editor unverified |
| 11 | Vertex | Entry: graphs/templates/search-arounds, search and exploration; graph editor unverified |
| 12 | Carbon workspaces | Limited: no workspaces available or no access, per displayed message |
| 13 | Custom Widgets | Entry: empty Recents, Favorites, create widget set |
| 14 | Examples (Build with AIP) | Entry: searchable catalog, featured/installed examples; nothing installed |
| 15 | Machinery | Entry: empty Recents, new graph, example; editor unverified |
| 16 | SQL Studio | Workspace: resource explorer, worksheet tabs, editor, results/history; no query run |
| 17 | Slate | Entry: empty Recents, new application; editor unverified |
| 18 | Solution Designer | Entry: embedded example diagram, planning and new-diagram entry points |
| 19 | Workshop | Workspace: existing operational dashboard, editor, section inspector and layout sizing |
| 20 | Artifacts | Entry: package-type selector, search, repository creation and guidance |
| 21 | Build Schedules | Entry: scope/search/sort/filter controls; zero matching schedules |
| 22 | Builds | Workspace: job filters, dates, status tabs, existing build row and duration |
| 23 | Code Repositories | Entry: pull-request tabs, repository search, Recents/Favorites; no recent repositories |
| 24 | Code Workspaces | Entry: running workspace section, list and IDE filters; none running |
| 25 | Compute Modules | Entry: recent modules, create, examples; no recent activity |
| 26 | Data Connection | Entry: Sources/Syncs/Agents/Listeners/External stacks; three onboarding paths |
| 27 | Data Health | Entry: Monitoring views/Health checks/Check groups; setup state |
| 28 | Data Lineage | Workspace: empty graph, pan/select/layout/expand/snap/minimap and contextual tabs |
| 29 | HyperAuto | Entry: no existing pipelines; link to supported data sources |
| 30 | Jupyter | Entry: IDE-specific URL to shared Code Workspaces; no notebook launched |
| 31 | Pipeline Builder | Workspace: prior graph inspection and verified panning; landing rechecked |
| 32 | RStudio | Entry: IDE-specific URL to shared Code Workspaces; no runtime launched |
| 33 | Time Series Catalog | Entry: sync/object/derived-series tabs, counts and creation guidance |
| 34 | VS Code | Entry: IDE-specific URL to shared Code Workspaces; no runtime launched |
| 35 | DevOps | Entry: store selection/creation prerequisite and product-delivery guidance |
| 36 | Developer Console | Entry: applications/OAuth tabs, search/sort, empty list and templates |
| 37 | Global Branching | Entry: branches/proposals lists, status and history links; none open |
| 38 | Marketplace | Entry: store/product search, installation entry point, store table; no installation |
| 39 | AIP Chatbot Studio | Entry: search/list filters, examples; no recent chatbot opened |
| 40 | AIP Document Intelligence | Limited: media-set selection/upload prerequisite; object-type path marked Coming soon |
| 41 | AIP Evals | Entry: empty Recents, new suite, examples; result editor unverified |
| 42 | AIP Logic | Entry: function search/list and examples; no existing function opened |
| 43 | Model Catalog | Workspace: lifecycle/type/provider filters, models and Compare control; no model execution |
| 44 | Model Studio | Limited: opened Choose file location dialog; canceled without saving |
| 45 | Modeling Objectives | Entry: input/output/project/status filters and empty objectives list |
| 46 | Automate | Entry: Overview/Automations, condition/effect explanation and examples |
| 47 | Foundry Rules | Entry: existing/pending/old workflow tabs; empty workflow list |
| 48 | Object Explorer | Workspace: object catalog, Route Alert analysis, charts/results/links, custom-layout menu |
| 49 | Ontology Manager | Workspace: object overview, relationships/dependents, properties table and property inspector |
| 50 | Value Types | Entry: base-type categories, table, onboarding; no value types shown |
| 51 | Workflow Lineage | Entry: search/ownership filters and empty workflow list |
| 52 | Approvals | Entry: inbox/creator/all scope, request/status/person/project filters; no requests |
| 53 | Checkpoints | Entry: review/configuration, scope/time/resource filters; no discoverable records |
| 54 | Cipher | Entry: empty Recents, new channel, examples; channel editor unverified |
| 55 | Projects & files | Workspace: file catalog, filters, roles, resizable region, sortable table |
| 56 | Sensitive Data Scanner | Limited: space selection prerequisite; no scan configured or run |
| 57 | AI FDE | Workspace: context categories, tool approval, model controls, outline; no prompt sent |
| 58 | Issues | Entry: status/priority/assignee/date filters; no matching open issues |
| 59 | Linter | Entry: resilience and savings categories, recommendation counts, impact tracking |
| 60 | Training | Entry: personalized learning, role-based tracks, workflow starting points |
| 61 | Walkthroughs | Entry: search/list/status columns and existing published walkthrough |

The original Home/global launcher review plus this ledger covers the application's exposed catalog. Authentication transitions, hidden administrative pages, every nested editor state, mobile Foundry behavior, and persistence of Foundry drag operations remain outside verified coverage.
