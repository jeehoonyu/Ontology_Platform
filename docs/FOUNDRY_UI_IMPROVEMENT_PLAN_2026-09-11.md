# Foundry-inspired UI improvement plan

Date: September 11, 2026

Scope: Improve this repository's Ontology Platform using the supplied Foundry site as an interaction reference. This is a design and implementation plan; application code has not been changed.

Follow-up: The review now covers entry pages for all 61 applications in the Foundry launcher and deeper Workshop and ontology workflows. See [Platform-wide review and rollout](FOUNDRY_PLATFORM_UI_REVIEW_2026-09-11.md) for the coverage ledger, additional findings, and a plan for every local workspace. Its expanded observations supersede the initial inspection limits below.

## Evidence and limits

I inspected the authenticated [Foundry home page](https://digitalglobe.usw-17.palantirfoundry.com/workspace/narrative/), application launcher, Pipeline Builder landing page, and an existing Pipeline Builder graph. I verified background-drag panning visually. The graph exposed pan/select tools, grid snapping, layout, zoom/fit, undo/redo, selection preview, suggestions, warnings, and an outputs rail. I did not move or add nodes, deploy changes, or test persistence in Foundry. Free docking and floating panels below are proposed improvements, not claims about observed Foundry behavior. Workshop editor behavior has not been verified.

The local comparison is based on source inspection, not a browser audit of the running local application. The working tree already contains ongoing pane and drag improvements; build on that work.

## Design direction

Make the canvas the primary workspace. Users should be able to add content at the point of work, move it freely, inspect it without leaving the canvas, and rearrange supporting panels without losing context.

Use a compact global sidebar, a document header, one contextual editing toolbar, a large canvas, a right inspector, and a bottom preview drawer. The library should be searchable and collapsible. Keep document state and release actions visible in the header.

Suggested starting dimensions at 1440 × 900: navigation collapsed to 56 px while editing, library 240 px when open, inspector 300 px when open, header and toolbar 88–104 px combined, and preview drawer 220 px when expanded. Treat these as prototype values to validate. Offer a Focus layout that hides supporting panels and preserves the current selection and viewport.

## What to carry over from the reference

| Observed pattern | Application to this platform |
| --- | --- |
| Persistent global navigation and search | Preserve orientation across builders; keep recents and favorites within reach. |
| Large graph with compact node cards | Give relationships and flow priority over permanent configuration forms. |
| Explicit pan and drag-select modes | Make the meaning of an empty-canvas drag visible and predictable. |
| Layout, snap, and zoom/fit controls | Combine free positioning with easy recovery and alignment. |
| Transform tools respond to selection | Show relevant actions beside the selection or in one contextual toolbar. |
| Bottom selection preview and warnings | Inspect data and resolve issues while keeping the graph visible. |
| Saved state, proposal, history, deployment | Keep editing, validation, and publishing states understandable. |

## Current implementation and gaps

| Area | Source evidence | Planned improvement |
| --- | --- | --- |
| Pipeline canvas | `frontend/src/components/canvas/PipelineCanvas.tsx` uses a scaled stage and fixed SVG viewBox. Its +, −, and Fit buttons have no handlers. | Wire visible controls; adopt a common viewport model and verify drop coordinates at different zoom levels. |
| Shared visual builder | `frontend/src/workspaces/VisualBuilder.tsx` already uses React Flow, selection, minimap, snapping, and undo/redo. | Reuse this foundation. Add explicit pan/select controls and a snap toggle instead of permanently enabled snapping. |
| Panel layout | `frontend/src/components/layout/Pane.tsx` supports slot moves, collapse/hide, restoration, and side splitters. | Add clear docking previews, ordering within a slot, tab groups, and a height splitter for the bottom region. |
| Drag handling | `frontend/src/components/dnd/DragKit.tsx` already centralizes sensors, grips, alternate controls, and collision filtering. | Preserve this boundary; add consistent ghost previews, rejection feedback, and cancellation. |
| Layout storage | `frontend/src/lib/paneLayout.ts` stores personal layout separately from artifact revisions. | Retain this distinction when extending layouts; migrate old saved layouts and recover offscreen panes. |
| Pipeline edge insertion | Edge buttons share a callback without identifying the clicked edge. | Pass the exact edge ID and insertion point; show which connection will be replaced. |

The custom pipeline card applies the raw drag delta inside a scaled parent while its commit path divides delta by zoom. Test for a preview-to-drop jump at non-unit zoom before treating it as a confirmed runtime defect.

## Interaction specification

### 1. Add and move content — first priority

- Drag a library item to the canvas and display a ghost at its final graph coordinates.
- Highlight only compatible targets. For an invalid target, explain why and leave the original state intact.
- Drop on empty space to create an unconnected node. Drop on a compatible edge to preview insertion into that specific edge; validate before committing.
- Move nodes freely; keep connected edges attached during the gesture. Support optional 16 px snapping and temporary snap bypass.
- Multi-select and move a group while preserving relative spacing. Provide align and distribute actions.
- Use one history entry per completed gesture. Escape cancels; undo restores the entire move or insertion.
- Retain click-to-add, Move to, keyboard movement, and form-based connection alternatives.

### 2. Pan, zoom, and selection — first priority

- Pan mode: drag empty space to move the viewport. Select mode: drag empty space for a selection rectangle.
- Space temporarily enables panning when focus is outside text inputs. Show a hand cursor while active.
- Zoom around the pointer and support trackpad gestures, visible +/− controls, Fit all, and Fit selection.
- Keep viewport movement separate from document edits: panning must not mark the graph dirty.
- Preserve viewport and selection when opening, closing, or resizing a panel. Fit only on explicit request or initial loading.

### 3. Flexible panels — second priority

- Drag panels only from their headers; interacting with a table or graph inside a panel must never move the panel.
- During dragging, display left/right/bottom docking targets with a preview of the resulting size.
- Support tab grouping, tab reorder, side width resizing, bottom height resizing, collapse, hide, and restore.
- Offer named personal presets: Build, Inspect, and Focus. Reset layout is always reachable.
- Add floating panels after docking is stable. Include resize handles, bring-to-front behavior, a redock action, and viewport clamping after window resize.
- Keep node coordinates in artifact state and panel arrangement in personal view state.

### 4. Context and visual clarity — third priority

- Replace letter-only utility buttons with recognizable icons, accessible names, and tooltips.
- Use compact nodes with a type icon, meaningful title, status, and one useful metric; expose detail on selection.
- Use color for category and state with accompanying text/icons. Keep connections readable against a quiet neutral canvas.
- Show selected-node configuration in the inspector; put Preview, Schema, and Issues in real interactive drawer tabs.
- Make issues selectable so they focus the relevant node and field. Preserve selection if preview loading fails.
- Show Saving, Saved, Retry, and Conflict states without blocking movement; failed saves retain the user's work.

### 5. Apply by workspace

- Pipeline and AIP Logic: connected graph, typed ports, edge insertion, free node movement.
- Ontology: movable object cards, relationship creation, and source-field-to-property mapping with type feedback.
- Workshop: a separate composition model for dragging, resizing, and nesting widgets, with responsive layout previews. A node graph alone is not an adequate dashboard layout editor.
- Maps and object exploration: movable support panels while map pan/zoom and table scrolling retain their own gestures.

## Implementation sequence

1. **Complete interaction reliability.** Wire custom canvas controls; verify zoom/drop math, exact-edge insertion, cancellation, and one-gesture undo. Resolve which pipeline surface is canonical before consolidating rendering. Preserve existing backend APIs.
2. **Unify graph behavior.** Reuse the existing React Flow dependency for graph viewport behavior where appropriate. Keep dnd-kit for palettes, panels, and sortable lists. Ensure each gesture has one owner and compatible drop targets across pane boundaries.
3. **Extend the existing pane system.** Add bottom resizing, slot reorder, docking previews, tab groups, presets, and persisted layout migration. Test docking before introducing floating panels.
4. **Improve task clarity.** Add contextual tools, useful empty states, accessible labels, interactive preview tabs, issue navigation, and save/recovery feedback.
5. **Roll out across workspaces.** Start with Pipeline, then Ontology and AIP Logic; implement Workshop composition separately. Reuse the panel shell and gesture vocabulary everywhere.

## Acceptance criteria

- At 50%, 100%, and 150% zoom, a dropped node lands under its preview without a visible jump, including after panning and resizing panels.
- Moving a node updates its connections continuously and creates one undo step; undo restores the original arrangement.
- A pane drag never creates a node; a palette drag never relocates a pane; scrolling a list never starts either gesture.
- Users can dock, resize, hide, restore, and reset panels by pointer and through keyboard-accessible controls.
- Reload restores personal panel layout; changing the window size cannot strand a panel offscreen.
- Failed or conflicting saves preserve edits and expose a clear recovery action.
- All visible toolbar buttons work or explain why unavailable; there are no decorative action controls.
- Test the primary workflow at 1440 × 900 and 1280 × 720, plus touch and keyboard alternatives. Prototype narrower layouts with drawers instead of squeezing every panel into columns.
- Measure a representative 250-node graph: target p95 drag frame time below 32 ms on an agreed test machine, with no persistence requests for every pointer move.
- Run existing drag-affordance, evaluator, and pane-layout browser tests, add focused cases for these outcomes, and run the frontend build. Apply the repository's release checks when implementing a release.

Recommended first deliverable: one polished Pipeline workspace demonstrating palette drop, smooth pan/zoom, exact placement, contextual inspection, resizable preview, panel docking, and reliable undo. Use it as the interaction contract for the remaining workspaces.
