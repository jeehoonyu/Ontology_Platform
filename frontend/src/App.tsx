import { useEffect, useState } from "react";
import { api, postJson } from "./api";
import { getWorkflowState } from "./api/workspaceState";
import { MiniGraph } from "./components/canvas/PipelineCanvas";
import { DataTable, DebugJson, KeyValueGrid, Metric, Panel, StatusBadge } from "./components/data/DataDisplay";
import { Page } from "./components/workbench/Workbench";
import { useAsyncState } from "./hooks/useAsyncState";
import { asRows, asString, classNames } from "./utils/format";
import { currentWorkspaceView, navigate } from "./utils/navigation";
import { OntologyManager } from "./workspaces/OntologyManager";
import { PipelineBuilder } from "./workspaces/PipelineBuilder";
import type {
  CommandCenterSummary,
  JsonObject,
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

export function App() {
  const [view, setView] = useState(currentWorkspaceView(CORE_VIEWS));
  useEffect(() => {
    const handler = () => setView(currentWorkspaceView(CORE_VIEWS));
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
        {view === "pipeline" && <PipelineBuilder />}
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
