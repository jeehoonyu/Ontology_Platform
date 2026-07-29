import { useState, type DragEvent, type PointerEvent as ReactPointerEvent } from "react";
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

export function PipelineCanvas({
  canvas,
  zoom,
  selectedNodeId,
  details,
  onSelect,
  onDrop,
  onDragOver,
  onInsertEdge,
  onContextInsert,
  onMoveNode,
  onDeleteNode
}: {
  canvas: PipelineCanvasState | null;
  zoom: number;
  selectedNodeId: string;
  details?: PipelineNodeDetails | null;
  onSelect: (nodeId: string) => void;
  onDrop: (event: DragEvent<HTMLDivElement>) => void;
  onDragOver: (event: DragEvent<HTMLDivElement>) => void;
  onInsertEdge: () => void;
  onContextInsert: (nodeType: string) => void;
  onMoveNode: (nodeId: string, position: { x: number; y: number }, commit: boolean) => void;
  onDeleteNode: (nodeId: string) => void;
}) {
  const [dragging, setDragging] = useState<{
    nodeId: string;
    offsetX: number;
    offsetY: number;
    startX: number;
    startY: number;
  } | null>(null);
  const [dropActive, setDropActive] = useState(false);
  const nodes = canvas?.nodes || [];
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const selectedNode = byId.get(selectedNodeId);
  const toCanvasPoint = (event: ReactPointerEvent<HTMLElement>) => {
    const container = event.currentTarget.closest(".pipeline-canvas") as HTMLDivElement | null;
    const rect = container?.getBoundingClientRect();
    return {
      x: ((event.clientX - (rect?.left || 0) + (container?.scrollLeft || 0)) / zoom),
      y: ((event.clientY - (rect?.top || 0) + (container?.scrollTop || 0)) / zoom)
    };
  };

  function startNodeDrag(event: ReactPointerEvent<HTMLButtonElement>, node: PipelineNode) {
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    const point = toCanvasPoint(event);
    setDragging({
      nodeId: node.id,
      offsetX: point.x - node.position.x,
      offsetY: point.y - node.position.y,
      startX: point.x,
      startY: point.y
    });
    onSelect(node.id);
  }

  function moveNode(event: ReactPointerEvent<HTMLButtonElement>) {
    if (!dragging) return;
    const point = toCanvasPoint(event);
    if (Math.hypot(point.x - dragging.startX, point.y - dragging.startY) < 3) return;
    onMoveNode(dragging.nodeId, {
      x: Math.max(0, point.x - dragging.offsetX),
      y: Math.max(0, point.y - dragging.offsetY)
    }, false);
  }

  function endNodeDrag(event: ReactPointerEvent<HTMLButtonElement>) {
    if (!dragging) return;
    const point = toCanvasPoint(event);
    if (Math.hypot(point.x - dragging.startX, point.y - dragging.startY) >= 3) {
      onMoveNode(dragging.nodeId, {
        x: Math.max(0, point.x - dragging.offsetX),
        y: Math.max(0, point.y - dragging.offsetY)
      }, true);
    }
    setDragging(null);
  }

  return (
    <div
      className={classNames("pipeline-canvas", dropActive && "drag-active")}
      onDrop={(event) => {
        setDropActive(false);
        onDrop(event);
      }}
      onDragOver={(event) => {
        setDropActive(true);
        onDragOver(event);
      }}
      onDragLeave={() => setDropActive(false)}
    >
      <div className="canvas-controls">
        <button title="Zoom in">+</button>
        <button title="Zoom out">-</button>
        <button title="Fit to view">Fit</button>
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
      <div className="canvas-stage" style={{ transform: `scale(${zoom})` }}>
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
        {nodes.map((node) => (
          <PipelineNodeCard
            key={node.id}
            node={node}
            selected={selectedNodeId === node.id}
            dragging={dragging?.nodeId === node.id}
            onSelect={onSelect}
            onPointerDown={startNodeDrag}
            onPointerMove={moveNode}
            onPointerUp={endNodeDrag}
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
  );
}

function PipelineNodeCard({
  node,
  selected,
  dragging,
  onSelect,
  onPointerDown,
  onPointerMove,
  onPointerUp
}: {
  node: PipelineNode;
  selected: boolean;
  dragging: boolean;
  onSelect: (nodeId: string) => void;
  onPointerDown: (event: ReactPointerEvent<HTMLButtonElement>, node: PipelineNode) => void;
  onPointerMove: (event: ReactPointerEvent<HTMLButtonElement>) => void;
  onPointerUp: (event: ReactPointerEvent<HTMLButtonElement>) => void;
}) {
  return (
    <button
      className={classNames("pipeline-node", node.category, node.type, selected && "selected", dragging && "dragging", node.status === "ERROR" && "error")}
      style={{ left: node.position.x, top: node.position.y }}
      onClick={() => onSelect(node.id)}
      onPointerDown={(event) => onPointerDown(event, node)}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
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
