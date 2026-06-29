import { useEffect, useMemo, useState, type ReactNode } from "react";
import { api, postJson } from "./api";

type AnyRecord = Record<string, any>;

const CORE_VIEWS = new Set(["command-center", "imports", "ontology", "pipeline", "graph", "validation"]);

const NAV_ITEMS = [
  { id: "command-center", label: "Command Center", hint: "Guided asset reliability workflow" },
  { id: "imports", label: "Data Onboarding", hint: "Upload, map, transform, connect, replay" },
  { id: "ontology", label: "Ontology Generator", hint: "Generate object types from datasets" },
  { id: "pipeline", label: "Pipeline Builder", hint: "Validate and deliver DAG outputs" },
  { id: "graph", label: "Platform Graph", hint: "Inspect relationships and evidence" },
  { id: "validation", label: "Validation", hint: "Trust, conformance, schema health" }
];

const LEGACY_ITEMS = [
  "aip",
  "map",
  "workshop",
  "object-explorer",
  "models",
  "decision",
  "ops",
  "investigations"
];

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

function Badge({ value }: { value?: string | number | null }) {
  const text = String(value ?? "unknown");
  const tone = text.toLowerCase();
  return <span className={classNames("badge", tone.includes("fail") || tone.includes("critical") ? "bad" : tone.includes("warn") || tone.includes("pending") ? "warn" : "good")}>{text}</span>;
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

function Table({ rows, empty = "No records" }: { rows?: AnyRecord[]; empty?: string }) {
  const safeRows = rows || [];
  const columns = useMemo(() => {
    const seen = new Set<string>();
    for (const row of safeRows.slice(0, 10)) {
      Object.keys(row || {}).slice(0, 8).forEach((key) => seen.add(key));
    }
    return Array.from(seen);
  }, [safeRows]);
  if (!safeRows.length) return <div className="empty">{empty}</div>;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>{columns.map((column) => <th key={column}>{column}</th>)}</tr>
        </thead>
        <tbody>
          {safeRows.slice(0, 25).map((row, index) => (
            <tr key={index}>
              {columns.map((column) => <td key={column}>{formatValue(row[column])}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function useAsyncState<T>(loader: () => Promise<T>, deps: unknown[] = []) {
  const [value, setValue] = useState<T | null>(null);
  const [error, setError] = useState<string>("");
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
        {view === "ontology" && <OntologyGenerator />}
        {view === "pipeline" && <PipelineWorkspace />}
        {view === "graph" && <GraphWorkspace />}
        {view === "validation" && <ValidationWorkspace />}
      </main>
    </div>
  );
}

function CommandCenter() {
  const [refreshKey, setRefreshKey] = useState(0);
  const [result, setResult] = useState<AnyRecord | null>(null);
  const summary = useAsyncState<AnyRecord>(() => api("/scenarios/asset-reliability/summary"), [refreshKey]);
  const validation = useAsyncState<AnyRecord>(() => api("/project/validate"), [refreshKey]);

  async function bootstrap() {
    setResult(await postJson("/scenarios/asset-reliability/bootstrap", { actor: "react", run_pipelines: true, run_checks: true }));
    setRefreshKey((key) => key + 1);
  }

  async function triage() {
    setResult(await postJson("/scenarios/asset-reliability/run-triage", { actor: "react" }));
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
  }

  const kpis = summary.value?.kpis || {};
  const highRisk = summary.value?.high_risk_assets || [];

  return (
    <Page title="Asset Reliability Command Center" subtitle="One guided path from data onboarding to governed operational action.">
      <section className="stepper">
        {["Start with sample data", "Upload or connect data", "Generate ontology", "Deliver pipeline", "Run reliability triage", "Approve action", "Export proof report"].map((label, index) => (
          <button key={label} onClick={() => (index === 0 ? bootstrap() : index === 4 ? triage() : index === 6 ? exportReport() : navigate(index === 1 ? "imports" : index === 2 ? "ontology" : index === 3 ? "pipeline" : "validation"))}>
            <span>{index + 1}</span>
            {label}
          </button>
        ))}
      </section>
      <div className="grid metrics">
        <Metric label="High risk assets" value={kpis.high_risk_assets ?? 0} />
        <Metric label="Open alerts" value={kpis.active_alerts ?? 0} />
        <Metric label="Failing checks" value={kpis.failing_checks ?? 0} />
        <Metric label="Open approvals" value={kpis.open_approvals ?? 0} />
      </div>
      <div className="two-col">
        <Panel title="High-Risk Assets" action={<button onClick={() => setRefreshKey((key) => key + 1)}>Refresh</button>}>
          <Table rows={highRisk.map((item: AnyRecord) => ({ id: item.id, name: item.name, risk: item.risk_band, status: item.status, criticality: item.criticality }))} />
        </Panel>
        <Panel title="Proof Trail">
          <ProofTrail summary={summary.value} validation={validation.value} result={result} />
        </Panel>
      </div>
      {result && (
        <Panel title="Latest Run Output">
          <pre>{JSON.stringify(result, null, 2)}</pre>
        </Panel>
      )}
      {summary.error && <div className="notice">Bootstrap the sample scenario to populate the Command Center.</div>}
    </Page>
  );
}

function DataOnboarding() {
  const [csvContent, setCsvContent] = useState("asset_id,name,status,criticality,vibration_mm_s,temperature_f,longitude,latitude\nasset_react_1,React Pump,degraded,HIGH,0.42,194,-122.4012,37.7924\nasset_react_1,React Pump,degraded,HIGH,0.42,194,-122.4012,37.7924\n");
  const [job, setJob] = useState<AnyRecord | null>(null);
  const [suggestions, setSuggestions] = useState<AnyRecord | null>(null);
  const [sourcePreview, setSourcePreview] = useState<AnyRecord | null>(null);
  const [streamReplay, setStreamReplay] = useState<AnyRecord | null>(null);
  const jobs = useAsyncState<AnyRecord>(() => api("/imports/jobs"), [job?.id, streamReplay?.stream_id]);

  async function createCsvJob() {
    const created = await postJson<AnyRecord>("/imports/csv", {
      filename: "react-assets.csv",
      display_name: "React Asset Import",
      target_dataset_id: "react_asset_import_dataset",
      content: csvContent
    });
    setJob(created);
  }

  async function suggestMapping() {
    if (!job?.id) return;
    setSuggestions(await api(`/imports/jobs/${job.id}/mapping-suggestions?template=asset`));
  }

  async function transformJob() {
    if (!job?.id) return;
    const transformed = await postJson<AnyRecord>(`/imports/jobs/${job.id}/apply-transforms`, {
      actor: "react",
      steps: [
        { op: "enum_cleanup", field: "status", mapping: { degraded: "DEGRADED", running: "RUNNING" } },
        { op: "enum_cleanup", field: "criticality", mapping: { high: "high", medium: "medium", low: "low" } },
        { op: "normalize_unit", source: "temperature_f", target: "temperature_c", from_unit: "fahrenheit", to_unit: "celsius" },
        { op: "normalize_unit", source: "vibration_mm_s", target: "vibration_mm_s", from_unit: "ips", to_unit: "mm_s" },
        { op: "derive_point", latitude_field: "latitude", longitude_field: "longitude", target: "geometry" },
        { op: "deduplicate", keys: ["asset_id"] }
      ]
    });
    setJob(transformed.job);
  }

  async function generateDraft() {
    if (!job?.id) return;
    setJob(await postJson(`/imports/jobs/${job.id}/generate-ontology-draft`, { actor: "react", object_type_id: "react_asset", display_name: "React Asset" }));
  }

  async function connectorPreview() {
    const source = await postJson<AnyRecord>("/connections/sources", {
      id: "react_rest_source",
      display_name: "React REST Source",
      source_type: "rest",
      config: {
        base_url: "http://localhost:9000/mock-assets",
        sample_records: [{ asset_id: "asset_connector_1", name: "Connector Pump", status: "RUNNING", criticality: "medium" }]
      }
    }).catch(() => api<AnyRecord>("/connections/sources/react_rest_source"));
    const preview = await postJson<AnyRecord>(`/connections/sources/${source.id}/preview`, { limit: 10 });
    setSourcePreview(preview);
    const importJob = await postJson<AnyRecord>(`/connections/sources/${source.id}/generate-import-job`, {
      id: "react_connector_import",
      display_name: "React Connector Import",
      target_dataset_id: "react_connector_dataset",
      template: "asset",
      actor: "react"
    }).catch(() => api<AnyRecord>("/imports/jobs/react_connector_import"));
    setJob(importJob.job || importJob);
  }

  async function replayStream() {
    await postJson("/streams", {
      id: "react_sensor_stream",
      display_name: "React Sensor Stream",
      schema: { sample_records: [{ reading_id: "r1", asset_id: "asset_react_1", vibration_mm_s: 11.2, observed_at: "1782684300" }] }
    }).catch(() => api("/streams/react_sensor_stream"));
    setStreamReplay(await postJson("/streams/react_sensor_stream/replay", {
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
          {job && <pre>{JSON.stringify(job, null, 2)}</pre>}
        </Panel>
        <Panel title="Mapping Suggestions">
          <Table rows={suggestions?.suggestions || []} />
        </Panel>
      </div>
      <div className="two-col">
        <Panel title="Hybrid Connector Preview" action={<button onClick={connectorPreview}>Preview REST Source</button>}>
          <Table rows={sourcePreview?.preview_rows || []} />
        </Panel>
        <Panel title="Stream Replay" action={<button onClick={replayStream}>Replay Sensor Stream</button>}>
          {streamReplay ? <pre>{JSON.stringify(streamReplay, null, 2)}</pre> : <div className="empty">Replay stream data into a local dataset.</div>}
        </Panel>
      </div>
      <Panel title="Recent Import Jobs">
        <Table rows={jobs.value?.jobs || []} />
      </Panel>
    </Page>
  );
}

function OntologyGenerator() {
  const [refreshKey, setRefreshKey] = useState(0);
  const [assetId, setAssetId] = useState("");
  const [result, setResult] = useState<AnyRecord | null>(null);
  const assets = useAsyncState<AnyRecord[]>(() => api("/data-assets"), [refreshKey]);
  const drafts = useAsyncState<AnyRecord[]>(() => api("/ontology-generator/drafts"), [refreshKey]);

  async function createDraft() {
    if (!assetId) return;
    const id = `${assetId}_react_draft`.replace(/[^a-zA-Z0-9_]/g, "_");
    setResult(await postJson("/ontology-generator/drafts", {
      id,
      asset_id: assetId,
      object_type_id: `${assetId}_object`.replace(/[^a-zA-Z0-9_]/g, "_"),
      include_actions: true,
      create_pipeline_graph: true
    }));
    setRefreshKey((key) => key + 1);
  }

  async function applyDraft(id: string) {
    setResult(await postJson(`/ontology-generator/drafts/${id}/apply`, { actor: "react", create_actions: true, create_pipeline_graph: true }));
    setRefreshKey((key) => key + 1);
  }

  return (
    <Page title="Ontology Generator" subtitle="Generate reviewed ontology drafts from promoted datasets.">
      <Panel title="Create Draft" action={<button onClick={createDraft} disabled={!assetId}>Generate</button>}>
        <select value={assetId} onChange={(event) => setAssetId(event.target.value)}>
          <option value="">Choose dataset</option>
          {(assets.value || []).map((asset) => <option key={asset.id} value={asset.id}>{asset.display_name || asset.id}</option>)}
        </select>
      </Panel>
      <Panel title="Drafts">
        <div className="cards">
          {(drafts.value || []).map((draft) => (
            <article key={draft.id} className="resource-card">
              <strong>{draft.id}</strong>
              <span>{draft.object_type_id}</span>
              <Badge value={draft.status} />
              <button onClick={() => applyDraft(draft.id)}>Apply</button>
            </article>
          ))}
        </div>
      </Panel>
      {result && <Panel title="Latest Ontology Result"><pre>{JSON.stringify(result, null, 2)}</pre></Panel>}
    </Page>
  );
}

function PipelineWorkspace() {
  const [refreshKey, setRefreshKey] = useState(0);
  const [selected, setSelected] = useState("");
  const [result, setResult] = useState<AnyRecord | null>(null);
  const graphs = useAsyncState<AnyRecord[]>(() => api("/pipeline-builder/graphs"), [refreshKey]);
  const nodeTypes = useAsyncState<AnyRecord>(() => api("/pipeline-builder/node-types"), []);
  const graph = (graphs.value || []).find((item) => item.id === selected) || (graphs.value || [])[0];

  async function run(action: "validate" | "preview" | "deliver") {
    if (!graph?.id) return;
    setSelected(graph.id);
    setResult(await postJson(`/pipeline-builder/graphs/${graph.id}/${action}`, { actor: "react" }));
    setRefreshKey((key) => key + 1);
  }

  return (
    <Page title="Pipeline Builder" subtitle="Validate, preview, and deliver DAGs generated by onboarding and ontology workflows.">
      <div className="two-col">
        <Panel title="Graphs">
          <div className="cards">
            {(graphs.value || []).map((item) => (
              <button key={item.id} className={classNames("resource-card", (selected || graph?.id) === item.id && "selected")} onClick={() => setSelected(item.id)}>
                <strong>{item.display_name || item.id}</strong>
                <span>{item.nodes?.length || 0} nodes</span>
              </button>
            ))}
          </div>
        </Panel>
        <Panel title="Node Library">
          <Table rows={(nodeTypes.value?.node_types || []).map((node: AnyRecord) => ({ type: node.type, label: node.label || node.type, category: node.category }))} />
        </Panel>
      </div>
      <Panel title="Selected Graph" action={<div className="button-row"><button onClick={() => run("validate")}>Validate</button><button onClick={() => run("preview")}>Preview</button><button onClick={() => run("deliver")}>Deliver</button></div>}>
        <GraphList graph={graph} />
      </Panel>
      {result && <Panel title="Pipeline Result"><pre>{JSON.stringify(result, null, 2)}</pre></Panel>}
    </Page>
  );
}

function GraphWorkspace() {
  const graph = useAsyncState<AnyRecord>(() => api("/graph/overview"), []);
  return (
    <Page title="Platform Graph" subtitle="Searchable overview of datasets, pipelines, objects, incidents, and reports.">
      <Panel title="Graph Canvas">
        <MiniGraph nodes={graph.value?.nodes || []} edges={graph.value?.edges || []} />
      </Panel>
      <div className="two-col">
        <Panel title="Nodes"><Table rows={graph.value?.nodes || []} /></Panel>
        <Panel title="Edges"><Table rows={graph.value?.edges || []} /></Panel>
      </div>
    </Page>
  );
}

function ValidationWorkspace() {
  const [refreshKey, setRefreshKey] = useState(0);
  const project = useAsyncState<AnyRecord>(() => api("/project/validate"), [refreshKey]);
  const matrix = useAsyncState<AnyRecord>(() => api("/scenarios/asset-reliability/validation-dashboard"), [refreshKey]);
  const sections = project.value?.sections || {};
  return (
    <Page title="Validation and Trust" subtitle="Executable evidence for schema health, migrations, events, snapshots, and docs conformance.">
      <div className="button-row top-actions"><button onClick={() => setRefreshKey((key) => key + 1)}>Refresh</button></div>
      <div className="grid metrics">
        <Metric label="Project" value={project.value?.status || "loading"} />
        <Metric label="Schema" value={project.value?.summary?.schema || "-"} />
        <Metric label="Events" value={project.value?.summary?.events || "-"} />
        <Metric label="Docs rows" value={matrix.value?.row_count || sections.docs_conformance?.row_count || 0} />
      </div>
      <div className="two-col">
        <Panel title="Project Validation">
          <pre>{JSON.stringify(project.value || project.error || {}, null, 2)}</pre>
        </Panel>
        <Panel title="Docs Matrix">
          <Table rows={matrix.value?.rows || []} />
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

function Metric({ label, value }: { label: string; value: unknown }) {
  return (
    <article className="metric-card">
      <strong>{formatValue(value)}</strong>
      <span>{label}</span>
    </article>
  );
}

function ProofTrail({ summary, validation, result }: { summary: AnyRecord | null; validation: AnyRecord | null; result: AnyRecord | null }) {
  const items = [
    { label: "Pipeline run", value: summary?.latest_pipeline_run_id },
    { label: "Dataset/import job", value: summary?.latest_import_job_id || summary?.dataset_id },
    { label: "Risk explanation", value: summary?.selected_asset?.risk_band || result?.risk?.band },
    { label: "Approval/action", value: result?.approval?.id || summary?.latest_approval_id },
    { label: "Audit/event", value: validation?.summary?.events },
    { label: "Incident/report", value: summary?.latest_report_id || "available" }
  ];
  return (
    <ol className="proof-trail">
      {items.map((item) => (
        <li key={item.label}>
          <span>{item.label}</span>
          <strong>{formatValue(item.value || "pending")}</strong>
        </li>
      ))}
    </ol>
  );
}

function GraphList({ graph }: { graph?: AnyRecord }) {
  if (!graph) return <div className="empty">No pipeline graph yet. Generate one from Ontology Generator.</div>;
  return (
    <div className="pipeline-list">
      {(graph.nodes || []).map((node: AnyRecord, index: number) => (
        <article key={node.id || index}>
          <span>{index + 1}</span>
          <div>
            <strong>{node.label || node.id}</strong>
            <small>{node.type}</small>
          </div>
        </article>
      ))}
    </div>
  );
}

function MiniGraph({ nodes, edges }: { nodes: AnyRecord[]; edges: AnyRecord[] }) {
  const width = 940;
  const height = 380;
  const positioned: Array<AnyRecord & { x: number; y: number }> = nodes.slice(0, 40).map((node, index) => {
    const angle = (Math.PI * 2 * index) / Math.max(nodes.length, 1);
    return {
      ...node,
      x: width / 2 + Math.cos(angle) * 320,
      y: height / 2 + Math.sin(angle) * 135
    };
  });
  const byId = new Map(positioned.map((node) => [node.id, node]));
  return (
    <svg className="mini-graph" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Platform graph">
      {edges.slice(0, 80).map((edge, index) => {
        const source = byId.get(edge.source || edge.source_id);
        const target = byId.get(edge.target || edge.target_id);
        if (!source || !target) return null;
        return <line key={index} x1={source.x} y1={source.y} x2={target.x} y2={target.y} />;
      })}
      {positioned.map((node) => (
        <g key={node.id} transform={`translate(${node.x}, ${node.y})`}>
          <circle r="18" />
          <text y="4">{String(node.kind || node.type || "?").slice(0, 2).toUpperCase()}</text>
          <title>{node.label || node.title || node.id}</title>
        </g>
      ))}
    </svg>
  );
}
