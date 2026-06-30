import { useEffect, useMemo, useState, type DragEvent, type ReactNode } from "react";
import { api, postJson } from "./api";
import {
  getOntologyObjectType,
  getOntologyState,
  getOntologyWalkthrough,
  getPipelineCanvas,
  getPipelineState,
  getWorkflowState,
  indexObjectType,
  insertPipelineNode,
  previewPipelineNode,
  savePipelineLayout,
  suggestPipelineNode
} from "./api/workspaceState";
import type {
  CommandCenterSummary,
  JsonObject,
  NodePreview,
  NodeSuggestions,
  OntologyManagerState,
  OntologyUiState,
  OntologyWalkthrough,
  PipelineCanvasState,
  PipelineNode,
  PipelineUiState,
  TableRow,
  WorkflowState
} from "./types";

const CORE_VIEWS = new Set(["command-center", "imports", "ontology", "pipeline", "graph", "validation"]);

const NAV_ITEMS = [
  { id: "command-center", label: "Command Center", hint: "Guided asset reliability workflow" },
  { id: "imports", label: "Data Onboarding", hint: "Upload, map, transform, connect, replay" },
  { id: "ontology", label: "Ontology Manager", hint: "Generate and manage object types" },
  { id: "pipeline", label: "Pipeline Builder", hint: "Canvas, previews, outputs" },
  { id: "graph", label: "Platform Graph", hint: "Inspect relationships and evidence" },
  { id: "validation", label: "Validation", hint: "Trust, conformance, schema health" }
];

const LEGACY_ITEMS = ["aip", "map", "workshop", "object-explorer", "models", "decision", "ops", "investigations"];

interface ImportJob extends TableRow {
  id?: string;
  status?: string;
  target_dataset_id?: string;
  validation?: JsonObject;
  transformed_records?: TableRow[];
}

interface ImportJobsResponse {
  jobs?: ImportJob[];
}

interface DataAssetsResponseItem extends TableRow {
  id: string;
  display_name?: string;
}

interface GraphOverview {
  nodes?: TableRow[];
  edges?: TableRow[];
}

function currentView(): string {
  const match = window.location.pathname.match(/\/workspace\/([^/?#]+)/);
  const view = match?.[1] || "command-center";
  return CORE_VIEWS.has(view) ? view : "command-center";
}

function navigate(view: string) {
  window.history.pushState({}, "", `/workspace/${view}`);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

function classNames(...parts: Array<string | false | undefined>) {
  return parts.filter(Boolean).join(" ");
}

function asString(value: unknown, fallback = ""): string {
  if (typeof value === "string") return value;
  if (value === null || value === undefined) return fallback;
  return String(value);
}

function asRows(value: unknown): TableRow[] {
  return Array.isArray(value) ? value.filter((item): item is TableRow => item !== null && typeof item === "object" && !Array.isArray(item)) : [];
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function useAsyncState<T>(loader: () => Promise<T>, deps: unknown[] = []) {
  const [value, setValue] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    loader()
      .then((result) => {
        if (!cancelled) {
          setValue(result);
          setError("");
        }
      })
      .catch((err: Error) => !cancelled && setError(err.message))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, deps);
  return { value, error, loading, reload: async () => setValue(await loader()) };
}

export function App() {
  const [view, setView] = useState(currentView());
  useEffect(() => {
    const handler = () => setView(currentView());
    window.addEventListener("popstate", handler);
    return () => window.removeEventListener("popstate", handler);
  }, []);

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span>OA</span>
          <div>
            <strong>Ontology AIP</strong>
            <small>React evaluator shell</small>
          </div>
        </div>
        <nav>
          {NAV_ITEMS.map((item) => (
            <button key={item.id} className={classNames("nav-item", view === item.id && "active")} onClick={() => navigate(item.id)}>
              <strong>{item.label}</strong>
              <span>{item.hint}</span>
            </button>
          ))}
        </nav>
        <div className="legacy-links">
          <strong>Legacy during migration</strong>
          {LEGACY_ITEMS.map((item) => <a key={item} href={`/workspace/${item}?legacy=1`}>{item}</a>)}
        </div>
      </aside>
      <main className="workspace">
        {view === "command-center" && <CommandCenter />}
        {view === "imports" && <DataOnboarding />}
        {view === "ontology" && <OntologyManager />}
        {view === "pipeline" && <PipelineWorkspace />}
        {view === "graph" && <GraphWorkspace />}
        {view === "validation" && <ValidationWorkspace />}
      </main>
    </div>
  );
}

function CommandCenter() {
  const [refreshKey, setRefreshKey] = useState(0);
  const [lastRun, setLastRun] = useState<JsonObject | null>(null);
  const workflow = useAsyncState<WorkflowState>(getWorkflowState, [refreshKey]);
  const summary: CommandCenterSummary = workflow.value?.summary || {};
  const kpis = summary.kpis || {};
  const highRisk = summary.high_risk_assets || [];

  async function bootstrap() {
    setLastRun(await postJson<JsonObject>("/scenarios/asset-reliability/bootstrap", { actor: "react", run_pipelines: true, run_checks: true }));
    setRefreshKey((key) => key + 1);
  }

  async function triage() {
    setLastRun(await postJson<JsonObject>("/scenarios/asset-reliability/run-triage", { actor: "react" }));
    setRefreshKey((key) => key + 1);
  }

  async function exportReport() {
    const markdown = await api<string>("/scenarios/asset-reliability/report?format=markdown");
    const blob = new Blob([markdown], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "asset-reliability-report.md";
    link.click();
    URL.revokeObjectURL(url);
    setRefreshKey((key) => key + 1);
  }

  return (
    <Page title="Asset Reliability Command Center" subtitle="Guided path from data onboarding to governed operational action.">
      <section className="stepper">
        {(workflow.value?.steps || []).map((step, index) => (
          <button key={step.id} className={classNames(step.status === "complete" && "complete", step.status === "active" && "active")} onClick={() => {
            if (step.id === "bootstrap") void bootstrap();
            else if (step.id === "triage") void triage();
            else if (step.id === "report") void exportReport();
            else if (step.href?.startsWith("/workspace/")) navigate(step.href.replace("/workspace/", ""));
          }}>
            <span>{index + 1}</span>
            {step.label}
            <StatusBadge value={step.status} />
          </button>
        ))}
      </section>
      <div className="grid metrics">
        <Metric label="High risk assets" value={kpis.high_risk_assets ?? 0} />
        <Metric label="Open alerts" value={kpis.open_alerts ?? 0} />
        <Metric label="Failing checks" value={kpis.data_contract_status ?? "NOT_RUN"} />
        <Metric label="Open approvals" value={kpis.open_approvals ?? 0} />
      </div>
      <div className="two-col">
        <Panel title="High-Risk Assets" action={<button onClick={() => setRefreshKey((key) => key + 1)}>Refresh</button>}>
          <DataTable rows={highRisk.map((item) => ({
            id: item.object_id,
            name: asString(item.object?.name || item.object?.display_name || item.object?.id),
            risk: asString(item.risk?.band),
            score: item.risk?.score,
            explanation: item.risk?.explanation
          }))} />
        </Panel>
        <Panel title="Proof Trail">
          <ProofTrail workflow={workflow.value} />
        </Panel>
      </div>
      <DebugJson title="Latest Run Output" value={lastRun} />
      {workflow.error && <div className="notice">Bootstrap the sample scenario to populate the Command Center.</div>}
    </Page>
  );
}

function DataOnboarding() {
  const [csvContent, setCsvContent] = useState("asset_id,name,status,criticality,vibration_mm_s,temperature_f,longitude,latitude\nasset_react_1,React Pump,degraded,HIGH,0.42,194,-122.4012,37.7924\nasset_react_1,React Pump,degraded,HIGH,0.42,194,-122.4012,37.7924\n");
  const [job, setJob] = useState<ImportJob | null>(null);
  const [suggestions, setSuggestions] = useState<TableRow[]>([]);
  const [sourcePreview, setSourcePreview] = useState<TableRow[]>([]);
  const [streamReplay, setStreamReplay] = useState<JsonObject | null>(null);
  const jobs = useAsyncState<ImportJobsResponse>(() => api<ImportJobsResponse>("/imports/jobs"), [job?.id, streamReplay?.stream_id]);

  async function createCsvJob() {
    setJob(await postJson<ImportJob>("/imports/csv", {
      filename: "react-assets.csv",
      display_name: "React Asset Import",
      target_dataset_id: "react_asset_import_dataset",
      content: csvContent
    }));
  }

  async function suggestMapping() {
    const jobId = job?.id;
    if (!jobId) return;
    const response = await api<{ suggestions?: TableRow[] }>(`/imports/jobs/${encodeURIComponent(jobId)}/mapping-suggestions?template=asset`);
    setSuggestions(response.suggestions || []);
  }

  async function transformJob() {
    const jobId = job?.id;
    if (!jobId) return;
    const transformed = await postJson<{ job?: ImportJob }>(`/imports/jobs/${encodeURIComponent(jobId)}/apply-transforms`, {
      actor: "react",
      steps: [
        { op: "enum_cleanup", field: "status", mapping: { degraded: "DEGRADED", running: "RUNNING" } },
        { op: "enum_cleanup", field: "criticality", mapping: { high: "high", medium: "medium", low: "low" } },
        { op: "normalize_unit", source: "temperature_f", target: "temperature_c", from_unit: "fahrenheit", to_unit: "celsius" },
        { op: "derive_point", latitude_field: "latitude", longitude_field: "longitude", target: "geometry" },
        { op: "deduplicate", keys: ["asset_id"] }
      ]
    });
    if (transformed.job) setJob(transformed.job);
  }

  async function generateDraft() {
    const jobId = job?.id;
    if (!jobId) return;
    setJob(await postJson<ImportJob>(`/imports/jobs/${encodeURIComponent(jobId)}/generate-ontology-draft`, {
      actor: "react",
      object_type_id: "react_asset",
      display_name: "React Asset"
    }));
  }

  async function connectorPreview() {
    const source = await postJson<JsonObject>("/connections/sources", {
      id: "react_rest_source",
      display_name: "React REST Source",
      source_type: "rest",
      config: {
        base_url: "http://localhost:9000/mock-assets",
        sample_records: [{ asset_id: "asset_connector_1", name: "Connector Pump", status: "RUNNING", criticality: "medium" }]
      }
    }).catch(() => api<JsonObject>("/connections/sources/react_rest_source"));
    const sourceId = asString(source.id);
    const preview = await postJson<{ preview_rows?: TableRow[] }>(`/connections/sources/${encodeURIComponent(sourceId)}/preview`, { limit: 10 });
    setSourcePreview(preview.preview_rows || []);
    const importJob = await postJson<{ job?: ImportJob }>(`/connections/sources/${encodeURIComponent(sourceId)}/generate-import-job`, {
      id: "react_connector_import",
      display_name: "React Connector Import",
      target_dataset_id: "react_connector_dataset",
      template: "asset",
      actor: "react"
    }).catch(() => api<ImportJob>("/imports/jobs/react_connector_import"));
    setJob((importJob as { job?: ImportJob }).job || (importJob as ImportJob));
  }

  async function replayStream() {
    await postJson("/streams", {
      id: "react_sensor_stream",
      display_name: "React Sensor Stream",
      schema: { sample_records: [{ reading_id: "r1", asset_id: "asset_react_1", vibration_mm_s: 11.2, observed_at: "1782684300" }] }
    }).catch(() => api("/streams/react_sensor_stream"));
    setStreamReplay(await postJson<JsonObject>("/streams/react_sensor_stream/replay", {
      actor: "react",
      target_asset_id: "react_sensor_archive",
      archive_to_dataset: true,
      records: [
        { reading_id: "r1", asset_id: "asset_react_1", vibration_mm_s: 11.2, observed_at: "1782684300" },
        { reading_id: "r2", asset_id: "asset_react_1", vibration_mm_s: 12.1, observed_at: "1782684310" }
      ],
      timestamp_field: "observed_at"
    }));
  }

  return (
    <Page title="Data Onboarding" subtitle="Upload, map, transform, connect, and replay data before promotion.">
      <div className="two-col">
        <Panel title="CSV Import and Transform" action={<button onClick={createCsvJob}>Create Job</button>}>
          <textarea value={csvContent} onChange={(event) => setCsvContent(event.target.value)} />
          <div className="button-row">
            <button onClick={suggestMapping} disabled={!job?.id}>Suggest Mapping</button>
            <button onClick={transformJob} disabled={!job?.id}>Apply Transforms</button>
            <button onClick={generateDraft} disabled={!job?.id}>Generate Ontology Draft</button>
          </div>
          <ImportJobSummary job={job} />
        </Panel>
        <Panel title="Mapping Suggestions">
          <DataTable rows={suggestions} />
        </Panel>
      </div>
      <div className="two-col">
        <Panel title="Hybrid Connector Preview" action={<button onClick={connectorPreview}>Preview REST Source</button>}>
          <DataTable rows={sourcePreview} />
        </Panel>
        <Panel title="Stream Replay" action={<button onClick={replayStream}>Replay Sensor Stream</button>}>
          {streamReplay ? <KeyValueGrid data={streamReplay} /> : <div className="empty">Replay stream data into a local dataset.</div>}
        </Panel>
      </div>
      <Panel title="Recent Import Jobs">
        <DataTable rows={jobs.value?.jobs || []} />
      </Panel>
    </Page>
  );
}

function OntologyManager() {
  const [refreshKey, setRefreshKey] = useState(0);
  const [assetId, setAssetId] = useState("");
  const [selectedId, setSelectedId] = useState("");
  const [manager, setManager] = useState<OntologyManagerState | null>(null);
  const [walkthrough, setWalkthrough] = useState<OntologyWalkthrough | null>(null);
  const state = useAsyncState<OntologyUiState>(getOntologyState, [refreshKey]);
  const assets = useAsyncState<DataAssetsResponseItem[]>(() => api<DataAssetsResponseItem[]>("/data-assets"), [refreshKey]);
  const drafts = useAsyncState<TableRow[]>(() => api<TableRow[]>("/ontology-generator/drafts"), [refreshKey]);

  useEffect(() => {
    if (!selectedId && state.value?.selected_object_type?.object_type.id) {
      setSelectedId(state.value.selected_object_type.object_type.id);
    }
  }, [state.value, selectedId]);

  useEffect(() => {
    if (!selectedId) return;
    let cancelled = false;
    Promise.all([getOntologyObjectType(selectedId), getOntologyWalkthrough(selectedId)])
      .then(([nextManager, nextWalkthrough]) => {
        if (!cancelled) {
          setManager(nextManager);
          setWalkthrough(nextWalkthrough);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setManager(null);
          setWalkthrough(null);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [selectedId, refreshKey]);

  async function createDraft() {
    if (!assetId) return;
    const id = `${assetId}_react_draft`.replace(/[^a-zA-Z0-9_]/g, "_");
    const draft = await postJson<TableRow>("/ontology-generator/drafts", {
      id,
      asset_id: assetId,
      object_type_id: `${assetId}_object`.replace(/[^a-zA-Z0-9_]/g, "_"),
      include_actions: true,
      create_pipeline_graph: true
    });
    setSelectedId(asString(draft.object_type_id, selectedId));
    setRefreshKey((key) => key + 1);
  }

  async function applyDraft(id: string) {
    const result = await postJson<TableRow>(`/ontology-generator/drafts/${encodeURIComponent(id)}/apply`, {
      actor: "react",
      create_actions: true,
      create_pipeline_graph: true
    });
    const objectType = result.object_type;
    const appliedObjectTypeId = typeof objectType === "object" && objectType !== null && !Array.isArray(objectType)
      ? (objectType as JsonObject).id
      : undefined;
    setSelectedId(asString(result.object_type_id || appliedObjectTypeId, selectedId));
    setRefreshKey((key) => key + 1);
  }

  async function markIndexed() {
    if (!selectedId) return;
    setManager(await indexObjectType(selectedId));
    setRefreshKey((key) => key + 1);
  }

  return (
    <Page title="Ontology Manager" subtitle="Generate object types from datasets, then inspect their properties, links, actions, and lineage.">
      <div className="ontology-layout">
        <aside className="walkthrough-panel">
          <h2>{walkthrough?.title || "Build ontology workflow"}</h2>
          <p>Guided evidence from pipeline output into object type review.</p>
          <ol>
            {(walkthrough?.steps || []).map((step, index) => (
              <li key={step.id} className={classNames(step.status === "active" && "active", step.status === "complete" && "complete")}>
                <span>{index + 1}</span>
                <div>
                  <strong>{step.title}</strong>
                  <small>{step.resource}</small>
                </div>
              </li>
            ))}
          </ol>
        </aside>
        <aside className="resource-nav">
          <Panel title="Discover">
            {(state.value?.object_types || []).map((objectType) => (
              <button key={objectType.id} className={classNames("resource-row", selectedId === objectType.id && "selected")} onClick={() => setSelectedId(objectType.id)}>
                <strong>{objectType.display_name}</strong>
                <span>{objectType.property_count} properties</span>
              </button>
            ))}
          </Panel>
          <Panel title="Generate From Dataset" action={<button onClick={createDraft} disabled={!assetId}>Generate</button>}>
            <select value={assetId} onChange={(event) => setAssetId(event.target.value)}>
              <option value="">Choose dataset</option>
              {(assets.value || []).map((asset) => <option key={asset.id} value={asset.id}>{asset.display_name || asset.id}</option>)}
            </select>
          </Panel>
          <Panel title="Drafts">
            {(drafts.value || []).slice(0, 6).map((draft) => (
              <button key={asString(draft.id)} className="resource-row" onClick={() => applyDraft(asString(draft.id))}>
                <strong>{formatValue(draft.id)}</strong>
                <span>{formatValue(draft.status)}</span>
              </button>
            ))}
          </Panel>
        </aside>
        <section className="manager-surface">
          {manager ? (
            <>
              <div className="manager-header-card">
                <div>
                  <span className="object-icon">OT</span>
                  <h2>{manager.object_type.display_name}</h2>
                  <p>{manager.object_type.description || "No description"}</p>
                </div>
                <div className="button-row">
                  <button onClick={markIndexed}>Index</button>
                  <button onClick={() => navigate("pipeline")}>Open Pipeline</button>
                </div>
              </div>
              <div className="manager-nav">
                {manager.navigation.map((item) => <button key={item}>{item.replace(/_/g, " ")}</button>)}
              </div>
              <div className="manager-grid">
                <Panel title="Overview">
                  <KeyValueGrid data={{
                    plural_name: manager.object_type.plural_name,
                    api_name: manager.object_type.api_name,
                    point_of_contact: manager.object_type.point_of_contact,
                    ontology: manager.object_type.ontology,
                    rid: manager.object_type.rid
                  }} />
                </Panel>
                <Panel title="Status">
                  <KeyValueGrid data={{
                    status: manager.object_type.status,
                    visibility: manager.object_type.visibility,
                    index_status: manager.object_type.index_status,
                    edits: manager.object_type.edits
                  }} />
                </Panel>
                <Panel title={`Properties ${manager.cards.properties.count}`}>
                  <DataTable rows={manager.cards.properties.rows} />
                </Panel>
                <Panel title={`Action Types ${manager.cards.action_types.count}`}>
                  <DataTable rows={manager.cards.action_types.rows} />
                </Panel>
                <Panel title={`Link Types ${manager.cards.link_types.count}`}>
                  <RelationshipStrip rows={manager.cards.link_types.rows} fallback={manager.object_type.display_name} />
                </Panel>
                <Panel title={`Dependents ${manager.cards.dependents.count}`}>
                  <DataTable rows={manager.cards.dependents.rows} />
                </Panel>
              </div>
            </>
          ) : <div className="empty">Generate or select an object type to inspect manager details.</div>}
        </section>
      </div>
    </Page>
  );
}

function PipelineWorkspace() {
  const [refreshKey, setRefreshKey] = useState(0);
  const [selectedGraphId, setSelectedGraphId] = useState("");
  const [selectedNodeId, setSelectedNodeId] = useState("");
  const [canvas, setCanvas] = useState<PipelineCanvasState | null>(null);
  const [preview, setPreview] = useState<NodePreview | null>(null);
  const [suggestions, setSuggestions] = useState<NodeSuggestions | null>(null);
  const [zoom, setZoom] = useState(0.86);
  const [quickAddType, setQuickAddType] = useState("filter");
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
    if (!selectedGraphId || !selectedNodeId) return;
    let cancelled = false;
    Promise.all([
      previewPipelineNode(selectedGraphId, selectedNodeId).catch(() => null),
      suggestPipelineNode(selectedGraphId, selectedNodeId).catch(() => null)
    ]).then(([nextPreview, nextSuggestions]) => {
      if (!cancelled) {
        setPreview(nextPreview);
        setSuggestions(nextSuggestions);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [selectedGraphId, selectedNodeId, refreshKey]);

  async function run(action: "validate" | "preview" | "deliver") {
    if (!selectedGraphId) return;
    await postJson(`/pipeline-builder/graphs/${encodeURIComponent(selectedGraphId)}/${action}`, { actor: "react" });
    setRefreshKey((key) => key + 1);
  }

  async function insertAfter(nodeType = quickAddType) {
    const nodeId = selectedNodeId || canvas?.nodes[0]?.id;
    if (!selectedGraphId || !nodeId) return;
    const nextCanvas = await insertPipelineNode(selectedGraphId, nodeId, nodeType);
    setCanvas(nextCanvas);
    setSelectedNodeId(nextCanvas.selected_node?.id || nodeId);
    setRefreshKey((key) => key + 1);
  }

  async function saveLayout() {
    if (!selectedGraphId || !canvas) return;
    const positions = Object.fromEntries(canvas.nodes.map((node) => [node.id, node.position]));
    setCanvas(await savePipelineLayout(selectedGraphId, positions));
  }

  function handleNodeDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    const nodeType = event.dataTransfer.getData("application/x-node-type");
    if (nodeType) void insertAfter(nodeType);
  }

  return (
    <Page title="Pipeline Builder" subtitle="Canvas, node previews, suggestions, warnings, outputs, and deliver controls.">
      <div className="builder-shell">
        <section className="builder-main">
          <WorkspaceHeader
            title={canvas?.graph.display_name || "Pipeline graph"}
            tabs={["Graph", "Proposals", "History"]}
            actions={<>
              <button onClick={() => setZoom((value) => Math.max(0.55, value - 0.08))}>-</button>
              <button onClick={() => setZoom(0.86)}>Fit</button>
              <button onClick={() => setZoom((value) => Math.min(1.35, value + 0.08))}>+</button>
              <button onClick={saveLayout}>Save layout</button>
              <button onClick={() => run("validate")}>Propose</button>
              <button onClick={() => run("deliver")}>Deploy</button>
            </>}
          />
          <Toolbar groups={canvas?.toolbar_groups || state.value?.selected_canvas?.toolbar_groups || []} />
          <div className="pipeline-body">
            <aside className="node-library">
              <h2>Add data / transforms</h2>
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
              onSelect={setSelectedNodeId}
              onDrop={handleNodeDrop}
              onDragOver={(event) => event.preventDefault()}
              onInsertEdge={() => insertAfter(quickAddType)}
            />
          </div>
          <BottomDrawer preview={preview} selectedNode={canvas?.selected_node || null} suggestions={suggestions} validation={canvas?.validation} />
        </section>
        <aside className="output-rail">
          <Panel title="Pipeline Outputs" action={<button onClick={() => insertAfter("dataset_output")}>Add</button>}>
            <input className="compact-input" placeholder="Search outputs..." />
            <div className="cards tight">
              {asRows(canvas?.outputs?.nodes).map((node) => (
                <article key={asString(node.id)} className="resource-card">
                  <strong>{formatValue(node.label || node.id)}</strong>
                  <StatusBadge value={node.status as string} />
                </article>
              ))}
              {asRows(canvas?.outputs?.builds).map((build) => (
                <article key={asString(build.id)} className="resource-card">
                  <strong>{formatValue(build.output_asset_id || build.id)}</strong>
                  <span>{formatValue(build.row_count)} rows</span>
                </article>
              ))}
            </div>
          </Panel>
          <Panel title="Output Settings">
            <KeyValueGrid data={{
              target_ontology: canvas?.outputs?.target_ontology || "local",
              output_folder: canvas?.outputs?.output_folder || "No location selected",
              validation: canvas?.validation?.status || "UNKNOWN"
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
    </Page>
  );
}

function GraphWorkspace() {
  const graph = useAsyncState<GraphOverview>(() => api<GraphOverview>("/graph/overview"), []);
  return (
    <Page title="Platform Graph" subtitle="Searchable overview of datasets, pipelines, objects, incidents, and reports.">
      <Panel title="Graph Canvas">
        <MiniGraph nodes={graph.value?.nodes || []} edges={graph.value?.edges || []} />
      </Panel>
      <div className="two-col">
        <Panel title="Nodes"><DataTable rows={graph.value?.nodes || []} /></Panel>
        <Panel title="Edges"><DataTable rows={graph.value?.edges || []} /></Panel>
      </div>
    </Page>
  );
}

function ValidationWorkspace() {
  const [refreshKey, setRefreshKey] = useState(0);
  const project = useAsyncState<{ status?: string; summary?: JsonObject; sections?: JsonObject }>(() => api("/project/validate"), [refreshKey]);
  const matrix = useAsyncState<{ row_count?: number; rows?: TableRow[] }>(() => api("/scenarios/asset-reliability/validation-dashboard"), [refreshKey]);
  const summary = project.value?.summary || {};
  return (
    <Page title="Validation and Trust" subtitle="Executable evidence for schema health, migrations, events, snapshots, and docs conformance.">
      <div className="button-row top-actions"><button onClick={() => setRefreshKey((key) => key + 1)}>Refresh</button></div>
      <div className="grid metrics">
        <Metric label="Project" value={project.value?.status || "loading"} />
        <Metric label="Schema" value={summary.schema || "-"} />
        <Metric label="Events" value={summary.events || "-"} />
        <Metric label="Docs rows" value={matrix.value?.row_count || 0} />
      </div>
      <div className="two-col">
        <Panel title="Project Sections">
          <KeyValueGrid data={project.value?.sections || {}} />
        </Panel>
        <Panel title="Docs Matrix">
          <DataTable rows={matrix.value?.rows || []} />
        </Panel>
      </div>
    </Page>
  );
}

function Page({ title, subtitle, children }: { title: string; subtitle: string; children: ReactNode }) {
  return (
    <>
      <header className="page-header">
        <div>
          <h1>{title}</h1>
          <p>{subtitle}</p>
        </div>
        <a className="legacy-button" href={`${window.location.pathname}?legacy=1`}>Legacy view</a>
      </header>
      {children}
    </>
  );
}

function WorkspaceHeader({ title, tabs, actions }: { title: string; tabs: string[]; actions: ReactNode }) {
  return (
    <div className="workspace-header">
      <div>
        <strong>{title}</strong>
        <span>Batch</span>
      </div>
      <nav>{tabs.map((tab) => <button key={tab} className={tab === "Graph" ? "active" : ""}>{tab}</button>)}</nav>
      <div className="button-row">{actions}</div>
    </div>
  );
}

function Toolbar({ groups }: { groups: PipelineCanvasState["toolbar_groups"] }) {
  return (
    <div className="toolbar-strip">
      {groups.map((group) => (
        <div key={group.id} className="toolbar-group">
          <span>{group.label}</span>
          <div>{group.actions.slice(0, 8).map((action) => <button key={action} title={action}>{action.slice(0, 2).toUpperCase()}</button>)}</div>
        </div>
      ))}
    </div>
  );
}

function PipelineCanvas({
  canvas,
  zoom,
  selectedNodeId,
  onSelect,
  onDrop,
  onDragOver,
  onInsertEdge
}: {
  canvas: PipelineCanvasState | null;
  zoom: number;
  selectedNodeId: string;
  onSelect: (nodeId: string) => void;
  onDrop: (event: DragEvent<HTMLDivElement>) => void;
  onDragOver: (event: DragEvent<HTMLDivElement>) => void;
  onInsertEdge: () => void;
}) {
  const nodes = canvas?.nodes || [];
  const byId = new Map(nodes.map((node) => [node.id, node]));
  return (
    <div className="pipeline-canvas" onDrop={onDrop} onDragOver={onDragOver}>
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
        {nodes.map((node) => <PipelineNodeCard key={node.id} node={node} selected={selectedNodeId === node.id} onSelect={onSelect} />)}
      </div>
    </div>
  );
}

function PipelineNodeCard({ node, selected, onSelect }: { node: PipelineNode; selected: boolean; onSelect: (nodeId: string) => void }) {
  return (
    <button
      className={classNames("pipeline-node", node.category, selected && "selected", node.status === "ERROR" && "error")}
      style={{ left: node.position.x, top: node.position.y }}
      onClick={() => onSelect(node.id)}
    >
      <strong>{node.label}</strong>
      <small>{node.row_count ?? 0} rows</small>
      <span>{node.type}</span>
    </button>
  );
}

function BottomDrawer({ preview, selectedNode, suggestions, validation }: { preview: NodePreview | null; selectedNode: PipelineNode | null; suggestions: NodeSuggestions | null; validation?: PipelineCanvasState["validation"] }) {
  const [tab, setTab] = useState("preview");
  const rows = tab === "preview" ? (preview?.rows || selectedNode?.sample || []) : tab === "suggestions" ? (suggestions?.suggestions || []) : tab === "pipeline_warnings" ? (validation?.warnings || validation?.errors || []) : [];
  return (
    <section className="bottom-drawer">
      <nav>
        {["selection_preview", "preview", "transformations", "suggestions", "pipeline_warnings"].map((item) => (
          <button key={item} className={tab === item ? "active" : ""} onClick={() => setTab(item)}>{item.replace(/_/g, " ")}</button>
        ))}
      </nav>
      {tab === "selection_preview" && selectedNode ? <KeyValueGrid data={{ id: selectedNode.id, type: selectedNode.type, status: selectedNode.status, rows: selectedNode.row_count ?? 0 }} /> : null}
      {tab === "transformations" && selectedNode ? <DataTable rows={Object.entries(selectedNode.config || {}).map(([key, value]) => ({ key, value: formatValue(value) }))} /> : null}
      {tab !== "selection_preview" && tab !== "transformations" ? <DataTable rows={rows} empty="No preview rows, suggestions, or warnings for this node." /> : null}
    </section>
  );
}

function Panel({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="panel">
      <header className="panel-header">
        <h2>{title}</h2>
        {action}
      </header>
      {children}
    </section>
  );
}

function StatusBadge({ value }: { value?: string | number | null }) {
  const text = String(value ?? "unknown");
  const tone = text.toLowerCase();
  return <span className={classNames("badge", tone.includes("fail") || tone.includes("critical") || tone.includes("error") ? "bad" : tone.includes("warn") || tone.includes("pending") || tone.includes("active") ? "warn" : "good")}>{text}</span>;
}

function DataTable({ rows, empty = "No records" }: { rows?: TableRow[]; empty?: string }) {
  const safeRows = rows || [];
  const columns = useMemo(() => {
    const seen = new Set<string>();
    for (const row of safeRows.slice(0, 10)) Object.keys(row || {}).slice(0, 8).forEach((key) => seen.add(key));
    return Array.from(seen);
  }, [safeRows]);
  if (!safeRows.length) return <div className="empty">{empty}</div>;
  return (
    <div className="table-wrap">
      <table>
        <thead><tr>{columns.map((column) => <th key={column}>{column}</th>)}</tr></thead>
        <tbody>
          {safeRows.slice(0, 40).map((row, index) => (
            <tr key={index}>{columns.map((column) => <td key={column}>{formatValue(row[column])}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function KeyValueGrid({ data }: { data: JsonObject }) {
  const entries = Object.entries(data || {});
  if (!entries.length) return <div className="empty">No details available.</div>;
  return (
    <dl className="kv-grid">
      {entries.map(([key, value]) => (
        <div key={key}>
          <dt>{key.replace(/_/g, " ")}</dt>
          <dd>{formatValue(value)}</dd>
        </div>
      ))}
    </dl>
  );
}

function ImportJobSummary({ job }: { job: ImportJob | null }) {
  if (!job) return <div className="empty">Create an import job to review schema, transform data, and generate ontology.</div>;
  return (
    <div className="summary-list">
      <KeyValueGrid data={{
        id: job.id,
        status: job.status,
        target_dataset_id: job.target_dataset_id,
        transformed_rows: job.transformed_records?.length ?? 0
      }} />
      <DataTable rows={asRows(job.validation?.errors)} empty="No validation errors." />
    </div>
  );
}

function ProofTrail({ workflow }: { workflow: WorkflowState | null }) {
  const links = workflow?.evidence_links || [];
  return (
    <ol className="proof-trail">
      {(workflow?.steps || []).map((step) => (
        <li key={step.id}>
          <span>{step.label}</span>
          <strong>{step.evidence_id || step.status}</strong>
        </li>
      ))}
      {links.filter((link) => link.id).map((link) => (
        <li key={`${link.kind}-${link.id}`}>
          <span>{link.kind}</span>
          <a href={link.href}>{link.id}</a>
        </li>
      ))}
    </ol>
  );
}

function Metric({ label, value }: { label: string; value: unknown }) {
  return (
    <article className="metric-card">
      <strong>{formatValue(value)}</strong>
      <span>{label}</span>
    </article>
  );
}

function RelationshipStrip({ rows, fallback }: { rows: TableRow[]; fallback: string }) {
  if (!rows.length) {
    return <div className="relationship-strip"><span>{fallback}</span><button>Create new link type</button></div>;
  }
  return (
    <div className="relationship-strip">
      {rows.map((row) => (
        <article key={asString(row.id)}>
          <span>{formatValue(row.source_object_type_id)}</span>
          <strong>{formatValue(row.display_name || row.id)}</strong>
          <span>{formatValue(row.target_object_type_id)}</span>
        </article>
      ))}
    </div>
  );
}

function DebugJson({ title, value }: { title: string; value: unknown }) {
  if (!value) return null;
  return (
    <details className="debug-json">
      <summary>{title}</summary>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </details>
  );
}

function MiniGraph({ nodes, edges }: { nodes: TableRow[]; edges: TableRow[] }) {
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
