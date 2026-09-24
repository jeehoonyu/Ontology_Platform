import { ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { DndContext, useDraggable, type DragEndEvent } from "@dnd-kit/core";
import { dropPointOf, slotAwareCollision, useWorkspaceSensors } from "../components/dnd/DragKit";
import { PaneHost, usePaneLayout } from "../components/layout/Pane";
import { DataGrid } from "../components/data/DataGrid";
import type { PaneSpec } from "../lib/paneLayout";
import { columnLayout, layersOf } from "../lib/graphLayout";
import { CLIPBOARD_KIND, readNodes, writeNodes } from "../lib/nodeClipboard";
import { bare, ctrl, ctrlShift, useHotkeys, type Hotkey } from "../lib/hotkeys";
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
  applyPipelineCommands,
  type PipelineCommand,
  suggestPipelineNode,
  updatePipelineNode
} from "../api/workspaceState";
import { BottomDrawer, LASSO_ID, PipelineCanvas, ZOOM_FIT, ZOOM_MAX, ZOOM_MIN } from "../components/canvas/PipelineCanvas";
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
  const [canvasFailed, setCanvasFailed] = useState(false);
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
  // X5 of GOAL_GRAPH_2026-09-23 widened it to what else one Undo can take back: a
  // paste, whose nodes it removes in one request.
  const [moves, setMoves] = useState<HistoryEntry[]>([]);
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
    setCanvasFailed(false);
    getPipelineCanvas(selectedGraphId, selectedNodeId || undefined)
      .then((nextCanvas) => {
        if (!cancelled) {
          setCanvas(nextCanvas);
          setSelectedNodeId(nextCanvas.selected_node?.id || selectedNodeId);
        }
      })
      .catch(() => {
        if (cancelled) return;
        setCanvas(null);
        setCanvasFailed(true);
      });
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
  // Nodes hidden from this view, per pipeline, in this browser: a viewing preference
  // like a pane layout, never sent to the server. X6 of GOAL_GRAPH_2026-09-23.
  const [hiddenIds, setHiddenIds] = useState<string[]>([]);
  useEffect(() => { setHiddenIds(readHidden(selectedGraphId)); }, [selectedGraphId]);
  const hiddenSet = useMemo(() => new Set(hiddenIds), [hiddenIds]);
  const shownNodes = useMemo(() => (canvas?.nodes || []).filter((node) => !hiddenSet.has(node.id)),
                             [canvas, hiddenSet]);

  // The nodes every tool acts on: the set, or the node last clicked when the set is
  // empty. GOAL_GRAPH_2026-09-23: selection is one set, and every tool takes it. A
  // hidden node is not on the canvas, so no tool takes it.
  const targets = useMemo(() => {
    const present = new Set(shownNodes.map((node) => node.id));
    const chosen = selection.length ? selection : selectedNodeId ? [selectedNodeId] : [];
    return chosen.filter((id) => present.has(id));
  }, [shownNodes, selection, selectedNodeId]);

  /**
   * The nodes a selection rectangle closed over. With Shift held when it began they
   * join the selection, as a Shift+click does; without, they replace it.
   */
  function selectRegion(nodeIds: string[], additive: boolean) {
    setSelection((current) => {
      if (!additive) return nodeIds;
      const base = current.length ? current : selectedNodeId ? [selectedNodeId] : [];
      return Array.from(new Set([...base, ...nodeIds]));
    });
  }

  /** Every node on the canvas. Writes the set only, so nothing is fetched. */
  function selectAll() {
    setSelection(shownNodes.map((node) => node.id));
  }

  /** Hides what is selected from this view; the graph on the server is untouched. */
  function hideSelection() {
    if (!targets.length) return;
    const next = Array.from(new Set([...hiddenIds, ...targets]));
    setHiddenIds(next);
    writeHidden(selectedGraphId, next);
    setSelection([]);
    setActionStatus(`Hid ${targets.length === 1 ? "1 node" : `${targets.length} nodes`} in this browser. `
      + "The pipeline itself is unchanged.");
  }

  function showAllHidden() {
    setHiddenIds([]);
    writeHidden(selectedGraphId, []);
    setActionStatus("Showing every node.");
  }

  /**
   * Adds the selected nodes' parents or children, one edge away, so pressing it
   * again walks further. The original's Ctrl+E and Ctrl+D. Writes the set only.
   */
  function selectAlongEdges(direction: "parents" | "children") {
    const from = new Set(targets);
    const reached = (canvas?.edges || [])
      .filter((edge) => from.has(direction === "parents" ? edge.target : edge.source))
      .map((edge) => (direction === "parents" ? edge.source : edge.target))
      .filter((id) => !hiddenSet.has(id));
    setSelection(Array.from(new Set([...targets, ...reached])));
  }

  // Search pipeline: matches by name, id or type are selected, and the first is
  // scrolled into view. It writes the set, so a tool used after a search acts on
  // what it found. The original's Ctrl+F.
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchText, setSearchText] = useState("");
  const searchBox = useRef<HTMLInputElement | null>(null);
  const [hotkeysOpen, setHotkeysOpen] = useState(false);
  const hotkeysButton = useRef<HTMLButtonElement | null>(null);
  const hotkeysClose = useRef<HTMLButtonElement | null>(null);
  useEffect(() => {
    if (searchOpen) searchBox.current?.focus();
  }, [searchOpen]);
  // The reference takes the focus when it opens, so Escape reaches it and a screen
  // reader lands in it, and gives it back to the button that opened it.
  useEffect(() => {
    if (hotkeysOpen) hotkeysClose.current?.focus();
  }, [hotkeysOpen]);

  function openSearch() {
    setSearchOpen(true);
    searchBox.current?.focus();
    searchBox.current?.select();
  }

  function matching(text: string) {
    const needle = text.trim().toLowerCase();
    if (!needle || !canvas) return [];
    return shownNodes.filter((node) =>
      [node.label, node.id, node.type].some((value) => String(value || "").toLowerCase().includes(needle)));
  }

  function searchNodes(text: string) {
    setSearchText(text);
    const found = matching(text);
    if (!text.trim()) return;
    setSelection(found.map((node) => node.id));
    const first = found[0];
    if (first) {
      canvasRef.current?.querySelector(`[data-node-id="${CSS.escape(first.id)}"]`)
        ?.scrollIntoView({ block: "nearest", inline: "nearest" });
    }
  }

  function showHotkeys() {
    setHotkeysOpen(true);
  }

  function closeHotkeys() {
    setHotkeysOpen(false);
    hotkeysButton.current?.focus();
  }

  // Every key the canvas answers to, in one table. The listener is driven by it and
  // `View hotkeys` renders it, so the reference cannot disagree with the wiring, and
  // every row names the button that does the same thing. X4 of GOAL_GRAPH_2026-09-23.
  const hotkeys: Hotkey[] = [
    { keys: "Ctrl+A", label: "Select all", button: "Select all", matches: ctrl("a"), run: selectAll },
    { keys: "Ctrl+E", label: "Select parents", button: "Select parents", matches: ctrl("e"),
      run: () => selectAlongEdges("parents") },
    { keys: "Ctrl+D", label: "Select children", button: "Select children", matches: ctrl("d"),
      run: () => selectAlongEdges("children") },
    { keys: "Ctrl+F", label: "Search pipeline", button: "Search pipeline", matches: ctrl("f"), run: openSearch },
    // Up Arrow is also how a keyboard drag moves a node up. While a drag is live the
    // hotkeys stand down (`dragging` below), and a test proves the zoom stays put.
    { keys: "Up Arrow", label: "Fit to view", button: "Fit to view", matches: bare("ArrowUp"),
      run: () => setZoom(ZOOM_FIT) },
    // With text selected on the page, Ctrl+C copies the text, as it always did.
    { keys: "Ctrl+C", label: "Copy", button: "Copy",
      matches: (event) => ctrl("c")(event) && !window.getSelection()?.toString(), run: () => void copySelection() },
    { keys: "Ctrl+V", label: "Paste", button: "Paste", matches: ctrl("v"), run: () => void pasteNodes() },
    { keys: "Delete", label: "Delete selected", button: "Delete selected", matches: bare("Delete"),
      run: () => void deleteSelected() },
    { keys: "Ctrl+H", label: "Hide selected", button: "Hide selected", matches: ctrl("h"), run: hideSelection },
    // Not the original's Ctrl+K: that is this product's command palette on every screen.
    { keys: "Ctrl+Shift+H", label: "Show all", button: "Show all", matches: ctrlShift("h"), run: showAllHidden },
  ];
  // Whether a drag is live on this screen: its keys are the drag's while it is.
  const dragging = useRef(false);
  useHotkeys(hotkeys, ".pipeline-body", Boolean(canvas), () => dragging.current);

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
    if (!canvas) return;
    const moving = new Set(nodeIds);
    const label = nodeIds.length === 1 ? nodeIds[0] : `${nodeIds.length} nodes`;
    commitPositions(
      Object.fromEntries(canvas.nodes.filter((node) => moving.has(node.id)).map((node) => [node.id, {
        x: Math.max(0, node.position.x + delta.x), y: Math.max(0, node.position.y + delta.y)
      }])),
      label,
      nodeIds.length === 1 ? `Saved ${label} position.` : `Saved positions of ${label}.`
    );
  }

  /**
   * Puts nodes where `next` says, and commits once: one layout request, and one
   * history entry holding every position before, so one `Undo move` takes the whole
   * change back however many nodes it touched. Node moves and `Auto layout` both
   * come through here.
   */
  function commitPositions(next: Record<string, { x: number; y: number }>, label: string, done: string) {
    if (!selectedGraphId || !canvas) return;
    const placed = (node: { id: string; position: { x: number; y: number } }) => next[node.id] || node.position;
    setCanvas((current) => current && {
      ...current,
      nodes: current.nodes.map((node) => ({ ...node, position: placed(node) })),
      selected_node: current.selected_node ? { ...current.selected_node, position: placed(current.selected_node) } : current.selected_node
    });
    const previous = Object.fromEntries(canvas.nodes.map((node) => [node.id, node.position]));
    setMoves((current) => [...current, { kind: "move", graphId: selectedGraphId, label, positions: previous }]);
    const positions = Object.fromEntries(canvas.nodes.map((node) => [node.id, placed(node)]));
    setActionStatus(`Saving ${label} position...`);
    void savePipelineLayout(selectedGraphId, positions)
      .then((nextCanvas) => {
        setCanvas(nextCanvas);
        setActionStatus(done);
        setRefreshKey((key) => key + 1);
      })
      .catch((error: Error) => setActionStatus(`Could not save layout: ${error.message}`));
  }

  /**
   * Lays the pipeline out left to right, a column per layer: a node nothing flows
   * into on the left, and every edge pointing to a later column. Inside a column the
   * nodes keep the order top to bottom a person had already given them. One commit,
   * so one `Undo move` puts every node back. X3 of GOAL_GRAPH_2026-09-23.
   */
  function autoLayout() {
    if (!canvas?.nodes.length) return;
    const layer = layersOf(canvas.nodes.map((node) => node.id), canvas.edges);
    const depth = (id: string) => layer.get(id) ?? 0;
    const ordered = [...canvas.nodes].sort((a, b) =>
      depth(a.id) - depth(b.id) || a.position.y - b.position.y || a.position.x - b.position.x);
    const placed = columnLayout(ordered, (node) => node.id, (node) => depth(node.id),
                                { x: 260, y: 110, originX: 40, originY: 60 });
    const moved = canvas.nodes.filter((node) => {
      const to = placed.get(node.id);
      return to && (to.x !== node.position.x || to.y !== node.position.y);
    });
    if (!moved.length) {
      setActionStatus("The pipeline is already laid out; nothing moved.");
      return;
    }
    const label = `${canvas.nodes.length} nodes`;
    commitPositions(Object.fromEntries(placed), label, `Laid out ${label}.`);
  }

  /**
   * One Undo, one committed change. A move saves the positions before it back; a
   * paste removes the nodes it added, and their edges, in one request.
   */
  async function undoLast() {
    const last = moves[moves.length - 1];
    if (!last || !canvas || last.graphId !== selectedGraphId) return;
    setMoves((current) => current.slice(0, -1));
    // A node deleted since has no position to restore and nothing to remove.
    const present = new Set(canvas.nodes.map((node) => node.id));
    if (last.kind === "connect") {
      setActionStatus(`Taking back the edge ${last.label}...`);
      try {
        setCanvas(await applyPipelineCommands(last.graphId, [{ op: "delete_edge", source: last.source, target: last.target }]));
        setActionStatus(`Took back the edge ${last.label}.`);
      } catch (error) {
        setActionStatus(`Could not take back the edge: ${error instanceof Error ? error.message : String(error)}`);
      }
      return;
    }
    if (last.kind === "paste") {
      const pasted = last.nodeIds.filter((id) => present.has(id));
      setActionStatus(`Taking back the paste of ${last.label}...`);
      try {
        if (pasted.length) {
          setCanvas(await applyPipelineCommands(last.graphId, pasted.map((id) => ({ op: "delete_node" as const, node_id: id }))));
        }
        setSelection((current) => current.filter((id) => !pasted.includes(id)));
        setActionStatus(`Took back the paste of ${last.label}.`);
      } catch (error) {
        setActionStatus(`Could not take back the paste: ${error instanceof Error ? error.message : String(error)}`);
      }
      return;
    }
    const positions = Object.fromEntries(Object.entries(last.positions).filter(([id]) => present.has(id)));
    setActionStatus(`Moving ${last.label} back...`);
    try {
      setCanvas(await savePipelineLayout(last.graphId, positions));
      setActionStatus(`Moved ${last.label} back.`);
      setRefreshKey((key) => key + 1);
    } catch (error) {
      setActionStatus(`Could not move ${last.label} back: ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  const count = (n: number) => (n === 1 ? "1 node" : `${n} nodes`);

  /**
   * One edge from `source` to `target`, by one command, which one Undo takes back.
   * X7 of GOAL_GRAPH_2026-09-23. The edge control on an edge inserts a new node and
   * connects nothing already there, so this is the batch's `add_edge`, not that path.
   */
  async function connectNodes(source: string, target: string) {
    if (!selectedGraphId || !canvas) return;
    if (source === target) {
      setActionStatus("A node cannot feed itself.");
      return;
    }
    if (canvas.edges.some((edge) => edge.source === source && edge.target === target)) {
      setActionStatus(`${source} already feeds ${target}.`);
      return;
    }
    setActionStatus(`Connecting ${source} to ${target}...`);
    try {
      setCanvas(await applyPipelineCommands(selectedGraphId, [{ op: "add_edge", source, target }]));
      setMoves((current) => [...current, { kind: "connect", graphId: selectedGraphId, label: `${source} to ${target}`, source, target }]);
      setActionStatus(`Connected ${source} to ${target}.`);
    } catch (error) {
      setActionStatus(`Could not connect: ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  /**
   * The selected nodes and the edges between them, to the clipboard. X5 of
   * GOAL_GRAPH_2026-09-23. A text selection on the page is the browser's to copy.
   */
  async function copySelection() {
    if (!canvas || !targets.length) return;
    const chosen = new Set(targets);
    const nodes = canvas.nodes.filter((node) => chosen.has(node.id)).map((node) => ({
      id: node.id, type: node.type, label: node.label, config: node.config || {}, position: node.position,
    }));
    const edges = canvas.edges.filter((edge) => chosen.has(edge.source) && chosen.has(edge.target))
      .map((edge) => ({ source: edge.source, target: edge.target }));
    const where = await writeNodes({ kind: CLIPBOARD_KIND, version: 1, nodes, edges });
    setActionStatus(`Copied ${count(nodes.length)}${edges.length ? ` and ${edges.length === 1 ? "1 edge" : `${edges.length} edges`}` : ""}.`
      + (where === "tab" ? " The system clipboard refused it, so it pastes in this tab only." : ""));
  }

  /**
   * What was copied, into this pipeline: one batch that adds the nodes and the edges
   * between them, 40px down and right of where they were, with the pasted nodes
   * selected. One Undo takes the whole paste back. The batch is the one request a
   * paste sends; nothing is re-fetched after it, because the batch returns the canvas.
   */
  async function pasteNodes() {
    if (!selectedGraphId || !canvas) return;
    const read = await readNodes();
    if (!read?.copied.nodes.length) {
      setActionStatus("Nothing to paste: copy nodes first.");
      return;
    }
    const { copied } = read;
    const commands: PipelineCommand[] = [
      ...copied.nodes.map((node) => ({
        op: "add_node" as const, ref: node.id, node_type: node.type, label: node.label, config: node.config,
        position: { x: node.position.x + 40, y: node.position.y + 40 },
      })),
      ...copied.edges.map((edge) => ({ op: "add_edge" as const, source: edge.source, target: edge.target })),
    ];
    const label = count(copied.nodes.length);
    setActionStatus(`Pasting ${label}...`);
    try {
      const result = await applyPipelineCommands(selectedGraphId, commands);
      setCanvas(result);
      const pasted = Object.values(result.created);
      setSelection(pasted);
      setMoves((current) => [...current, { kind: "paste", graphId: selectedGraphId, label, nodeIds: pasted }]);
      setActionStatus(`Pasted ${label}.` + (read.from === "tab" ? " Read from this tab's copy; the system clipboard could not be read." : ""));
    } catch (error) {
      setActionStatus(`Could not paste: ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  /**
   * Every selected node, and its edges, in one request. Unlike `Delete node`, it does
   * not join the neighbours of a deleted node: with more than one node going, which
   * neighbours would join is not a question with one answer.
   */
  async function deleteSelected() {
    if (!selectedGraphId || !targets.length) return;
    const doomed = [...targets];
    const label = count(doomed.length);
    setActionStatus(`Deleting ${label}...`);
    try {
      const result = await applyPipelineCommands(selectedGraphId, doomed.map((id) => ({ op: "delete_node" as const, node_id: id })));
      setCanvas(result);
      setSelection([]);
      if (doomed.includes(selectedNodeId)) setSelectedNodeId(result.selected_node?.id || "");
      setActionStatus(`Deleted ${label}. Their edges went with them.`);
    } catch (error) {
      setActionStatus(`Could not delete: ${error instanceof Error ? error.message : String(error)}`);
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
    // The canvas selected what the rectangle closed over. It must not reach the
    // palette drop below, which would read "lasso:canvas" as a node type to create.
    if (id === LASSO_ID) return;
    // A port drag connects, or, dropped anywhere but an input port, does nothing.
    if (id.startsWith("port-out:")) {
      const over = String(event.over?.id ?? "");
      if (over.startsWith("port-in:")) void connectNodes(id.slice(9), over.slice(8));
      return;
    }
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

  // Node configurations typed and not saved, on this pipeline. X8 of GOAL_GRAPH: the
  // original shows a filled Saved state and lists unsaved work; positions save on drop
  // here, so what can be unsaved is a node's configuration. A draft is dropped when
  // what is typed is back to what is saved, so a count here is a real difference.
  const unsavedNodes = (canvas?.nodes || []).filter((node) => nodeDrafts[`${selectedGraphId}/${node.id}`]);
  const [unsavedOpen, setUnsavedOpen] = useState(false);

  // S5 of GOAL_SHELL_2026-09-23. The badge read `canvas?.validation.status ||
  // "loading"`, so it said loading with no pipeline selected and after a canvas
  // had failed to load, when nothing was loading. It says loading only while the
  // page or a canvas is on its way.
  const pageLoading = !state.value && !state.error;
  const stripStatus = canvas ? canvas.validation.status
    : pageLoading ? "loading"
    : state.error ? "Pipelines failed to load"
    : !selectedGraphId ? "No pipeline selected"
    : canvasFailed ? "Canvas failed to load"
    : "loading";

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
              {/* Named for what it takes back: a move or a paste. X5 of GOAL_GRAPH. */}
              <button onClick={() => void undoLast()} disabled={!moves.length}>
                Undo {moves[moves.length - 1]?.kind ?? "move"}
              </button>
              <button onClick={() => removeNode()} disabled={!selectedNodeId}>Delete node</button>
              <button onClick={() => run("validate")} disabled={!selectedGraphId || Boolean(busyAction)}>Propose</button>
              <button onClick={() => run("preview")} disabled={!selectedGraphId || Boolean(busyAction)}>Preview</button>
              <button onClick={() => run("deliver")} disabled={!selectedGraphId || Boolean(busyAction)}>{busyAction === "deliver" ? "Queueing..." : "Deploy"}</button>
              <a className="legacy-button compact" href="/workspace/pipeline?legacy=1">Legacy</a>
            </>}
          />
          <Toolbar groups={canvas?.toolbar_groups || state.value?.selected_canvas?.toolbar_groups || []} />
          <div className="workbench-status-strip">
            <StatusBadge value={stripStatus} />
            {unsavedNodes.length ? (
              <button type="button" className="unsaved-changes" aria-expanded={unsavedOpen}
                      onClick={() => setUnsavedOpen((open) => !open)}>
                {unsavedNodes.length === 1 ? "1 unsaved change" : `${unsavedNodes.length} unsaved changes`}
              </button>
            ) : canvas ? <span className="saved-state">Saved</span> : null}
            <span className="strip-message">{actionStatus}</span>
            {unsavedOpen && unsavedNodes.length ? (
              <ul className="unsaved-list" aria-label="Unsaved changes">
                {unsavedNodes.map((node) => (
                  <li key={node.id}>
                    <button type="button" onClick={() => selectNode(node.id)}>
                      {node.label} ({node.id}): configuration not saved
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
          <DndContext sensors={sensors} collisionDetection={slotAwareCollision} onDragStart={(event) => {
            dragging.current = true;
            const id = String(event.active.id);
            if (id.startsWith("node:")) setSelectedNodeId(id.slice(5));
          }} onDragCancel={() => {
            dragging.current = false;
          }} onDragEnd={(event) => {
            dragging.current = false;
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
            <div className="canvas-tools">
              <span className="canvas-selection-count">
                {targets.length} of {canvas?.nodes.length ?? 0} selected
              </span>
              <button type="button" onClick={selectAll} disabled={!canvas?.nodes.length}>Select all</button>
              <button type="button" onClick={() => selectAlongEdges("parents")} disabled={!targets.length}>
                Select parents
              </button>
              <button type="button" onClick={() => selectAlongEdges("children")} disabled={!targets.length}>
                Select children
              </button>
              <button type="button" onClick={() => void copySelection()} disabled={!targets.length}>Copy</button>
              <button type="button" onClick={() => void pasteNodes()} disabled={!canvas}>Paste</button>
              <button type="button" onClick={() => void deleteSelected()} disabled={!targets.length}>Delete selected</button>
              {/* Connect without dragging a port: the first node selected feeds the second. */}
              <button type="button" onClick={() => void connectNodes(selection[0], selection[1])}
                      disabled={selection.length !== 2 || targets.length !== 2}>Connect</button>
              <button type="button" onClick={hideSelection} disabled={!targets.length}>Hide selected</button>
              <button type="button" onClick={autoLayout} disabled={!canvas?.nodes.length}>Auto layout</button>
              <button type="button" onClick={openSearch} disabled={!canvas?.nodes.length}>Search pipeline</button>
              <button type="button" ref={hotkeysButton} onClick={showHotkeys}>View hotkeys</button>
            </div>
            {searchOpen ? (
              <div className="canvas-search">
                <input
                  ref={searchBox}
                  aria-label="Find in pipeline"
                  placeholder="Name, id or type"
                  value={searchText}
                  onChange={(event) => searchNodes(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key !== "Escape") return;
                    event.preventDefault();
                    event.stopPropagation();
                    setSearchOpen(false);
                  }}
                />
                <span className="canvas-search-count">
                  {searchText.trim()
                    ? `${matching(searchText).length} of ${canvas?.nodes.length ?? 0} match`
                    : "Type to select what matches"}
                </span>
                <button type="button" onClick={() => setSearchOpen(false)}>Close search</button>
              </div>
            ) : null}
            {hotkeysOpen ? (
              <section
                role="dialog"
                aria-label="Hotkeys"
                className="hotkeys-reference"
                onKeyDown={(event) => {
                  if (event.key !== "Escape") return;
                  event.preventDefault();
                  event.stopPropagation();
                  closeHotkeys();
                }}
              >
                <header>
                  <strong>Hotkeys</strong>
                  <button type="button" ref={hotkeysClose} onClick={closeHotkeys}>Close</button>
                </header>
                <table>
                  <thead><tr><th>Keys</th><th>Does</th><th>Button</th></tr></thead>
                  <tbody>
                    {hotkeys.map((hotkey) => (
                      <tr key={hotkey.keys}>
                        <td><kbd>{hotkey.keys}</kbd></td><td>{hotkey.label}</td><td>{hotkey.button}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </section>
            ) : null}
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
              onLasso={selectRegion}
              hiddenNodes={hiddenSet}
              onShowAll={showAllHidden}
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
                rows: details.preview.row_count,
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
                    {/* The names may be cut behind an ellipsis in a narrow pane; the counts below may not. */}
                    <span><strong title={contract.object_type_id}>{contract.object_type_id}</strong><small title={contract.node_id}>{contract.node_id}</small></span>
                    <span><StatusBadge value={contract.status} /></span>
                    <small className="contract-row-counts">{contract.accepted_rows.toLocaleString()} accepted / {contract.rejected_rows.toLocaleString()} rejected</small>
                  </button>
                ))}
              </div>
            ) : <EmptyState inline>Deploy an ontology output to record reconciliation and quarantine evidence.</EmptyState>}
          </Panel>
          <Panel title="Pipeline Outputs" action={<button onClick={() => insertAfter("dataset_output")}>Add</button>}>
            {/* No search box. It had no state and no handler, so it searched nothing and lost
                its text whenever this pane moved; and what this lists is the graph's output
                nodes and the five builds the canvas loads, so a search here would read as a
                search of every build. V12 of GOAL_MOVEMENT_2026-09-12. */}
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

const HIDDEN_PREFIX = "ontology.pipeline.hidden.";

/** The nodes hidden from one pipeline in this browser. A store that throws hides nothing. */
function readHidden(graphId: string): string[] {
  if (!graphId) return [];
  try {
    const stored = JSON.parse(window.localStorage.getItem(HIDDEN_PREFIX + graphId) || "[]");
    return Array.isArray(stored) ? stored.filter((id): id is string => typeof id === "string") : [];
  } catch {
    return [];
  }
}

function writeHidden(graphId: string, ids: string[]) {
  if (!graphId) return;
  try {
    if (ids.length) window.localStorage.setItem(HIDDEN_PREFIX + graphId, JSON.stringify(ids));
    else window.localStorage.removeItem(HIDDEN_PREFIX + graphId);
  } catch {
    /* not being able to remember what is hidden must not stop hiding it */
  }
}

/** What one Undo takes back: a committed move of any number of nodes, a paste, or an edge. */
type HistoryEntry =
  | { kind: "move"; graphId: string; label: string; positions: Record<string, { x: number; y: number }> }
  | { kind: "paste"; graphId: string; label: string; nodeIds: string[] }
  | { kind: "connect"; graphId: string; label: string; source: string; target: string };

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

  // What the server holds, in the form's own terms, so a draft typed back to it is no
  // draft. X8 of GOAL_GRAPH: the strip counts drafts as unsaved changes, and a field
  // changed and changed back is not a change.
  const saved = { label: details.node.label,
                  values: Object.fromEntries(fields.map((field) => [field.name, displayConfigValue(sourceConfig[field.name], field.type)])) };
  const differs = (nextLabel: string, nextValues: Record<string, string>) => nextLabel !== saved.label
    || fields.some((field) => (nextValues[field.name] ?? "") !== (saved.values[field.name] ?? ""));

  function changeLabel(next: string) {
    setLabel(next);
    onDraft(differs(next, values) ? { label: next, values } : null);
  }

  function changeValue(name: string, value: string) {
    const next = { ...values, [name]: value };
    setValues(next);
    onDraft(differs(label, next) ? { label, values: next } : null);
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
