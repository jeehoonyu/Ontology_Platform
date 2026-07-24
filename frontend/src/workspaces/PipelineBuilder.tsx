import { useEffect, useState, type DragEvent } from "react";
import { postJson } from "../api";
import { cancelJob, enqueuePipelineJob, getJob, retryJob, runPipelineJob } from "../api/jobApi";
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
import { BottomDrawer, PipelineCanvas } from "../components/canvas/PipelineCanvas";
import { DataTable, KeyValueGrid, Panel, StatusBadge } from "../components/data/DataDisplay";
import { Toolbar, WorkspaceHeader } from "../components/workbench/Workbench";
import { useAsyncState } from "../hooks/useAsyncState";
import { asRows, asString, classNames, formatValue } from "../utils/format";
import type {
  NodePreview,
  NodeSuggestions,
  JsonObject,
  PipelineCanvasState,
  PipelineNodeDetails,
  PipelineOutputsState,
  PipelineUiState,
  PlatformJob
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
  const [executionJob, setExecutionJob] = useState<PlatformJob | null>(null);
  const [busyAction, setBusyAction] = useState("");
  const [actionStatus, setActionStatus] = useState("Select a node, insert transforms from edges or the node menu, then preview or deploy.");
  const state = useAsyncState<PipelineUiState>(getPipelineState, [refreshKey]);

  useEffect(() => {
    if (!executionJob || !["QUEUED", "RUNNING"].includes(executionJob.status)) return;
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
        const queued = await enqueuePipelineJob(selectedGraphId, action, `${action}-${selectedGraphId}-${Date.now()}`);
        setExecutionJob(queued);
        setActionStatus(`${action} queued as ${queued.id}. Waiting for worker claim...`);
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

  async function insertAfter(nodeType = quickAddType) {
    const nodeId = selectedNodeId || canvas?.nodes[0]?.id;
    if (!selectedGraphId || !nodeId) return;
    const nextCanvas = await insertPipelineNode(selectedGraphId, nodeId, nodeType);
    setCanvas(nextCanvas);
    setSelectedNodeId(nextCanvas.selected_node?.id || nodeId);
    setActionStatus(`Inserted ${nodeType} after ${nodeId}. Preview the selected node below.`);
    setRefreshKey((key) => key + 1);
  }

  async function addNodeAtDrop(event: DragEvent<HTMLDivElement>, nodeType: string) {
    if (!selectedGraphId) return;
    const container = event.currentTarget;
    const rect = container.getBoundingClientRect();
    const position = {
      x: Math.max(0, (event.clientX - rect.left + container.scrollLeft) / zoom - 86),
      y: Math.max(0, (event.clientY - rect.top + container.scrollTop) / zoom - 28)
    };
    setActionStatus(`Adding ${nodeType} at ${Math.round(position.x)}, ${Math.round(position.y)}...`);
    const nextCanvas = await createPipelineNode(selectedGraphId, nodeType, position, selectedNodeId || undefined);
    setCanvas(nextCanvas);
    setSelectedNodeId(nextCanvas.selected_node?.id || selectedNodeId);
    setActionStatus(`Added ${nodeType} at drop location. Layout is saved.`);
    setRefreshKey((key) => key + 1);
  }

  function moveNode(nodeId: string, position: { x: number; y: number }, commit: boolean) {
    setCanvas((current) => {
      if (!current) return current;
      const nodes = current.nodes.map((node) => node.id === nodeId ? { ...node, position } : node);
      return {
        ...current,
        nodes,
        selected_node: current.selected_node?.id === nodeId ? { ...current.selected_node, position } : current.selected_node
      };
    });
    if (commit && selectedGraphId && canvas) {
      const positions = Object.fromEntries(canvas.nodes.map((node) => [
        node.id,
        node.id === nodeId ? position : node.position
      ]));
      setActionStatus(`Saving ${nodeId} position...`);
      void savePipelineLayout(selectedGraphId, positions)
        .then((nextCanvas) => {
          setCanvas(nextCanvas);
          setActionStatus(`Saved ${nodeId} position.`);
          setRefreshKey((key) => key + 1);
        })
        .catch((error: Error) => setActionStatus(`Could not save layout: ${error.message}`));
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

  async function saveLayout() {
    if (!selectedGraphId || !canvas) return;
    const positions = Object.fromEntries(canvas.nodes.map((node) => [node.id, node.position]));
    setCanvas(await savePipelineLayout(selectedGraphId, positions));
    setActionStatus("Layout saved for this graph.");
  }

  function handleNodeDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    const nodeType = event.dataTransfer.getData("application/x-node-type");
    if (nodeType) void addNodeAtDrop(event, nodeType);
  }

  const outputRows = asRows((outputs?.outputs || canvas?.outputs)?.nodes);
  const buildRows = asRows((outputs?.outputs || canvas?.outputs)?.builds);

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
          <WorkspaceHeader
            title={canvas?.graph.display_name || "Pipeline graph"}
            tabs={["Graph", "Proposals", "History"]}
            actions={<>
              <button onClick={createGraph}>New pipeline</button>
              <button onClick={() => setZoom((value) => Math.max(0.55, value - 0.08))}>-</button>
              <button onClick={() => setZoom(0.86)}>Fit</button>
              <button onClick={() => setZoom((value) => Math.min(1.35, value + 0.08))}>+</button>
              <button onClick={saveLayout}>Save layout</button>
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
              onMoveNode={moveNode}
              onDeleteNode={removeNode}
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
          <Panel title="Execution">
            {executionJob ? <div className="pipeline-execution-state" aria-live="polite">
              <div className="pipeline-execution-heading"><StatusBadge value={executionJob.status} /><strong>{executionJob.job_type}</strong></div>
              <progress max={100} value={executionJob.progress} aria-label={`Execution progress ${executionJob.progress}%`} />
              <KeyValueGrid data={{
                job_id: executionJob.id,
                progress: `${executionJob.progress}%`,
                attempt: executionJob.attempt,
                error: executionJob.error || "None"
              }} />
              <div className="action-row">
                <button onClick={cancelExecution} disabled={!["QUEUED", "RUNNING"].includes(executionJob.status)}>Cancel</button>
                <button onClick={retryExecution} disabled={!["FAILED", "CANCELLED"].includes(executionJob.status)}>Retry</button>
              </div>
              {executionJob.events?.length ? <details><summary>Execution events</summary><DataTable rows={executionJob.events.map((event) => ({ event: event.event_type, status: event.status, created_at: event.created_at }))} /></details> : null}
            </div> : <div className="empty">Preview or deploy to create durable execution evidence.</div>}
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
            </> : <div className="empty">Select a node to inspect lineage, config, and preview details.</div>}
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

interface ConfigFieldDefinition {
  name: string;
  label: string;
  type: string;
  required?: boolean;
  options?: string[];
  minimum?: number;
  maximum?: number;
}

function PipelineNodeConfig({ details, onSave }: { details: PipelineNodeDetails; onSave: (label: string, config: JsonObject) => Promise<void> }) {
  const schema = details.metadata.configuration_schema as { fields?: ConfigFieldDefinition[] } | undefined;
  const fields = schema?.fields || [];
  const sourceConfig = (details.metadata.config || {}) as JsonObject;
  const [label, setLabel] = useState(details.node.label);
  const [values, setValues] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setLabel(details.node.label);
    setValues(Object.fromEntries(fields.map((field) => [field.name, displayConfigValue(sourceConfig[field.name], field.type)])));
    setError("");
  }, [details.node_id, details.node.label, JSON.stringify(sourceConfig)]);

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
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="pipeline-node-config" onSubmit={(event) => { event.preventDefault(); void save(); }}>
      <div className="pipeline-config-heading"><strong>Transform configuration</strong><StatusBadge value={asString((details.metadata.configuration_validation as JsonObject | undefined)?.status || "READY")} /></div>
      <label>Node label<input value={label} onChange={(event) => setLabel(event.target.value)} required /></label>
      {fields.map((field) => (
        <label key={field.name}>
          {field.label}{field.required ? " *" : ""}
          {field.type === "select" ? (
            <select value={values[field.name] || ""} required={field.required} onChange={(event) => setValues((current) => ({ ...current, [field.name]: event.target.value }))}>
              <option value="">Choose...</option>
              {(field.options || []).map((option) => <option value={option} key={option}>{option.replace(/_/g, " ")}</option>)}
            </select>
          ) : field.type === "textarea" || field.type === "key_value" ? (
            <textarea rows={field.type === "key_value" ? 4 : 3} value={values[field.name] || ""} required={field.required} placeholder={field.type === "key_value" ? "source: target, one per line" : undefined} onChange={(event) => setValues((current) => ({ ...current, [field.name]: event.target.value }))} />
          ) : (
            <input
              type={["integer", "number"].includes(field.type) ? "number" : "text"}
              min={field.minimum}
              max={field.maximum}
              value={values[field.name] || ""}
              required={field.required}
              placeholder={field.type === "field_list" ? "field_a, field_b" : field.type === "field" ? "Choose or enter a field" : undefined}
              onChange={(event) => setValues((current) => ({ ...current, [field.name]: event.target.value }))}
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
