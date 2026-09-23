import { useRef, useState, type MutableRefObject } from "react";
import { useDndMonitor, useDraggable, useDroppable } from "@dnd-kit/core";
import { DataTable, KeyValueGrid, StatusBadge } from "../data/DataDisplay";
import { asString, classNames, formatValue } from "../../utils/format";
import type {
  NodePreview,
  NodeSuggestions,
  PipelineCanvasState,
  PipelineNode,
  PipelineNodeDetails,
  TableRow
} from "../../types";

export const ZOOM_MIN = 0.55;
export const ZOOM_MAX = 1.35;
export const ZOOM_FIT = 0.86;
export const ZOOM_STEP = 0.08;

/** The drag id of the selection rectangle. The builder stops at it before a drop
 * onto the canvas can be read as a palette entry and create a node. */
export const LASSO_ID = "lasso:canvas";

/** A node's box in stage pixels: `.pipeline-node` is 172 wide and at least 58 tall. */
const NODE_WIDTH = 172;
const NODE_HEIGHT = 58;

interface Region { x: number; y: number; width: number; height: number }

function regionFrom(start: { x: number; y: number }, delta: { x: number; y: number }, zoom: number): Region {
  const end = { x: start.x + delta.x / zoom, y: start.y + delta.y / zoom };
  return {
    x: Math.min(start.x, end.x),
    y: Math.min(start.y, end.y),
    width: Math.abs(end.x - start.x),
    height: Math.abs(end.y - start.y),
  };
}

/** A node is inside a region when its centre is. */
function inRegion(node: PipelineNode, region: Region): boolean {
  const cx = node.position.x + NODE_WIDTH / 2;
  const cy = node.position.y + NODE_HEIGHT / 2;
  return cx >= region.x && cx <= region.x + region.width && cy >= region.y && cy <= region.y + region.height;
}

export function PipelineCanvas({
  canvas,
  zoom,
  selectedNodeId,
  selection = [],
  details,
  onSelect,
  containerRef,
  onInsertEdge,
  onAddFirst,
  quickAddType,
  onContextInsert,
  onDeleteNode,
  onZoom,
  onLasso
}: {
  canvas: PipelineCanvasState | null;
  zoom: number;
  selectedNodeId: string;
  /** Nodes selected together; a drag of any one of them carries all of them. */
  selection?: string[];
  details?: PipelineNodeDetails | null;
  onSelect: (nodeId: string, extend?: boolean) => void;
  containerRef: MutableRefObject<HTMLDivElement | null>;
  onInsertEdge: () => void;
  onAddFirst?: () => void;
  quickAddType?: string;
  onContextInsert: (nodeType: string) => void;
  onDeleteNode: (nodeId: string) => void;
  /** Absolute, already clamped by the caller that owns the zoom state. */
  onZoom: (next: number) => void;
  /** The nodes a selection rectangle closed over, and whether Shift was held when it began. */
  onLasso: (nodeIds: string[], additive: boolean) => void;
}) {
  const droppable = useDroppable({ id: "pipeline-canvas" });
  // The live delta of a node drag, so the other selected nodes move with the one
  // being dragged instead of jumping when it drops. dnd-kit transforms only the
  // active draggable; the rest of a selection follows it from here. M5.
  const [carry, setCarry] = useState<{ id: string; x: number; y: number } | null>(null);
  // The selection rectangle, in stage pixels. X2 of GOAL_GRAPH_2026-09-23: a drag
  // that starts on empty canvas selects the nodes it closes over. It begins where
  // the pointer went down, measured against the stage at that moment, and grows by
  // the delta dnd-kit reports -- which already counts any scroll of the canvas since.
  const stageRef = useRef<HTMLDivElement | null>(null);
  const lassoStart = useRef<{ x: number; y: number; additive: boolean } | null>(null);
  const [lasso, setLasso] = useState<Region | null>(null);
  const endLasso = () => {
    lassoStart.current = null;
    setLasso(null);
  };
  useDndMonitor({
    onDragStart(event) {
      if (String(event.active.id) !== LASSO_ID) return;
      const pointer = event.activatorEvent as PointerEvent;
      const stage = stageRef.current?.getBoundingClientRect();
      if (!stage) return;
      lassoStart.current = {
        x: (pointer.clientX - stage.left) / zoom,
        y: (pointer.clientY - stage.top) / zoom,
        additive: pointer.shiftKey,
      };
      setLasso({ x: lassoStart.current.x, y: lassoStart.current.y, width: 0, height: 0 });
    },
    onDragMove(event) {
      const id = String(event.active.id);
      if (id.startsWith("node:")) setCarry({ id: id.slice(5), x: event.delta.x, y: event.delta.y });
      else if (id === LASSO_ID && lassoStart.current) setLasso(regionFrom(lassoStart.current, event.delta, zoom));
    },
    onDragEnd(event) {
      setCarry(null);
      const start = lassoStart.current;
      if (String(event.active.id) === LASSO_ID && start) {
        const region = regionFrom(start, event.delta, zoom);
        onLasso(nodes.filter((node) => inRegion(node, region)).map((node) => node.id), start.additive);
      }
      endLasso();
    },
    // Escape, or a pointer the system takes back: nothing is selected by it.
    onDragCancel() {
      setCarry(null);
      endLasso();
    }
  });
  const carried = carry && selection.length > 1 && selection.includes(carry.id) ? new Set(selection) : null;
  const nodes = canvas?.nodes || [];
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const selectedNode = byId.get(selectedNodeId);

  return (
    <div
      ref={(element) => {
        containerRef.current = element;
      }}
      // The drop outline is for something that can land here; a lasso lands nothing.
      className={classNames("pipeline-canvas",
        droppable.isOver && String(droppable.active?.id ?? "") !== LASSO_ID && "drag-active")}
    >
      {/* The drop target sits inside the scrolling canvas rather than being it.
          dnd-kit sums scroll offsets over the scrollable ancestors of whatever a
          drag is over, and an element is not its own ancestor, so with the canvas
          as the droppable its scroll left the sum the moment a node was over it:
          a node picked up on a canvas scrolled 100px at zoom 0.86 jumped -116.3
          stage px and was saved there. Sized to the zoomed stage and stretched to
          the canvas, so it still covers everything a drop can land on. V10 of
          GOAL_MOVEMENT_2026-09-12. */}
      <div
        ref={droppable.setNodeRef}
        className="pipeline-canvas-drop"
        style={{ minWidth: 1500 * zoom, minHeight: 700 * zoom }}
      >
      {/* These three rendered and did nothing, while a working copy of the same
          three sat in the document action row beside Deploy and Delete node --
          so the obvious place to zoom was the dead one. Zoom is a viewport
          control; it belongs on the viewport. */}
      <div className="canvas-controls">
        <button title="Zoom in" aria-label="Zoom in" onClick={() => onZoom(zoom + ZOOM_STEP)}>+</button>
        <button title="Zoom out" aria-label="Zoom out" onClick={() => onZoom(zoom - ZOOM_STEP)}>-</button>
        <button title="Fit to view" aria-label="Fit to view" onClick={() => onZoom(ZOOM_FIT)}>Fit</button>
      </div>
      <div className="canvas-legend">
        {(canvas?.legend || []).map((item) => (
          <span key={item.category}>
            <i style={{ background: item.color }} />
            {item.label}
          </span>
        ))}
      </div>
      {!nodes.length && <div className="empty canvas-empty">Generate an ontology draft or create a pipeline graph to start.</div>}
      <div className="canvas-stage" ref={stageRef} style={{ transform: `scale(${zoom})` }}>
        <LassoSurface />
        {lasso ? (
          <div className="canvas-lasso" style={{ left: lasso.x, top: lasso.y, width: lasso.width, height: lasso.height }} />
        ) : null}
        <svg viewBox="0 0 1500 700" className="edge-layer">
          {(canvas?.edges || []).map((edge) => {
            const source = byId.get(edge.source);
            const target = byId.get(edge.target);
            if (!source || !target) return null;
            const sx = source.position.x + 172;
            const sy = source.position.y + 28;
            const tx = target.position.x;
            const ty = target.position.y + 28;
            const mx = (sx + tx) / 2;
            return (
              <g key={edge.id || `${edge.source}-${edge.target}`}>
                <path d={`M ${sx} ${sy} C ${mx} ${sy}, ${mx} ${ty}, ${tx} ${ty}`} />
                <circle cx={mx} cy={(sy + ty) / 2} r="7" />
              </g>
            );
          })}
        </svg>
        {(canvas?.edges || []).map((edge) => {
          const source = byId.get(edge.source);
          const target = byId.get(edge.target);
          if (!source || !target) return null;
          return (
            <button
              key={`insert-${edge.source}-${edge.target}`}
              className="edge-insert"
              style={{ left: (source.position.x + target.position.x) / 2 + 78, top: (source.position.y + target.position.y) / 2 + 22 }}
              onClick={onInsertEdge}
              title="Insert selected node type"
            >
              +
            </button>
          );
        })}
        {!nodes.length && onAddFirst ? (
          <div className="pipeline-canvas-first">
            <strong>Empty canvas</strong>
            <span>Drag a node from the palette, or add the selected type here.</span>
            <button className="primary" onClick={onAddFirst}>
              Add {quickAddType || "node"}
            </button>
          </div>
        ) : null}
        {nodes.map((node) => (
          <PipelineNodeCard
            key={node.id}
            node={node}
            zoom={zoom}
            // What every tool acts on: the set, or the node last clicked when the set
            // is empty. It was both at once, so a node outside a multi-node selection
            // still looked selected because it had been clicked last.
            selected={selection.length ? selection.includes(node.id) : selectedNodeId === node.id}
            follow={carried && carry && carry.id !== node.id && carried.has(node.id) ? carry : null}
            onSelect={onSelect}
          />
        ))}
        {selectedNode ? (
          <div className="node-context-menu" style={{ left: selectedNode.position.x + 190, top: selectedNode.position.y - 2 }}>
            {(details?.context_actions || []).map((action) => (
              <button key={action.id} className={`context-action-${action.id}`} onClick={() => onContextInsert(action.node_type)}>
                <span>{action.label.slice(0, 1)}</span>
                {action.label}
              </button>
            ))}
            <button className="context-action-delete" onClick={() => onDeleteNode(selectedNode.id)}>
              <span>D</span>
              Delete node
            </button>
          </div>
        ) : null}
      </div>
      </div>
    </div>
  );
}

/**
 * The empty canvas, which a drag turns into a selection rectangle.
 *
 * On `DragKit`'s sensors like every other drag here, so the drag census counts it
 * and Escape cancels it the way it cancels a node drag. It sits under every node,
 * edge control and menu on the stage, so a press on any of them is theirs, and only
 * a press on bare canvas reaches it; a click stays a click below 8px of travel.
 * The listeners are spread and the attributes are not: it is not a control, so it
 * takes no role and no tab stop, and a key pressed on a button never starts it.
 * Touch is not claimed: without `touch-action: none` a finger here scrolls.
 */
function LassoSurface() {
  // Written out rather than `LASSO_ID`: the drag census reads the id literal, and
  // a constant here left the lasso missing from what this file registers.
  const draggable = useDraggable({ id: "lasso:canvas" });
  return <div ref={draggable.setNodeRef} className="canvas-lasso-surface" {...draggable.listeners} />;
}

/**
 * A node on the canvas, moved by dragging it.
 *
 * This was the fourth drag mechanism in the product and the census missed it:
 * `onPointerDown` with `setPointerCapture`, hand-rolled, counted by nothing
 * because it is neither `draggable` nor a sensor library. It worked from touch,
 * because pointer events fire for touch and `.pipeline-node` already carried
 * `touch-action: none`. It could not be reached from a keyboard at all, and a
 * node's position had no other control, so its layout was mouse-and-finger only.
 *
 * `useDraggable` moves it live through a transform and commits once at the end,
 * which also removes the uncommitted position updates the old version pushed on
 * every pointer move.
 */
function PipelineNodeCard({ node, zoom, selected, follow, onSelect }: {
  node: PipelineNode;
  zoom: number;
  selected: boolean;
  /** Another selected node's live drag, which this one moves with. */
  follow?: { x: number; y: number } | null;
  onSelect: (nodeId: string, extend?: boolean) => void;
}) {
  const draggable = useDraggable({ id: `node:${node.id}` });
  // dnd-kit reports the drag in screen pixels, and this card sits inside a stage
  // scaled by `zoom`, so the transform is divided by it -- the same division the
  // drop already makes. Without it the preview moved 48.4 screen pixels of an
  // 88-pixel landing at the zoom floor, and 35% past it at the ceiling: the node
  // jumped on release. V7 of GOAL_MOVEMENT_2026-09-12.
  const moved = draggable.transform || follow;
  const scaled = moved ? { x: moved.x / zoom, y: moved.y / zoom } : null;
  return (
    <button
      ref={draggable.setNodeRef}
      className={classNames("pipeline-node", node.category, node.type, selected && "selected", draggable.isDragging && "dragging", node.status === "ERROR" && "error")}
      data-node-id={node.id}
      data-in-selection={selected ? "true" : "false"}
      style={{
        left: node.position.x,
        top: node.position.y,
        transform: scaled ? `translate3d(${scaled.x}px, ${scaled.y}px, 0)` : undefined,
        zIndex: draggable.isDragging ? 3 : undefined
      }}
      onClick={(event) => onSelect(node.id, event.shiftKey)}
      {...draggable.attributes}
      {...draggable.listeners}
    >
      <strong>{node.label}</strong>
      <small>{node.row_count ?? 0} rows</small>
      <span>{node.type}</span>
      {node.errors?.length ? <StatusBadge value="error" /> : null}
    </button>
  );
}

export function BottomDrawer({
  preview,
  selectedNode,
  suggestions,
  validation,
  details
}: {
  preview: NodePreview | null;
  selectedNode: PipelineNode | null;
  suggestions: NodeSuggestions | null;
  validation?: PipelineCanvasState["validation"];
  details?: PipelineNodeDetails | null;
}) {
  const [tab, setTab] = useState("preview");
  const rows = drawerRows(tab, preview, selectedNode, suggestions, validation, details);
  // How many rows the node holds, from the same source as the rows shown: a preview of the
  // first 50 of 60 rows read as the node's whole output.
  const heldRows = tab !== "preview" ? null
    : preview?.rows ? preview.row_count
    : details?.preview.rows ? details.preview.row_count
    : selectedNode?.row_count ?? null;
  return (
    <section className="bottom-drawer">
      <nav>
        {["selection_preview", "preview", "transformations", "suggestions", "pipeline_warnings"].map((item) => (
          <button key={item} className={tab === item ? "active" : ""} onClick={() => setTab(item)}>{item.replace(/_/g, " ")}</button>
        ))}
      </nav>
      {tab === "selection_preview" && selectedNode ? (
        <div className="drawer-split">
          <KeyValueGrid data={{
            id: selectedNode.id,
            type: selectedNode.type,
            category: selectedNode.category,
            status: selectedNode.status,
            rows: selectedNode.row_count ?? details?.preview.row_count ?? 0
          }} />
          <DataTable rows={details?.preview.columns || selectedNode.schema?.fields || []} empty="No columns found for this node." />
        </div>
      ) : null}
      {tab === "preview" && typeof heldRows === "number" && heldRows > rows.length ? <p className="table-truncated" role="note">Previewing the first {rows.length.toLocaleString()} of {heldRows.toLocaleString()} rows</p> : null}
      {tab !== "selection_preview" ? <DataTable rows={rows} empty="No preview rows, suggestions, or warnings for this node." /> : null}
    </section>
  );
}

function drawerRows(
  tab: string,
  preview: NodePreview | null,
  selectedNode: PipelineNode | null,
  suggestions: NodeSuggestions | null,
  validation: PipelineCanvasState["validation"] | undefined,
  details: PipelineNodeDetails | null | undefined
): TableRow[] {
  if (tab === "preview") return preview?.rows || details?.preview.rows || selectedNode?.sample || [];
  if (tab === "suggestions") return suggestions?.suggestions || details?.suggestions.suggestions || [];
  if (tab === "pipeline_warnings") return validation?.warnings || validation?.errors || [];
  if (tab === "transformations" && selectedNode) {
    return Object.entries(selectedNode.config || {}).map(([key, value]) => ({ key, value: formatValue(value) }));
  }
  return [];
}

export function MiniGraph({ nodes, edges }: { nodes: TableRow[]; edges: TableRow[] }) {
  const width = 940;
  const height = 380;
  const positioned: Array<TableRow & { x: number; y: number }> = nodes.slice(0, 40).map((node, index) => {
    const angle = (Math.PI * 2 * index) / Math.max(nodes.length, 1);
    return { ...node, x: width / 2 + Math.cos(angle) * 320, y: height / 2 + Math.sin(angle) * 135 };
  });
  const byId = new Map(positioned.map((node) => [asString(node.id), node]));
  return (
    <svg className="mini-graph" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Platform graph">
      {edges.slice(0, 80).map((edge, index) => {
        const source = byId.get(asString(edge.source || edge.source_id));
        const target = byId.get(asString(edge.target || edge.target_id));
        if (!source || !target) return null;
        return <line key={index} x1={Number(source.x)} y1={Number(source.y)} x2={Number(target.x)} y2={Number(target.y)} />;
      })}
      {positioned.map((node) => (
        <g key={asString(node.id)} transform={`translate(${Number(node.x)}, ${Number(node.y)})`}>
          <circle r="18" />
          <text y="4">{asString(node.kind || node.type || "?").slice(0, 2).toUpperCase()}</text>
          <title>{asString(node.label || node.title || node.id)}</title>
        </g>
      ))}
    </svg>
  );
}
