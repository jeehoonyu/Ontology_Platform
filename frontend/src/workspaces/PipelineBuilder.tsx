import { useEffect, useState, type DragEvent } from "react";
import { postJson } from "../api";
import {
  getPipelineCanvas,
  getPipelineNodeDetails,
  getPipelineOutputs,
  getPipelineState,
  insertPipelineNode,
  previewPipelineNode,
  savePipelineLayout,
  suggestPipelineNode
} from "../api/workspaceState";
import { BottomDrawer, PipelineCanvas } from "../components/canvas/PipelineCanvas";
import { KeyValueGrid, Panel, StatusBadge } from "../components/data/DataDisplay";
import { Toolbar, WorkspaceHeader } from "../components/workbench/Workbench";
import { useAsyncState } from "../hooks/useAsyncState";
import { asRows, asString, classNames, formatValue } from "../utils/format";
import type {
  NodePreview,
  NodeSuggestions,
  PipelineCanvasState,
  PipelineNodeDetails,
  PipelineOutputsState,
  PipelineUiState
} from "../types";

export function PipelineBuilder() {
  const [refreshKey, setRefreshKey] = useState(0);
  const [selectedGraphId, setSelectedGraphId] = useState("");
  const [selectedNodeId, setSelectedNodeId] = useState("");
  const [canvas, setCanvas] = useState<PipelineCanvasState | null>(null);
  const [preview, setPreview] = useState<NodePreview | null>(null);
  const [suggestions, setSuggestions] = useState<NodeSuggestions | null>(null);
  const [details, setDetails] = useState<PipelineNodeDetails | null>(null);
  const [outputs, setOutputs] = useState<PipelineOutputsState | null>(null);
  const [zoom, setZoom] = useState(0.86);
  const [quickAddType, setQuickAddType] = useState("filter");
  const [actionStatus, setActionStatus] = useState("Select a node, insert transforms from edges or the node menu, then preview or deploy.");
  const state = useAsyncState<PipelineUiState>(getPipelineState, [refreshKey]);

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
    setActionStatus(`${action === "deliver" ? "Deploying" : action === "validate" ? "Checking proposal" : "Preparing preview"}...`);
    const result = await postJson(`/pipeline-builder/graphs/${encodeURIComponent(selectedGraphId)}/${action}`, { actor: "react" });
    setActionStatus(`${action} completed: ${formatValue((result as { status?: unknown }).status || "ok")}`);
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

  async function saveLayout() {
    if (!selectedGraphId || !canvas) return;
    const positions = Object.fromEntries(canvas.nodes.map((node) => [node.id, node.position]));
    setCanvas(await savePipelineLayout(selectedGraphId, positions));
    setActionStatus("Layout saved for this graph.");
  }

  function handleNodeDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    const nodeType = event.dataTransfer.getData("application/x-node-type");
    if (nodeType) void insertAfter(nodeType);
  }

  const outputRows = asRows((outputs?.outputs || canvas?.outputs)?.nodes);
  const buildRows = asRows((outputs?.outputs || canvas?.outputs)?.builds);

  return (
    <section className="workbench-page pipeline-workbench-page">
      <div className="builder-shell">
        <section className="builder-main">
          <WorkspaceHeader
            title={canvas?.graph.display_name || "Pipeline graph"}
            tabs={["Graph", "Proposals", "History"]}
            actions={<>
              <button onClick={() => setZoom((value) => Math.max(0.55, value - 0.08))}>-</button>
              <button onClick={() => setZoom(0.86)}>Fit</button>
              <button onClick={() => setZoom((value) => Math.min(1.35, value + 0.08))}>+</button>
              <button onClick={saveLayout}>Saved</button>
              <button onClick={() => run("validate")}>Propose</button>
              <button onClick={() => run("deliver")}>Deploy</button>
              <a className="legacy-button compact" href="/workspace/pipeline?legacy=1">Legacy</a>
            </>}
          />
          <Toolbar groups={canvas?.toolbar_groups || state.value?.selected_canvas?.toolbar_groups || []} />
          <div className="workbench-status-strip">
            <StatusBadge value={canvas?.validation.status || "loading"} />
            <span>{actionStatus}</span>
          </div>
          <div className="pipeline-body">
            <aside className="node-library">
              <h2>Add data / transforms</h2>
              <p>Drag a node onto the canvas, click a node type to set the edge insert action, or use the selected-node menu.</p>
              {(state.value?.node_library || []).map((item) => (
                <button
                  key={item.type}
                  draggable
                  onDragStart={(event) => event.dataTransfer.setData("application/x-node-type", item.type)}
                  onClick={() => setQuickAddType(item.type)}
                  className={classNames(quickAddType === item.type && "selected")}
                >
                  <strong>{item.label}</strong>
                  <span>{item.category}</span>
                </button>
              ))}
            </aside>
            <PipelineCanvas
              canvas={canvas}
              zoom={zoom}
              selectedNodeId={selectedNodeId}
              details={details}
              onSelect={setSelectedNodeId}
              onDrop={handleNodeDrop}
              onDragOver={(event) => event.preventDefault()}
              onInsertEdge={() => insertAfter(quickAddType)}
              onContextInsert={(nodeType) => insertAfter(nodeType)}
            />
            <aside className="pipeline-utility-rail" aria-label="Pipeline utility rail">
              {["R", "S", "L", "B", "C", "D"].map((item) => <button key={item}>{item}</button>)}
            </aside>
          </div>
          <BottomDrawer
            preview={preview}
            selectedNode={canvas?.selected_node || null}
            suggestions={suggestions}
            validation={canvas?.validation}
            details={details}
          />
        </section>
        <aside className="output-rail">
          <Panel title="Selected Node">
            {details ? <KeyValueGrid data={{
              id: details.node_id,
              type: details.metadata.type,
              upstream: formatValue(details.metadata.upstream),
              downstream: formatValue(details.metadata.downstream),
              preview_rows: details.preview.row_count,
            }} /> : <div className="empty">Select a node to inspect lineage, config, and preview details.</div>}
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
        </aside>
      </div>
    </section>
  );
}
