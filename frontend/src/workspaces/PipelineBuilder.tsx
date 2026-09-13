import { ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { DndContext, useDraggable, type DragEndEvent } from "@dnd-kit/core";
import { dropPointOf, slotAwareCollision, useWorkspaceSensors } from "../components/dnd/DragKit";
import { PaneHost, usePaneLayout } from "../components/layout/Pane";
import { DataGrid } from "../components/data/DataGrid";
import type { PaneSpec } from "../lib/paneLayout";
import { postJson } from "../api";
import {
  cancelJob,
  compilePipelinePlan,
  enqueuePipelineJob,
  executePipelinePlan,
  getJob,
  retryJob,
  runPipelineJob
} from "../api/jobApi";
import { getPipelineOntologyContracts } from "../api/pipelineOntologyApi";
import {
  createPipelineNode,
  deletePipelineNode,
  getPipelineCanvas,
  getPipelineNodeDetails,
  getPipelineOutputs,
  getPipelineState,
  insertPipelineNode,
  previewPipelineNode,
  savePipelineLayout,
  suggestPipelineNode,
  updatePipelineNode
} from "../api/workspaceState";
import { BottomDrawer, PipelineCanvas, ZOOM_MAX, ZOOM_MIN } from "../components/canvas/PipelineCanvas";
import { DataTable, EmptyState, KeyValueGrid, Panel, StatusBadge } from "../components/data/DataDisplay";
import { Toolbar } from "../components/workbench/Workbench";
import { useAsyncState } from "../hooks/useAsyncState";
import { asRows, asString, classNames, formatValue } from "../utils/format";
import type {
  NodePreview,
  NodeSuggestions,
  JsonObject,
  PipelineCanvasState,
  PipelineNodeDetails,
  PipelineOntologyContract,
  PipelineOntologyContractState,
  PipelineOutputsState,
  PipelineExecutionPlan,
  PipelineExecutionStrategy,
  PipelineUiState,
  PlatformJob
} from "../types";

/**
 * The pipeline builder's header. It lived in the shared primitives file under
 * the name `WorkspaceHeader`, where it read as the header every workspace should
 * use -- and it hardcodes the word "Batch" and highlights a tab called "Graph".
 * One workspace used it and two wrote the same markup by hand, which is what a
 * primitive nobody can trust looks like from the outside.
 */
function PipelineHeader({ title, actions }: { title: string; actions: ReactNode }) {
  return (
    <div className="workspace-header">
      <div>
        <strong>{title}</strong>
        <span>Batch</span>
      </div>
      <div className="button-row">{actions}</div>
    </div>
  );
}

// The four regions of this screen, and where each starts. The canvas is
// anchored: it may be resized around and never moved or hidden, because a
// pipeline builder with the pipeline put away is not a layout, it is a dead end.
const PIPELINE_PANES: PaneSpec[] = [
  { id: "library", title: "Add data / transforms", slot: "left" },
  { id: "canvas", title: "Pipeline", slot: "center", anchored: true },
  { id: "output", title: "Outputs", slot: "right" },
  { id: "drawer", title: "Evidence", slot: "bottom" }
];

export function PipelineBuilder() {
  const [refreshKey, setRefreshKey] = useState(0);
  const [selectedGraphId, setSelectedGraphId] = useState("");
  const [selectedNodeId, setSelectedNodeId] = useState("");
  // Nodes selected together, so one drag can carry several. M5 of
  // GOAL_PANES_2026-09-11. The primary node still drives details, preview and the
  // context menu; this only widens what a node drag moves.
  const [selection, setSelection] = useState<string[]>([]);
  const [canvas, setCanvas] = useState<PipelineCanvasState | null>(null);
  const [preview, setPreview] = useState<NodePreview | null>(null);
  const [suggestions, setSuggestions] = useState<NodeSuggestions | null>(null);
  const [details, setDetails] = useState<PipelineNodeDetails | null>(null);
  const [outputs, setOutputs] = useState<PipelineOutputsState | null>(null);
  const [contracts, setContracts] = useState<PipelineOntologyContractState | null>(null);
  const [zoom, setZoom] = useState(0.86);
  // Committed node moves, newest last, each with every position before it. V6 of
  // GOAL_MOVEMENT_2026-09-12: a drop saved positions to the server and nothing
  // could take a move back. A move belongs to the graph it was made on, so a
  // different graph starts with nothing to undo.
  const [moves, setMoves] = useState<Array<{ graphId: string; nodeId: string; positions: Record<string, { x: number; y: number }> }>>([]);
  useEffect(() => { setMoves([]); setSelection([]); }, [selectedGraphId]);
  useEffect(() => {
    if (!selection.length) return;
    const clear = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if ((event.target as HTMLElement | null)?.closest("input, textarea, select")) return;
      setSelection([]);
    };
    window.addEventListener("keydown", clear);
    return () => window.removeEventListener("keydown", clear);
  }, [selection.length]);
  // Node configuration typed and not yet saved, held above the panes. A pane moved
  // to another slot is a new parent, React remounts what it holds, and the form's
  // own state went with it: measured, a plain move or `Reset panes` replaced a
  // typed label with the saved one. Keyed by graph and node, so a draft belongs to
  // the node it was typed for. V9 of GOAL_MOVEMENT_2026-09-12.
  const [nodeDrafts, setNodeDrafts] = useState<Record<string, NodeDraft>>({});
  const [quickAddType, setQuickAddType] = useState("filter");
  const canvasRef = useRef<HTMLDivElement | null>(null);
  // "slots", not "free": this one context carries the pane drags as well as the
  // node and palette drags, and only the pane drags want an arrow key to cross
  // a slot instead of moving 25px. The getter tells them apart by id prefix.
  const sensors = useWorkspaceSensors("slots");
  const paneState = usePaneLayout("pipeline", PIPELINE_PANES);
  const [executionJob, setExecutionJob] = useState<PlatformJob | null>(null);
  const [executionPlan, setExecutionPlan] = useState<PipelineExecutionPlan | null>(null);
  const [executionEngine, setExecutionEngine] = useState<"builder" | "duckdb">("builder");
  const [executionStrategy, setExecutionStrategy] = useState<PipelineExecutionStrategy>("auto");
  const [maxPartitions, setMaxPartitions] = useState(8);
  const [busyAction, setBusyAction] = useState("");
  const [actionStatus, setActionStatus] = useState("Select a node, insert transforms from edges or the node menu, then preview or deploy.");
  const state = useAsyncState<PipelineUiState>(getPipelineState, [refreshKey]);

  useEffect(() => {
    if (!executionJob || !["BLOCKED", "QUEUED", "RUNNING"].includes(executionJob.status)) return;
    const timer = window.setInterval(() => {
      void getJob(executionJob.id).then(setExecutionJob).catch(() => undefined);
    }, 1_500);
    return () => window.clearInterval(timer);
  }, [executionJob?.id, executionJob?.status]);

  useEffect(() => {
    if (!selectedGraphId && state.value?.selected_canvas?.graph.id) {
      setSelectedGraphId(state.value.selected_canvas.graph.id);
    }
  }, [state.value, selectedGraphId]);

  useEffect(() => {
    if (!selectedGraphId) return;
    let cancelled = false;
    getPipelineCanvas(selectedGraphId, selectedNodeId || undefined)
      .then((nextCanvas) => {
        if (!cancelled) {
          setCanvas(nextCanvas);
          setSelectedNodeId(nextCanvas.selected_node?.id || selectedNodeId);
        }
      })
      .catch(() => !cancelled && setCanvas(null));
    return () => {
      cancelled = true;
    };
  }, [selectedGraphId, selectedNodeId, refreshKey]);

  useEffect(() => {
    if (!selectedGraphId) return;
    let cancelled = false;
    getPipelineOutputs(selectedGraphId)
      .then((nextOutputs) => !cancelled && setOutputs(nextOutputs))
      .catch(() => !cancelled && setOutputs(null));
    return () => {
      cancelled = true;
    };
  }, [selectedGraphId, refreshKey]);

  useEffect(() => {
    if (!selectedGraphId) return;
    let cancelled = false;
    getPipelineOntologyContracts(selectedGraphId)
      .then((nextContracts) => !cancelled && setContracts(nextContracts))
      .catch(() => !cancelled && setContracts(null));
    return () => {
      cancelled = true;
    };
  }, [selectedGraphId, refreshKey]);

  useEffect(() => {
    if (!selectedGraphId || !selectedNodeId) return;
    let cancelled = false;
    Promise.all([
      previewPipelineNode(selectedGraphId, selectedNodeId).catch(() => null),
      suggestPipelineNode(selectedGraphId, selectedNodeId).catch(() => null),
      getPipelineNodeDetails(selectedGraphId, selectedNodeId).catch(() => null)
    ]).then(([nextPreview, nextSuggestions, nextDetails]) => {
      if (!cancelled) {
        setPreview(nextPreview);
        setSuggestions(nextSuggestions);
        setDetails(nextDetails);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [selectedGraphId, selectedNodeId, refreshKey]);

  async function run(action: "validate" | "preview" | "deliver") {
    if (!selectedGraphId) return;
    setBusyAction(action);
    try {
      if (action === "validate") {
        setActionStatus("Checking proposal...");
        const result = await postJson(`/pipeline-builder/graphs/${encodeURIComponent(selectedGraphId)}/validate`, {});
        setActionStatus(`Validation completed: ${formatValue((result as { status?: unknown }).status || "ok")}`);
      } else {
        setActionStatus(`Queueing Pipeline ${action}...`);
        const idempotencyKey = `${action}-${selectedGraphId}-${Date.now()}`;
        let queued: PlatformJob;
        if (executionEngine === "duckdb") {
          setActionStatus("Compiling the graph into a typed DuckDB execution plan...");
          const plan = await compilePipelinePlan(selectedGraphId);
          setExecutionPlan(plan);
          const response = await executePipelinePlan(plan.id, {
            mode: action,
            execution_strategy: action === "preview" ? "single" : executionStrategy,
            max_partitions: maxPartitions,
            idempotency_key: idempotencyKey
          });
          queued = response.execution;
        } else {
          queued = await enqueuePipelineJob(selectedGraphId, action, idempotencyKey);
          setExecutionPlan(null);
        }
        setExecutionJob(queued);
        setActionStatus(`${action} queued as ${queued.id}. Waiting for worker claim...`);
        if (queued.partition_execution && queued.dependencies?.length) {
          let shardFailed = false;
          for (let index = 0; index < queued.dependencies.length; index += 1) {
            const dependency = queued.dependencies[index];
            setActionStatus(`Executing snapshot shard ${index + 1} of ${queued.dependencies.length}...`);
            const shard = await runPipelineJob(dependency.id);
            if (!shard.job || shard.job.status !== "SUCCEEDED") {
              shardFailed = true;
              break;
            }
            setExecutionJob(await getJob(queued.id));
          }
          if (shardFailed) {
            const failed = await getJob(queued.id);
            setExecutionJob(failed);
            setActionStatus(`Distributed delivery stopped: ${failed.error || "a snapshot shard failed"}`);
            return;
          }
        }
        const ready = await getJob(queued.id);
        setExecutionJob(ready);
        const executed = await runPipelineJob(queued.id);
        if (executed.job) {
          const detail = await getJob(executed.job.id);
          setExecutionJob(detail);
          setActionStatus(`${action} ${detail.status.toLowerCase()}: ${detail.error || `${detail.progress}% complete`}`);
        }
      }
      setRefreshKey((key) => key + 1);
    } catch (error) {
      setActionStatus(`${action} failed: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setBusyAction("");
    }
  }

  async function cancelExecution() {
    if (!executionJob) return;
    setExecutionJob(await cancelJob(executionJob.id));
    setActionStatus(`Cancelled ${executionJob.id}. Its worker lease has been released.`);
  }

  async function retryExecution() {
    if (!executionJob) return;
    const queued = await retryJob(executionJob.id);
    setExecutionJob(queued);
    setActionStatus(`Retrying ${queued.id}, attempt ${queued.attempt}...`);
    const executed = await runPipelineJob(queued.id);
    if (executed.job) setExecutionJob(await getJob(executed.job.id));
    setRefreshKey((key) => key + 1);
  }

  async function addFirstNode(nodeType = quickAddType) {
    // The only way to place the first node was an HTML5 drag, which does not
    // fire from touch input. Measured on a 390x844 viewport: palette and canvas
    // both visible, and neither a tap nor a touch-drag produced a node. The
    // `+` control that inserts a node exists per *edge*, so an empty canvas --
    // which is what "New pipeline" gives you -- had none.
    if (!selectedGraphId) return;
    const nextCanvas = await createPipelineNode(selectedGraphId, nodeType, { x: 120, y: 80 });
    setCanvas(nextCanvas);
    setSelectedNodeId(nextCanvas.selected_node?.id || "");
    setActionStatus(`Added ${nodeType} at drop location. Layout is saved.`);
    setRefreshKey((key) => key + 1);
  }

  async function insertAfter(nodeType = quickAddType) {
    const nodeId = selectedNodeId || canvas?.nodes[0]?.id;
    if (!selectedGraphId || !nodeId) return;
    const nextCanvas = await insertPipelineNode(selectedGraphId, nodeId, nodeType);
    setCanvas(nextCanvas);
    setSelectedNodeId(nextCanvas.selected_node?.id || nodeId);
    setActionStatus(`Inserted ${nodeType} after ${nodeId}. Preview the selected node below.`);
    setRefreshKey((key) => key + 1);
  }

  async function addNodeAtDrop(position: { x: number; y: number }, nodeType: string) {
    if (!selectedGraphId) return;
    setActionStatus(`Adding ${nodeType} at ${Math.round(position.x)}, ${Math.round(position.y)}...`);
    const nextCanvas = await createPipelineNode(selectedGraphId, nodeType, position, selectedNodeId || undefined);
    setCanvas(nextCanvas);
    setSelectedNodeId(nextCanvas.selected_node?.id || selectedNodeId);
    setActionStatus(`Added ${nodeType} at drop location. Layout is saved.`);
    setRefreshKey((key) => key + 1);
  }

  /** Click selects one node; Shift-click adds or removes one from the selection. */
  function selectNode(nodeId: string, extend = false) {
    setSelectedNodeId(nodeId);
    setSelection((current) => {
      if (!extend) return [nodeId];
      const base = current.length ? current : selectedNodeId ? [selectedNodeId] : [];
      return base.includes(nodeId) ? base.filter((id) => id !== nodeId) : [...base, nodeId];
    });
  }

  /**
   * Moves one node or several by the same stage-pixel delta, and commits once.
   *
   * One layout request and one undo entry however many nodes moved, because the
   * move is one act: taking it back one node at a time would be three Undos for
   * one drag, the defect V4 of GOAL_MOVEMENT removed from the artifact canvases.
   */
  function moveNodes(nodeIds: string[], delta: { x: number; y: number }) {
    if (!selectedGraphId || !canvas) return;
    const moving = new Set(nodeIds);
    const placed = (node: { id: string; position: { x: number; y: number } }) => moving.has(node.id)
      ? { x: Math.max(0, node.position.x + delta.x), y: Math.max(0, node.position.y + delta.y) }
      : node.position;
    setCanvas((current) => current && {
      ...current,
      nodes: current.nodes.map((node) => ({ ...node, position: placed(node) })),
      selected_node: current.selected_node ? { ...current.selected_node, position: placed(current.selected_node) } : current.selected_node
    });
    const previous = Object.fromEntries(canvas.nodes.map((node) => [node.id, node.position]));
    const label = nodeIds.length === 1 ? nodeIds[0] : `${nodeIds.length} nodes`;
    setMoves((current) => [...current, { graphId: selectedGraphId, nodeId: label, positions: previous }]);
    const positions = Object.fromEntries(canvas.nodes.map((node) => [node.id, placed(node)]));
    setActionStatus(`Saving ${label} position...`);
    void savePipelineLayout(selectedGraphId, positions)
      .then((nextCanvas) => {
        setCanvas(nextCanvas);
        setActionStatus(nodeIds.length === 1 ? `Saved ${label} position.` : `Saved positions of ${label}.`);
        setRefreshKey((key) => key + 1);
      })
      .catch((error: Error) => setActionStatus(`Could not save layout: ${error.message}`));
  }

  /** One Undo, one committed move: the positions before it are saved back. */
  async function undoMove() {
    const last = moves[moves.length - 1];
    if (!last || !canvas || last.graphId !== selectedGraphId) return;
    setMoves((current) => current.slice(0, -1));
    // A node deleted since the move has no position to restore.
    const present = new Set(canvas.nodes.map((node) => node.id));
    const positions = Object.fromEntries(Object.entries(last.positions).filter(([id]) => present.has(id)));
    setActionStatus(`Moving ${last.nodeId} back...`);
    try {
      setCanvas(await savePipelineLayout(last.graphId, positions));
      setActionStatus(`Moved ${last.nodeId} back.`);
      setRefreshKey((key) => key + 1);
    } catch (error) {
      setActionStatus(`Could not move ${last.nodeId} back: ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  async function removeNode(nodeId = selectedNodeId) {
    if (!selectedGraphId || !nodeId) return;
    setActionStatus(`Deleting ${nodeId}...`);
    const nextCanvas = await deletePipelineNode(selectedGraphId, nodeId);
    setCanvas(nextCanvas);
    setSelectedNodeId(nextCanvas.selected_node?.id || "");
    setActionStatus(`Deleted ${nodeId}. Incident edges were removed and simple paths were reconnected.`);
    setRefreshKey((key) => key + 1);
  }

  function endCanvasDrag(event: DragEndEvent) {
    const id = String(event.active.id);
    if (id.startsWith("node:")) {
      // A node already on the canvas: commit once, where it came to rest.
      const node = canvas?.nodes.find((item) => item.id === id.slice(5));
      if (!node || (!event.delta.x && !event.delta.y)) return;
      // A node inside a multi-node selection carries the whole selection; any
      // other node moves alone, whatever else happens to be selected.
      const carried = selection.length > 1 && selection.includes(node.id) ? selection : [node.id];
      moveNodes(carried, { x: event.delta.x / zoom, y: event.delta.y / zoom });
      return;
    }
    if (event.over?.id !== "pipeline-canvas") return;
    const point = dropPointOf(event);
    const container = canvasRef.current;
    if (!point || !container) return;
    const rect = container.getBoundingClientRect();
    void addNodeAtDrop({
      x: Math.max(0, (point.x - rect.left + container.scrollLeft) / zoom - 86),
      y: Math.max(0, (point.y - rect.top + container.scrollTop) / zoom - 28)
    }, id.replace("palette:", ""));
  }

  const outputRows = asRows((outputs?.outputs || canvas?.outputs)?.nodes);
  const buildRows = asRows((outputs?.outputs || canvas?.outputs)?.builds);
  const prospectiveContract = details?.metadata.ontology_contract as PipelineOntologyContract | null | undefined;
  const latestContract = contracts?.sections.latest.find((contract) => contract.node_id === selectedNodeId);

  async function createGraph() {
    setActionStatus("Creating pipeline draft...");
    const graph = await postJson<{ id: string }>("/pipeline-builder/graphs", {
      display_name: "Untitled pipeline",
      description: "Visual pipeline draft",
      nodes: [],
      edges: [],
      parameters: {},
      status: "DRAFT"
    });
    setSelectedGraphId(graph.id);
    setSelectedNodeId("");
    setActionStatus("Pipeline draft created. Drag an input or transform onto the canvas.");
    setRefreshKey((key) => key + 1);
  }

  return (
    <section className="workbench-page pipeline-workbench-page">
      <div className="builder-shell">
        <section className="builder-main">
          <PipelineHeader
            title={canvas?.graph.display_name || "Pipeline graph"}
            actions={<>
              <button onClick={createGraph}>New pipeline</button>
              {/* No `Save layout` here. Every drop already saves node positions to the
                  graph, so that button re-sent what was stored -- and it sat beside the
                  panes' reset, one noun naming the artifact everyone shares and a
                  preference in this browser. V8 of GOAL_MOVEMENT_2026-09-12. */}
              <button onClick={() => void undoMove()} disabled={!moves.length}>Undo move</button>
              <button onClick={() => removeNode()} disabled={!selectedNodeId}>Delete node</button>
              <button onClick={() => run("validate")} disabled={!selectedGraphId || Boolean(busyAction)}>Propose</button>
              <button onClick={() => run("preview")} disabled={!selectedGraphId || Boolean(busyAction)}>Preview</button>
              <button onClick={() => run("deliver")} disabled={!selectedGraphId || Boolean(busyAction)}>{busyAction === "deliver" ? "Queueing..." : "Deploy"}</button>
              <a className="legacy-button compact" href="/workspace/pipeline?legacy=1">Legacy</a>
            </>}
          />
          <Toolbar groups={canvas?.toolbar_groups || state.value?.selected_canvas?.toolbar_groups || []} />
          <div className="workbench-status-strip">
            <StatusBadge value={canvas?.validation.status || "loading"} />
            <span>{actionStatus}</span>
          </div>
          <DndContext sensors={sensors} collisionDetection={slotAwareCollision} onDragStart={(event) => {
            const id = String(event.active.id);
            if (id.startsWith("node:")) setSelectedNodeId(id.slice(5));
          }} onDragEnd={(event) => {
            // A pane move stops here; anything else belongs to the canvas.
            if (paneState.handleDragEnd(event)) return;
            endCanvasDrag(event);
          }}>
          <PaneHost state={paneState} render={(pane) => {
            if (pane === "library") return (<div className="node-library">
              <p>Drag a node onto the canvas, click a node type to set the edge insert action, or use the selected-node menu.</p>
              {(state.value?.node_library || []).map((item) => (
                <PaletteEntry
                  key={item.type}
                  type={item.type}
                  label={item.label}
                  category={item.category}
                  selected={quickAddType === item.type}
                  onArm={() => setQuickAddType(item.type)}
                />
              ))}
            </div>);
            if (pane === "canvas") return (
                <div className="pipeline-body">
            <PipelineCanvas
              canvas={canvas}
              zoom={zoom}
              onZoom={(next) => setZoom(Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, next)))}
              selectedNodeId={selectedNodeId}
              selection={selection}
              details={details}
              onSelect={selectNode}
              containerRef={canvasRef}
              onInsertEdge={() => insertAfter(quickAddType)}
              onAddFirst={() => addFirstNode(quickAddType)}
              quickAddType={quickAddType}
              onContextInsert={(nodeType) => insertAfter(nodeType)}
              onDeleteNode={removeNode}
            />
                </div>
            );
            if (pane === "drawer") return (
          <BottomDrawer
            preview={preview}
            selectedNode={canvas?.selected_node || null}
            suggestions={suggestions}
            validation={canvas?.validation}
            details={details}
          />
            );
            if (pane === "output") return (<div className="output-rail">
          <Panel title="Execution Policy">
            <div className="pipeline-execution-policy">
              <label>
                <span>Engine</span>
                <select value={executionEngine} onChange={(event) => setExecutionEngine(event.target.value as "builder" | "duckdb")}>
                  <option value="builder">Builder runtime</option>
                  <option value="duckdb">Snapshot runtime (DuckDB)</option>
                </select>
              </label>
              <label>
                <span>Delivery strategy</span>
                <select
                  value={executionStrategy}
                  disabled={executionEngine !== "duckdb"}
                  onChange={(event) => setExecutionStrategy(event.target.value as PipelineExecutionStrategy)}
                >
                  <option value="auto">Auto</option>
                  <option value="single">Single worker</option>
                  <option value="partitioned">Partition workers</option>
                </select>
              </label>
              <label>
                <span>Maximum partitions</span>
                <input
                  type="number"
                  min={2}
                  max={100}
                  value={maxPartitions}
                  disabled={executionEngine !== "duckdb" || executionStrategy === "single"}
                  onChange={(event) => setMaxPartitions(Math.max(2, Math.min(100, Number(event.target.value) || 2)))}
                />
              </label>
              <p>
                Auto distributes row-local plans over immutable files and falls back safely when a transform needs global state.
                Preview always uses one worker.
              </p>
            </div>
          </Panel>
          <Panel title="Execution">
            {executionJob ? <div className="pipeline-execution-state" aria-live="polite">
              <div className="pipeline-execution-heading"><StatusBadge value={executionJob.status} /><strong>{executionJob.job_type}</strong></div>
              <progress max={100} value={executionJob.progress} aria-label={`Execution progress ${executionJob.progress}%`} />
              <KeyValueGrid data={{
                job_id: executionJob.id,
                progress: `${executionJob.progress}%`,
                attempt: executionJob.attempt,
                strategy: executionJob.execution_strategy || (executionPlan ? "single" : "builder"),
                plan: executionPlan?.id || "Builder graph",
                error: executionJob.error || "None"
              }} />
              {executionJob.strategy_fallback?.reasons?.length ? (
                <div className="inline-warning" role="status">
                  Auto selected one worker: {executionJob.strategy_fallback.reasons.join(" ")}
                </div>
              ) : null}
              {executionJob.dependencies?.length ? (
                <details open>
                  <summary>Partition jobs ({executionJob.dependencies.length})</summary>
                  <DataTable rows={executionJob.dependencies.map((dependency, index) => ({
                    partition: index + 1,
                    job: dependency.id,
                    type: dependency.job_type,
                    status: dependency.status
                  }))} />
                </details>
              ) : null}
              <div className="action-row">
                <button onClick={cancelExecution} disabled={!["BLOCKED", "QUEUED", "RUNNING"].includes(executionJob.status)}>Cancel</button>
                <button onClick={retryExecution} disabled={!["FAILED", "CANCELLED"].includes(executionJob.status)}>Retry</button>
              </div>
              {executionJob.events?.length ? <details><summary>Execution events</summary><DataTable rows={executionJob.events.map((event) => ({ event: event.event_type, status: event.status, created_at: event.created_at }))} /></details> : null}
            </div> : <EmptyState inline>Preview or deploy to create durable execution evidence.</EmptyState>}
          </Panel>
          <Panel title="Selected Node">
            {details ? <>
              <KeyValueGrid data={{
                id: details.node_id,
                type: details.metadata.type,
                upstream: formatValue(details.metadata.upstream),
                downstream: formatValue(details.metadata.downstream),
                preview_rows: details.preview.row_count,
              }} />
              <PipelineNodeConfig
                details={details}
                draft={nodeDrafts[`${selectedGraphId}/${details.node_id}`]}
                onDraft={(draft) => setNodeDrafts((current) => {
                  const key = `${selectedGraphId}/${details.node_id}`;
                  const next = { ...current };
                  if (draft) next[key] = draft;
                  else delete next[key];
                  return next;
                })}
                onSave={async (label, config) => {
                  if (!selectedGraphId) return;
                  setActionStatus(`Saving ${details.node_id} configuration...`);
                  const next = await updatePipelineNode(selectedGraphId, details.node_id, label, config);
                  setDetails(next);
                  setActionStatus(`${details.node_id} configuration saved and preview refreshed.`);
                  setRefreshKey((key) => key + 1);
                }}
              />
              <details className="pipeline-lineage-details">
                <summary>Field lineage</summary>
                <DataTable rows={asRows(details.metadata.field_lineage)} empty="No propagated fields are available yet." />
              </details>
              {details.node.type === "ontology_output" ? (
                <OntologyContractPanel contract={prospectiveContract || latestContract || null} mode={prospectiveContract ? "preview" : "latest run"} />
              ) : null}
            </> : <EmptyState inline>Select a node to inspect lineage, config, and preview details.</EmptyState>}
          </Panel>
          <Panel title="Ontology Contracts" action={<StatusBadge value={contracts?.summary.status || "NOT_RUN"} />}>
            {contracts?.sections.latest.length ? (
              <div className="ontology-contract-list">
                {contracts.sections.latest.map((contract) => (
                  <button key={contract.id || contract.node_id} className="ontology-contract-row" onClick={() => setSelectedNodeId(contract.node_id)}>
                    <span><strong>{contract.object_type_id}</strong><small>{contract.node_id}</small></span>
                    <span><StatusBadge value={contract.status} /></span>
                    <small className="contract-row-counts">{contract.accepted_rows.toLocaleString()} accepted / {contract.rejected_rows.toLocaleString()} rejected</small>
                  </button>
                ))}
              </div>
            ) : <EmptyState inline>Deploy an ontology output to record reconciliation and quarantine evidence.</EmptyState>}
          </Panel>
          <Panel title="Pipeline Outputs" action={<button onClick={() => insertAfter("dataset_output")}>Add</button>}>
            <input className="compact-input" placeholder="Search outputs..." />
            <div className="cards tight">
              {outputRows.map((node) => (
                <article key={asString(node.id)} className="resource-card">
                  <strong>{formatValue(node.label || node.id)}</strong>
                  <StatusBadge value={node.status as string} />
                </article>
              ))}
              {buildRows.map((build) => (
                <article key={asString(build.id)} className="resource-card">
                  <strong>{formatValue(build.output_asset_id || build.id)}</strong>
                  <span>{formatValue(build.row_count)} rows</span>
                </article>
              ))}
            </div>
          </Panel>
          <Panel title="Output Settings">
            <KeyValueGrid data={{
              target_ontology: (outputs?.outputs || canvas?.outputs)?.target_ontology || "local",
              output_folder: (outputs?.outputs || canvas?.outputs)?.output_folder || "No location selected",
              mapped_columns: (outputs?.outputs || canvas?.outputs)?.mapped_columns || "-",
              validation: outputs?.validation.status || canvas?.validation?.status || "UNKNOWN"
            }} />
          </Panel>
          <Panel title="Graphs">
            {(state.value?.graphs || []).map((graph) => (
              <button key={graph.id} className={classNames("resource-row", selectedGraphId === graph.id && "selected")} onClick={() => setSelectedGraphId(graph.id)}>
                <strong>{graph.display_name || graph.id}</strong>
                <span>{graph.nodes.length} nodes</span>
              </button>
            ))}
          </Panel>
            </div>);
            return null;
          }} />
          </DndContext>
        </section>
      </div>
    </section>
  );
}

function OntologyContractPanel({ contract, mode }: { contract: PipelineOntologyContract | null; mode: string }) {
  // Memoized, and above the early return so the hooks run in the same order on every
  // render. The builder polls a running job every 1.5 s and re-renders this panel each
  // time without changing the contract; a new array on every tick would withdraw the
  // grid's status sentence while a person was reading it.
  const issues = useMemo(() => (contract?.violations ?? []).flatMap((violation) => violation.errors.map((error) => ({
    row: violation.row_index + 1,
    object: violation.object_id || "Not resolved",
    field: error.field,
    issue: error.message
  }))), [contract]);
  if (!contract) return <EmptyState inline>Configure the ontology output to preview its data contract.</EmptyState>;
  const lineage = contract.field_lineage.map((field) => ({
    source: field.source_field,
    ontology_property: field.target_property,
    origin: field.origins.map((origin) => [origin.asset_id, origin.field].filter(Boolean).join(".") || origin.operation || origin.node_id).filter(Boolean).join(" -> ")
  }));
  return (
    <section className="ontology-contract-panel" aria-label="Ontology output contract">
      <div className="pipeline-config-heading">
        <strong>Ontology contract</strong>
        <span className="contract-mode">{mode}</span>
        <StatusBadge value={contract.status} />
      </div>
      <KeyValueGrid data={{
        object_type: contract.object_type_id,
        accepted: contract.accepted_rows,
        rejected: contract.rejected_rows,
        created: contract.created_objects,
        updated: contract.updated_objects,
        unchanged: contract.unchanged_objects
      }} />
      {/* N9 of GOAL_HONEST_UI_2026-09-11. The table was handed the first twenty-five
          issues under a summary counting all of them, so the rest were named and could
          not be read. DataTable pages what it is given. The contract itself carries at
          most 100 violations, so when more rows were rejected than arrived, that is
          said as well: paging through 100 would be the same silence one layer down. */}
      {issues.length ? (
        <details open>
          <summary>{issues.length} contract issue{issues.length === 1 ? "" : "s"}</summary>
          {contract.rejected_rows > contract.violations.length ? <p className="table-truncated" role="note">Listing the issues of the first {contract.violations.length.toLocaleString()} of {contract.rejected_rows.toLocaleString()} rejected rows</p> : null}
          {/* N7d: a grid, so issues can be sorted by field or by row. Keyed by the contract,
              so a sort made on one output's contract does not carry into another's. When the
              contract kept fewer rows than were rejected, a sort ranks only the rows it kept,
              and the grid says so beside the sort. */}
          <DataGrid
            key={`${mode}:${contract.node_id}:${contract.id ?? ""}`}
            rows={issues}
            label="Contract issues"
            sortScope={contract.rejected_rows > contract.violations.length
              ? `the issues of the first ${contract.violations.length.toLocaleString()} of ${contract.rejected_rows.toLocaleString()} rejected rows`
              : undefined}
          />
        </details>
      ) : <p className="contract-success">All preview rows satisfy the ontology contract.</p>}
      {lineage.length ? <details><summary>Mapped field lineage ({lineage.length})</summary><DataTable rows={lineage} /></details> : null}
      {contract.quarantine_asset_id ? <a className="evidence-link" href={`/workspace/imports?asset=${encodeURIComponent(contract.quarantine_asset_id)}`}>Open quarantine dataset</a> : null}
    </section>
  );
}

interface ConfigFieldDefinition {
  name: string;
  label: string;
  type: string;
  required?: boolean;
  options?: string[];
  minimum?: number;
  maximum?: number;
}

type NodeDraft = { label: string; values: Record<string, string> };

function PipelineNodeConfig({ details, draft, onDraft, onSave }: {
  details: PipelineNodeDetails;
  /** What was typed and not saved, kept by the caller so a remount does not lose it. */
  draft?: NodeDraft;
  onDraft: (draft: NodeDraft | null) => void;
  onSave: (label: string, config: JsonObject) => Promise<void>;
}) {
  const schema = details.metadata.configuration_schema as { fields?: ConfigFieldDefinition[] } | undefined;
  const fields = schema?.fields || [];
  const sourceConfig = (details.metadata.config || {}) as JsonObject;
  const [label, setLabel] = useState(draft?.label ?? details.node.label);
  const [values, setValues] = useState<Record<string, string>>(draft?.values ?? {});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    // A draft for this node wins over what the server holds: it is what the person
    // typed, and the server's copy is what they were changing.
    if (draft) {
      setLabel(draft.label);
      setValues(draft.values);
    } else {
      setLabel(details.node.label);
      setValues(Object.fromEntries(fields.map((field) => [field.name, displayConfigValue(sourceConfig[field.name], field.type)])));
    }
    setError("");
  }, [details.node_id, details.node.label, JSON.stringify(sourceConfig)]);

  function changeLabel(next: string) {
    setLabel(next);
    onDraft({ label: next, values });
  }

  function changeValue(name: string, value: string) {
    const next = { ...values, [name]: value };
    setValues(next);
    onDraft({ label, values: next });
  }

  async function save() {
    setSaving(true);
    setError("");
    try {
      const config: JsonObject = {};
      for (const field of fields) {
        const raw = values[field.name] || "";
        if (!raw && !field.required) continue;
        config[field.name] = parseConfigValue(raw, field.type);
      }
      await onSave(label, config);
      onDraft(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="pipeline-node-config" onSubmit={(event) => { event.preventDefault(); void save(); }}>
      <div className="pipeline-config-heading"><strong>Transform configuration</strong><StatusBadge value={asString((details.metadata.configuration_validation as JsonObject | undefined)?.status || "READY")} /></div>
      <label>Node label<input value={label} onChange={(event) => changeLabel(event.target.value)} required /></label>
      {fields.map((field) => (
        <label key={field.name}>
          {field.label}{field.required ? " *" : ""}
          {field.type === "select" ? (
            <select value={values[field.name] || ""} required={field.required} onChange={(event) => changeValue(field.name, event.target.value)}>
              <option value="">Choose...</option>
              {(field.options || []).map((option) => <option value={option} key={option}>{option.replace(/_/g, " ")}</option>)}
            </select>
          ) : field.type === "textarea" || field.type === "key_value" ? (
            <textarea rows={field.type === "key_value" ? 4 : 3} value={values[field.name] || ""} required={field.required} placeholder={field.type === "key_value" ? "source: target, one per line" : undefined} onChange={(event) => changeValue(field.name, event.target.value)} />
          ) : (
            <input
              type={["integer", "number"].includes(field.type) ? "number" : "text"}
              min={field.minimum}
              max={field.maximum}
              value={values[field.name] || ""}
              required={field.required}
              placeholder={field.type === "field_list" ? "field_a, field_b" : field.type === "field" ? "Choose or enter a field" : undefined}
              onChange={(event) => changeValue(field.name, event.target.value)}
            />
          )}
        </label>
      ))}
      {error ? <div className="inline-form-error" role="alert">{error}</div> : null}
      <button className="primary-action" type="submit" disabled={saving}>{saving ? "Saving..." : "Save configuration"}</button>
    </form>
  );
}

function displayConfigValue(value: unknown, type: string): string {
  if (value == null) return "";
  if (type === "field_list" && Array.isArray(value)) return value.join(", ");
  if (type === "key_value" && typeof value === "object" && !Array.isArray(value)) return Object.entries(value as JsonObject).map(([key, item]) => `${key}: ${String(item)}`).join("\n");
  return String(value);
}

function parseConfigValue(value: string, type: string): string | number | boolean | string[] | JsonObject {
  if (type === "integer") return Number.parseInt(value, 10);
  if (type === "number") return Number.parseFloat(value);
  if (type === "field_list") return value.split(",").map((item) => item.trim()).filter(Boolean);
  if (type === "key_value") return Object.fromEntries(value.split(/\r?\n|,/).map((item) => item.trim()).filter(Boolean).map((item) => {
    const [key, ...rest] = item.split(":");
    return [key.trim(), rest.join(":").trim()];
  }));
  if (type === "scalar") {
    if (value === "true" || value === "false") return value === "true";
    const number = Number(value);
    return value.trim() !== "" && Number.isFinite(number) ? number : value;
  }
  return value;
}


/**
 * A node type in the palette: a button that arms it, and a drag that places it.
 *
 * Arming is what a touch user does — tap the type, then tap `Add` on the empty
 * canvas or the insert control on an edge. The drag is how a mouse user chooses
 * the position in one gesture, and the 8px activation distance in
 * `useWorkspaceSensors` is what keeps the two from eating each other.
 */
function PaletteEntry({ type, label, category, selected, onArm }: {
  type: string;
  label: string;
  category: string;
  selected: boolean;
  onArm: () => void;
}) {
  const draggable = useDraggable({ id: `palette:${type}` });
  return (
    <button
      ref={draggable.setNodeRef}
      onClick={onArm}
      className={classNames(selected && "selected", draggable.isDragging && "dragging")}
      style={draggable.isDragging ? { opacity: 0.5 } : undefined}
      {...draggable.attributes}
      {...draggable.listeners}
    >
      <strong>{label}</strong>
      <span>{category}</span>
    </button>
  );
}
