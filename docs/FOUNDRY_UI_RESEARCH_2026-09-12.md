# Foundry UI research: movement, layout, and state

Research update: September 12, 2026. Extends the [platform-wide review and 61-entry coverage ledger](FOUNDRY_PLATFORM_UI_REVIEW_2026-09-11.md).

The recommended direction is a consistent workspace shell with movement appropriate to each task: dockable tool panels, spatial graphs, structured application layouts, rearrangeable analytical cards, and typed data transfers. Each operation needs a visible destination and a predictable way to cancel or recover.

This update adds official documentation research and three visual references. Public documentation describes product capabilities; it does not prove that a feature is enabled in the DigitalGlobe enrollment. The September 11 live observations remain the evidence for that enrollment. This update did not repeat the 61-entry scan or test saved edits. Local code observations in the earlier report remain a dated baseline and must be rechecked before implementation.

## Visual references

These are Palantir's original documentation assets, served remotely with attribution. They are reference examples, not screenshots of our implementation. GIF animation and remote-image display depend on the Markdown viewer; the source pages remain available below each example.

### 1. Make the drag origin and destination visible

![Official Quiver example showing a card drag handle, floating header preview, and blue insertion line](https://www.palantir.com/docs/resources/foundry/quiver/howto-dashboards-drag-handle.png?width=500px)

The visible grip separates moving the card from interacting with its chart. The insertion line describes the placement before release. This static image was visually inspected in the browser. Source: [Quiver dashboard creation](https://www.palantir.com/docs/foundry/quiver/dashboards-create).

**Apply locally:** put the grip in a stable header location; expose it on keyboard focus as well as hover; keep chart brushing, text selection, and scrolling usable inside content. Use a labeled destination preview such as “Insert above Results.”

### 2. Use structured placement for dashboards

![Official animated example of adding a card to an empty Quiver dashboard](https://www.palantir.com/docs/resources/foundry/quiver/howto-dashboards-add-card-to-empty-dashboard.gif)

Quiver documents highlighted drop zones and automatic alignment within dashboard rows. Its documented regular-card row limit is three; this is a Quiver-specific constraint, not a platform-wide rule. Source: [Quiver dashboard creation](https://www.palantir.com/docs/foundry/quiver/dashboards-create).

**Apply locally:** use row/column insertion and predictable sibling reflow for operational dashboards. Offer presets for one, two, and three columns, with minimum usable widget sizes. Retain independent configuration for nested layouts where needed.

### 3. Support rearranging and resizing analytical cards

![Official animated example of resizing and rearranging cards in a Quiver analysis canvas](https://www.palantir.com/docs/resources/foundry/quiver/howto-analysis-canvas-resize-cards.gif)

Quiver's canvas documentation places movement on the upper-left handle and resizing at the lower-right corner. Cards can also move between canvases through the contents panel or a menu. Source: [Quiver canvas mode](https://www.palantir.com/docs/foundry/quiver/analysis-canvas).

**Apply locally:** provide card resizing, named canvases, an outline, and a “Move to…” action. Keep analytical presentation layout distinct from graph connections and computation order. The GIF URLs were verified from the official pages' image elements; their full animation sequences were not independently interaction-tested.

## Findings that change or sharpen the plan

| Area | Documented evidence | Recommendation for our platform |
| --- | --- | --- |
| Workshop sizing | Widget sizing includes content-driven Auto (max), fixed-pixel Absolute, and proportional Flex. [Widgets](https://www.palantir.com/docs/foundry/workshop/concepts-widgets) | Show readable choices: “Fit content,” “Fixed size,” and “Share available space,” with advanced values. Distinguish fixed sizing from absolute positioning. |
| Workshop structure | Sections support conditional visibility and copy/paste with either shared or duplicated input variables. [Layouts](https://www.palantir.com/docs/foundry/workshop/concepts-layouts) | Show hidden sections in the outline with a condition indicator. When duplicating bound widgets, explicitly choose whether inputs remain linked. |
| Runtime data drops | A section can receive object/object-set payloads, populate an output variable, and trigger an event. Drop Handling can require enrollment enablement. [Workshop drag and drop](https://www.palantir.com/docs/foundry/workshop/drag-and-drop) | Treat dropping data as its own operation. Preview payload type, count, destination, and effect; reject incompatible targets. Keep data transfer separate from rearranging that same section. |
| Object Explorer | Saved layouts include charts, table columns, and sorting; personal defaults can override global defaults. [Explore with charts](https://www.palantir.com/docs/foundry/object-explorer/explore-charts) | Add a scoped saved-view menu. Distinguish “Use as my default” from changing a shared default. Preserve table configuration with the exploration view. |
| Slate | Built-in positioning, flex containers, multi-selection alignment, and distribution are documented. Guidance favors restrained nesting. [Complex layouts](https://www.palantir.com/docs/foundry/slate/best-practices-complex-layouts) | Add align/distribute for appropriate multi-selections and inspectable parent containers. Keep graph node coordinates out of the operational page layout model. |
| Carbon navigation | A workspace curates resources, object-aware discovery, anchored modules, and additional module tabs. [Workspaces](https://www.palantir.com/docs/foundry/carbon/workspaces-overview) | Offer task-oriented landing pages and pinned workflow tabs. Keep a route back to the full app catalog. Carbon's actual configured runtime remains access-limited in the earlier live review. |
| Map | The current Workshop Map exposes visibility, selection locking, bidirectional selected objects, and draggable geometry ordering. [Map widget](https://www.palantir.com/docs/foundry/workshop/widgets-map) | Separate layer order, visibility, and interaction lock. Keep map/table selection synchronized. Reordering geometry is documented; do not infer that moving a layer changes an object's geographic position. |
| Explicit state saving | Workshop saves eligible variable values and optionally the current page; it does not automatically persist every preference across sessions. [State saving](https://www.palantir.com/docs/foundry/workshop/state-saving) | Name the save action by scope. A layout save must not silently imply that filters, drafts, or live selections were saved. |
| Rendering behavior | Keeping widgets mounted can retain state but also retain memory, computation, and requests. Hidden widgets may initially measure their size incorrectly. [Display optimization](https://www.palantir.com/docs/foundry/workshop/widget-display-optimization) | Preserve drafts explicitly; mount expensive widgets selectively. Remeasure charts/maps after reveal and resize. Measure resource use during repeated tab changes. |
| Mobile | Workshop has dedicated mobile support and widget availability constraints; enrollment availability varies. [Mobile overview](https://www.palantir.com/docs/foundry/workshop/mobile-overview) | Specify a mobile consumption experience separately from desktop editing. Use sheets, sequential content, and tap actions on narrow screens; test map support explicitly. |
| Accessible movement | WCAG 2.5.7 requires a single-pointer alternative to dragging, subject to its exceptions. Keyboard support alone does not satisfy that requirement. [W3C guidance](https://www.w3.org/WAI/WCAG22/Understanding/dragging-movements.html) | Provide clickable Move, Resize, and placement controls alongside drag and keyboard operations. Test with clicks/taps only and keyboard only as separate cases. |

### Four state scopes to expose clearly

The following is a proposed local design, not a claim about Foundry's internal architecture.

| State | Example | Persistence and user-facing action |
| --- | --- | --- |
| Personal workspace | Inspector on right; preview height; collapsed tool panel | Save automatically per user and workspace; “Reset workspace” restores panel defaults only. |
| Authored artifact | Pipeline node positions; dashboard section structure; widget bindings | Save with the artifact draft/version; use its normal edit permissions and undo history. |
| Saved analysis view | Visible columns, chart configuration, sorting, explicitly selected filters | “Save view…” names included state and intended audience. Distinguish private from shared views. |
| Transient work | Current selection, open menu, pointer preview, unsent input | Keep ephemeral UI transient. Recover unsent drafts through an explicit draft policy; do not publish them with layout preferences. |

Before adding more drag surfaces, classify every existing save/reset operation using this table. Establish stable widget and section IDs so moving a component does not recreate it or lose its configuration.

## Interaction contract

These are proposed acceptance requirements for implementation.

| Stage | Required behavior |
| --- | --- |
| Discover | A grip or resize boundary is visible on hover/focus, with a plain-language tooltip and a menu alternative. |
| Start | Clicking content keeps its normal meaning. Drag begins from the designated handle after an activation threshold. |
| Preview | Show a lightweight ghost and one unambiguous target. Distinguish insert, nest, connect, reorder, and transfer. |
| Traverse | Auto-scroll the active destination container near its edge. On graphs, account for viewport pan and zoom. Avoid scrolling an unrelated outer page. |
| Reject | Explain incompatible destinations with text and shape/icon feedback as well as color. Release leaves state unchanged. |
| Commit | Apply one logical operation on release; keep selection/focus attached to the moved item. Show the final placement. |
| Cancel | Escape or pointer cancellation restores the exact starting arrangement and clears overlays. |
| Recover | One Undo reverses one completed move/resize. A no-op drag creates no history entry. |

For data transfer, the destination preview should use an effect label such as “Use 12 flights as chart input.” For panel movement, use “Dock Preview below.” For layout editing, use “Move chart into Summary.” These phrases make an identical physical gesture understandable in different contexts.

## Delivery order and reviewable outcomes

This sequencing refines the earlier platform-wide rollout. It does not assume that the September 11 source gaps are still unfixed.

| Priority | Work package | First affected surfaces | Completion evidence |
| --- | --- | --- | --- |
| P0 | Recheck the existing pane and canvas implementation against this contract | Shared Pane, Pipeline Builder, VisualBuilder | Record current behavior and remaining gaps; preserve completed work. Check active handlers, coordinate conversion, history boundaries, and reset scope. |
| P0 | Reliable move/resize/cancel/undo and explicit state ownership | Shared shell and pipeline | A panel move does not dirty a pipeline. A node move creates one undo entry. Escape causes no mutation. Reload restores the intended scope. |
| P1 | Typed drop targets and accessible alternatives | Graphs, widget palette, object exploration | Each target describes its effect; invalid payloads produce no mutation; core tasks work with clicks only and keyboard only. |
| P1 | Nested operational layout editor | Workshop-like workspace | Add a chart beside a table; change their proportions; move both as a section; preserve data bindings; recover with Undo. |
| P1 | Saved views and durable exploration state | Explorer, tables, analytics | Save columns/sorts/charts; reopen the view; show which filters are included; keep personal defaults separate from shared changes. |
| P2 | Map and content-specific polish | Map, Fusion, documents, AI/SQL panes | Layer order is clear; viewport stays stable during ordinary filtering; table previews disclose truncation; editor/result resizing preserves drafts. |
| P2 | Task-oriented discovery and narrow-screen presentation | Home, navigation, operational apps | Users can resume a named workflow; narrow layouts keep primary actions reachable; desktop-only functionality is clearly represented. |
| P2 | Rendering and layout performance | Dashboards, graphs, large tables | Profile representative loaded workspaces. Record frame timing, memory, and data requests during resize/tab switching before broad rollout. |

### Concrete evaluation scenarios

Run these against a local test fixture before testing on shared production resources. Suggested sizes are test inputs, not measured capacity claims.

1. **Graph coordinates:** move a node at 50%, 100%, and 150% zoom, with a panned viewport. The committed position matches the ghost and connected edges remain attached. Fit and zoom buttons work.
2. **Nested drop:** move a chart between two sections near a scrolling boundary. Only the chosen container changes; the indicator never ambiguously targets both parent and child.
3. **Undo:** drag for several seconds, release, and Undo once. Verify the full move is reversed. Repeat for resizing and multi-selection.
4. **Workspace recovery:** move Preview below the editor, resize it, reload, then reset the workspace. Verify artifact content and unsent input are unaffected by the reset.
5. **Data transfer:** drop a valid object set onto a chart input, then try an incompatible payload. Verify the valid effect occurs once and the invalid drop changes nothing.
6. **Saved view:** reopen a view with columns, sorting, and filters. Check private/global default precedence and missing/deleted fields.
7. **Input alternatives:** complete a reorder, cross-section move, and resize using only taps/clicks, then only keyboard. Verify focus remains visible and outcomes are announced where needed.
8. **Map stability:** pan, select objects, change a filter, resize the panel, and toggle a layer. Preserve the camera unless the user chooses a fit/focus action.
9. **Rendering:** exercise a dashboard with 20 widgets and a graph with 200 nodes. After ten tab switches and panel resizes, check for avoidable refetching, draft loss, memory growth, and unusable interaction delay.
10. **Responsive use:** inspect at 1440, 1024, and 390 CSS pixels. Confirm primary tasks remain reachable; evaluate a designed mobile view separately from a compressed desktop editor.

## Remaining uncertainty

The prior broad inspection covered all 61 launcher entry points, but many opened empty lists or setup screens. Model Studio, restricted Carbon content, and other nested editors are still not validated in a populated workflow. The public references above reduce uncertainty about the intended interaction models; they do not fill those live-testing gaps.

No application source was changed, no data was submitted to Foundry, and no saved view or artifact was published during this research update. This deliverable is an illustrated plan with acceptance criteria, not an implemented redesign.
