import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { useLocation } from "react-router-dom";
import { LogIn, LogOut, Search, User } from "lucide-react";
import { api, postJson } from "./api";
import {
  bootstrapProjectDemo,
  getCommandCenterState,
  getImportsState,
  getProjectReadiness,
  getValidationState,
  resetProjectDemo
} from "./api/workspaceState";
import {
  DataTable,
  DeveloperEvidence,
  EmptyState,
  ErrorBanner,
  EvidenceList,
  KeyValueGrid,
  LoadingState,
  Metric,
  Panel,
  SectionCards,
  StatusBadge,
  WarningList
} from "./components/data/DataDisplay";
import { Page, PlatformFlow } from "./components/workbench/Workbench";
import { useAsyncState } from "./hooks/useAsyncState";
import { asRows, asString, classNames } from "./utils/format";
import { currentWorkspaceView, navigate } from "./utils/navigation";
import { OntologyManager } from "./workspaces/OntologyManager";
import { PipelineBuilder } from "./workspaces/PipelineBuilder";
import { ControlPanel } from "./workspaces/ControlPanel";
import { Security } from "./workspaces/Security";
import { Automate } from "./workspaces/Automate";
import { DataMedia } from "./workspaces/DataMedia";
import { Vertex } from "./workspaces/Vertex";
import { Fusion } from "./workspaces/Fusion";
import { Analytics } from "./workspaces/Analytics";
import { Delivery } from "./workspaces/Delivery";
import { PlatformGraphWorkspace } from "./workspaces/PlatformGraph";
import { getAuthSession, logout, type AuthSession } from "./api/authApi";
import { getJobSummary } from "./api/jobApi";
import type {
  CommandCenterSummary,
  CommandCenterUiState,
  ImportsUiState,
  JsonObject,
  JobSummary,
  ProjectReadiness,
  TableRow,
  ValidationUiState,
  WorkflowState
} from "./types";

const CORE_VIEWS = new Set(["command-center", "imports", "ontology", "pipeline", "workshop", "aip", "investigations", "entity-resolution", "graph", "validation", "control-panel", "security", "automate", "data-media", "vertex", "fusion", "analytics", "delivery"]);
const VisualBuilder = lazy(() => import("./workspaces/VisualBuilder").then((module) => ({ default: module.VisualBuilder })));

const NAV_ITEMS = [
  { id: "command-center", label: "Command Center", hint: "Guided asset reliability workflow" },
  { id: "imports", label: "Data Onboarding", hint: "Upload, map, transform, connect, replay" },
  { id: "ontology", label: "Ontology Manager", hint: "Generate and manage object types" },
  { id: "pipeline", label: "Pipeline Builder", hint: "Canvas, previews, outputs" },
  { id: "workshop", label: "Workshop", hint: "Compose operational applications" },
  { id: "aip", label: "AIP Logic", hint: "Build governed decision logic" },
  { id: "investigations", label: "Investigations", hint: "Evidence, entities, hypotheses" },
  { id: "entity-resolution", label: "Entity Resolution", hint: "Review and merge duplicates" },
  { id: "graph", label: "Platform Graph", hint: "Inspect relationships and evidence" },
  { id: "validation", label: "Validation", hint: "Trust, conformance, schema health" },
  { id: "data-media", label: "Data & Media", hint: "Upload files, datasets, media" },
  { id: "automate", label: "Automate", hint: "Automations, conditions, effects, runs" },
  { id: "security", label: "Security & Governance", hint: "Markings, CBAC, projects, cipher" },
  { id: "control-panel", label: "Control Panel", hint: "Orgs, users, groups, roles, tokens" },
  { id: "vertex", label: "Vertex", hint: "Graph explorer: expand, layout, merge" },
  { id: "fusion", label: "Fusion", hint: "Spreadsheet: cells, formulas, lookups" },
  { id: "analytics", label: "Analytics", hint: "Object Explorer charts + Contour boards" },
  { id: "delivery", label: "Delivery", hint: "Marketplace, DevOps, code & compute" }
];

const LEGACY_ITEMS = ["map", "object-explorer", "models", "decision", "ops"];

const ENDPOINT_INVENTORY: TableRow[] = [
  {
    route: "/workspace/command-center",
    ui_state: "/ui-state/command-center",
    primary_actions: "/project/demo/bootstrap, /scenarios/asset-reliability/run-triage",
    evidence: "/scenarios/asset-reliability/report, /project/readiness"
  },
  {
    route: "/workspace/imports",
    ui_state: "/ui-state/imports",
    primary_actions: "/imports/csv, /imports/jobs/{id}/apply-transforms, /connections/sources/{id}/preview, /streams/{id}/replay",
    evidence: "/imports/jobs, /imports/templates"
  },
  {
    route: "/workspace/ontology",
    ui_state: "/ui-state/ontology",
    primary_actions: "/ontology-generator/drafts, /ontology-generator/drafts/{id}/apply, /ontology/object-types/{id}/properties",
    evidence: "/ui-state/ontology/object-types/{id}/walkthrough"
  },
  {
    route: "/workspace/pipeline",
    ui_state: "/ui-state/pipeline",
    primary_actions: "/pipeline-builder/graphs/{id}/nodes, /pipeline-builder/graphs/{id}/layout, /pipeline-builder/graphs/{id}/deliver",
    evidence: "/ui-state/pipeline/{id}/canvas, /ui-state/pipeline/{id}/outputs"
  },
  {
    route: "/workspace/graph",
    ui_state: "/graph/overview",
    primary_actions: "search/filter/select local graph nodes",
    evidence: "/graph/overview"
  },
  {
    route: "/workspace/validation",
    ui_state: "/ui-state/validation",
    primary_actions: "/project/validate, /project/readiness",
    evidence: "/system/migrations, /system/schema-health, docs conformance matrix"
  }
];

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

export function App() {
  useLocation();
  const view = currentWorkspaceView(CORE_VIEWS);
  const backendReadiness = useAsyncState<ProjectReadiness>(getProjectReadiness, []);
  const [runtimeRefresh, setRuntimeRefresh] = useState(0);
  const jobSummary = useAsyncState<JobSummary>(getJobSummary, [runtimeRefresh]);
  const authSession = useAsyncState<AuthSession>(getAuthSession, []);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [recentViews, setRecentViews] = useState<string[]>(() => JSON.parse(localStorage.getItem("ontology.recentViews") || "[]"));
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen((value) => !value);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);
  useEffect(() => {
    const timer = window.setInterval(() => setRuntimeRefresh((value) => value + 1), 15_000);
    return () => window.clearInterval(timer);
  }, []);

  function openView(nextView: string) {
    navigate(nextView);
    const nextRecent = [nextView, ...recentViews.filter((item) => item !== nextView)].slice(0, 5);
    setRecentViews(nextRecent);
    localStorage.setItem("ontology.recentViews", JSON.stringify(nextRecent));
  }

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
        <button className="command-palette-trigger" onClick={() => setPaletteOpen(true)}><Search size={16} /><span>Search and commands</span><kbd>Ctrl K</kbd></button>
        <nav>
          {NAV_ITEMS.map((item) => (
            <button key={item.id} className={classNames("nav-item", view === item.id && "active")} onClick={() => openView(item.id)}>
              <strong>{item.label}</strong>
              <span>{item.hint}</span>
            </button>
          ))}
        </nav>
        {recentViews.length ? <div className="recent-links"><strong>Recent</strong>{recentViews.map((item) => {
          const found = NAV_ITEMS.find((entry) => entry.id === item);
          return found ? <button key={item} onClick={() => openView(item)}>{found.label}</button> : null;
        })}</div> : null}
        <div className="legacy-links">
          <strong>Legacy during migration</strong>
          {LEGACY_ITEMS.map((item) => <a key={item} href={`/workspace/${item}?legacy=1`}>{item}</a>)}
        </div>
        <AuthIdentity session={authSession.value} loading={authSession.loading} error={authSession.error} />
      </aside>
      <main className="workspace">
        <PlatformFlow currentView={view} />
        <BackendConnection readiness={backendReadiness.value} loading={backendReadiness.loading} error={backendReadiness.error} jobs={jobSummary.value} jobsError={jobSummary.error} />
        <Suspense fallback={<LoadingState label="Loading visual workspace..." />}>
          {view === "command-center" && <CommandCenter />}
          {view === "imports" && <DataOnboarding />}
          {view === "ontology" && <OntologyManager />}
          {view === "pipeline" && <PipelineBuilder />}
          {view === "workshop" && <VisualBuilder artifactType="workshop" title="Workshop" subtitle="Compose responsive operational applications from governed data and actions." />}
          {view === "aip" && <VisualBuilder artifactType="aip_logic" title="AIP Logic" subtitle="Build typed, governed decision flows with visible tools and approval gates." />}
          {view === "investigations" && <VisualBuilder artifactType="investigation_graph" title="Investigations" subtitle="Organize entities, evidence, hypotheses, findings, and reports." />}
          {view === "entity-resolution" && <VisualBuilder artifactType="entity_resolution" title="Entity Resolution" subtitle="Review candidate matches and stage merge or split decisions." />}
          {view === "graph" && <PlatformGraphWorkspace />}
          {view === "validation" && <ValidationWorkspace />}
          {view === "data-media" && <DataMedia />}
          {view === "automate" && <Automate />}
          {view === "security" && <Security />}
          {view === "control-panel" && <ControlPanel />}
          {view === "vertex" && <Vertex />}
          {view === "fusion" && <Fusion />}
          {view === "analytics" && <Analytics />}
          {view === "delivery" && <Delivery />}
        </Suspense>
      </main>
      {paletteOpen ? <CommandPalette onClose={() => setPaletteOpen(false)} onOpen={(item) => { openView(item); setPaletteOpen(false); }} /> : null}
    </div>
  );
}

function AuthIdentity({ session, loading, error }: { session: AuthSession | null; loading: boolean; error: string }) {
  if (loading) return <div className="auth-identity"><User size={16} /><span>Checking session...</span></div>;
  if (error || !session?.authenticated) return <a className="auth-identity" href={`/auth/login?next=${encodeURIComponent(window.location.pathname)}`}><LogIn size={16} /><span>Sign in</span></a>;
  return (
    <div className="auth-identity">
      <User size={16} />
      <span><strong>{session.display_name}</strong><small>{session.roles.join(", ")}</small></span>
      {session.auth_mode === "oidc" ? <button title="Sign out" aria-label="Sign out" onClick={async () => { await logout(); window.location.assign("/auth/login"); }}><LogOut size={15} /></button> : null}
    </div>
  );
}

function CommandPalette({ onClose, onOpen }: { onClose: () => void; onOpen: (view: string) => void }) {
  const [query, setQuery] = useState("");
  const filtered = useMemo(() => NAV_ITEMS.filter((item) => `${item.label} ${item.hint}`.toLowerCase().includes(query.toLowerCase())), [query]);
  useEffect(() => {
    const handler = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);
  return (
    <div className="command-palette-backdrop" role="presentation" onMouseDown={onClose}>
      <section className="command-palette" role="dialog" aria-modal="true" aria-label="Search workspaces" onMouseDown={(event) => event.stopPropagation()}>
        <label><Search size={18} /><input autoFocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Find a workspace or capability" /></label>
        <div>{filtered.map((item) => <button key={item.id} onClick={() => onOpen(item.id)}><strong>{item.label}</strong><small>{item.hint}</small></button>)}</div>
        {!filtered.length ? <p>No matching workspaces.</p> : null}
      </section>
    </div>
  );
}

function BackendConnection({ readiness, loading, error, jobs, jobsError }: { readiness: ProjectReadiness | null; loading: boolean; error: string; jobs: JobSummary | null; jobsError: string }) {
  const status = error ? "OFFLINE" : loading ? "CHECKING" : readiness?.status || "UNKNOWN";
  const failedJobs = jobs?.counts.FAILED || 0;
  return (
    <div className={classNames("backend-connection", error && "offline", status === "READY" && "ready", failedJobs > 0 && "execution-warning")}>
      <div className="backend-connection-main">
        <StatusBadge value={status} />
        <span>{error ? `Backend connection failed: ${error}` : `Backend connection: ${status}`}</span>
        {jobs ? <span className="execution-health" aria-label="Asynchronous execution health">
          <strong>{jobs.counts.RUNNING || 0}</strong> running
          <strong>{jobs.counts.QUEUED || 0}</strong> queued
          <strong>{failedJobs}</strong> failed
          <strong>{jobs.active_workers}</strong> workers
        </span> : jobsError ? <small>Execution status unavailable</small> : null}
        {readiness?.summary ? (
          <small>
            {asString(readiness.summary.ready_checks, "0")}/{asString(readiness.summary.check_count, "0")} checks ready
          </small>
        ) : null}
      </div>
      {readiness ? (
        <DeveloperEvidence title="Developer evidence: readiness checks">
          <DataTable rows={readiness.checks || []} />
          <DataTable rows={readiness.recommended_actions || []} empty="No recommended actions." />
        </DeveloperEvidence>
      ) : null}
    </div>
  );
}

function CommandCenter() {
  const [refreshKey, setRefreshKey] = useState(0);
  const [lastRun, setLastRun] = useState<JsonObject | null>(null);
  const ui = useAsyncState<CommandCenterUiState>(getCommandCenterState, [refreshKey]);
  const workflow = ui.value?.workflow || null;
  const summary: CommandCenterSummary = workflow?.summary || {};
  const kpis = summary.kpis || {};
  const highRisk = summary.high_risk_assets || [];
  const evaluatorSummary = ui.value?.evaluator_summary || {};

  async function bootstrap() {
    setLastRun(await bootstrapProjectDemo());
    setRefreshKey((key) => key + 1);
  }

  async function resetDemo() {
    setLastRun(await resetProjectDemo());
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
      <ErrorBanner message={ui.error} />
      {ui.loading && <LoadingState label="Loading Command Center evidence..." />}
      <WarningList warnings={ui.value?.warnings} />
      <div className="hero-summary">
        <div>
          <span className="eyebrow">Evaluator summary</span>
          <h2>{asString(evaluatorSummary.title, "Reliability decision summary")}</h2>
          <p>{asString(evaluatorSummary.why, "Bootstrap the sample workflow to populate evidence and recommendations.")}</p>
        </div>
        <div className="decision-card">
          <StatusBadge value={asString(evaluatorSummary.risk_band, "not_scored")} />
          <strong>{asString(evaluatorSummary.decision, "Start sample data")}</strong>
          <span>{asString(evaluatorSummary.recommendation, "Load data, inspect risk, run triage, approve action, and export the report.")}</span>
        </div>
      </div>
      <div className="button-row top-actions">
        <button onClick={bootstrap}>Start with sample data</button>
        <button onClick={triage}>Run reliability triage</button>
        <button onClick={exportReport}>Export proof report</button>
        <button onClick={resetDemo}>Reset demo state</button>
      </div>
      <section className="stepper">
        {(workflow?.steps || []).map((step, index) => (
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
          {highRisk.length ? <DataTable rows={highRisk.map((item) => ({
            id: item.object_id,
            name: asString(item.object?.name || item.object?.display_name || item.object?.id),
            risk: asString(item.risk?.band),
            score: item.risk?.score,
            explanation: item.risk?.explanation
          }))} /> : <EmptyState title="No high-risk assets yet" description="Start with sample data or run triage to populate risk evidence." action={<button onClick={bootstrap}>Bootstrap scenario</button>} />}
        </Panel>
        <Panel title="Proof Trail" action={<button onClick={() => navigate("graph")}>Open graph</button>}>
          <ProofTrail workflow={workflow} />
          <EvidenceList links={ui.value?.evidence_links} />
        </Panel>
      </div>
      <SectionCards sections={ui.value?.sections} onNavigate={(href) => {
        if (href.startsWith("/workspace/")) navigate(href.replace("/workspace/", ""));
        else window.location.href = href;
      }} />
      {lastRun ? (
        <DeveloperEvidence title="Developer evidence: latest action result">
          <KeyValueGrid data={lastRun} />
        </DeveloperEvidence>
      ) : null}
      {!ui.value && !ui.loading && <div className="notice">Bootstrap the sample scenario to populate the Command Center.</div>}
    </Page>
  );
}

function DataOnboarding() {
  const [csvContent, setCsvContent] = useState("asset_id,name,status,criticality,vibration_mm_s,temperature_f,longitude,latitude\nasset_react_1,React Pump,degraded,HIGH,0.42,194,-122.4012,37.7924\nasset_react_1,React Pump,degraded,HIGH,0.42,194,-122.4012,37.7924\n");
  const [job, setJob] = useState<ImportJob | null>(null);
  const [suggestions, setSuggestions] = useState<TableRow[]>([]);
  const [sourcePreview, setSourcePreview] = useState<TableRow[]>([]);
  const [streamReplay, setStreamReplay] = useState<JsonObject | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const importsUi = useAsyncState<ImportsUiState>(getImportsState, [job?.id, streamReplay?.stream_id, refreshKey]);
  const jobs = useAsyncState<ImportJobsResponse>(() => api<ImportJobsResponse>("/imports/jobs"), [job?.id, streamReplay?.stream_id]);

  async function createCsvJob() {
    setJob(await postJson<ImportJob>("/imports/csv", {
      filename: "react-assets.csv",
      display_name: "React Asset Import",
      target_dataset_id: "react_asset_import_dataset",
      content: csvContent
    }));
    setRefreshKey((key) => key + 1);
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
    setRefreshKey((key) => key + 1);
  }

  async function generateDraft() {
    const jobId = job?.id;
    if (!jobId) return;
    setJob(await postJson<ImportJob>(`/imports/jobs/${encodeURIComponent(jobId)}/generate-ontology-draft`, {
      actor: "react",
      object_type_id: "react_asset",
      display_name: "React Asset"
    }));
    setRefreshKey((key) => key + 1);
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
    setRefreshKey((key) => key + 1);
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
    setRefreshKey((key) => key + 1);
  }

  return (
    <Page title="Data Onboarding" subtitle="Upload, map, transform, connect, and replay data before promotion.">
      <ErrorBanner message={importsUi.error} />
      {(importsUi.loading || jobs.loading) && <LoadingState label="Loading import endpoints..." />}
      <WarningList warnings={importsUi.value?.warnings} />
      <div className="workspace-summary-row">
        <Metric label="Import jobs" value={importsUi.value?.summary.job_count ?? 0} />
        <Metric label="Templates" value={importsUi.value?.summary.template_count ?? 0} />
        <Metric label="Latest job" value={importsUi.value?.summary.latest_job_id || "-"} />
      </div>
      <SectionCards sections={importsUi.value?.sections} onNavigate={(href) => {
        if (href.startsWith("/workspace/")) navigate(href.replace("/workspace/", ""));
      }} />
      <div className="two-col">
        <Panel title="CSV Import and Transform" action={<button onClick={createCsvJob}>Create Job</button>}>
          <textarea aria-label="CSV records" value={csvContent} onChange={(event) => setCsvContent(event.target.value)} />
          <div className="button-row">
            <button onClick={suggestMapping} disabled={!job?.id}>Suggest Mapping</button>
            <button onClick={transformJob} disabled={!job?.id}>Apply Transforms</button>
            <button onClick={generateDraft} disabled={!job?.id}>Generate Ontology Draft</button>
          </div>
          <ImportJobSummary job={job} />
        </Panel>
        <Panel title="Mapping Suggestions">
          <DataTable rows={suggestions} empty="Create an import job, then request mapping suggestions." />
        </Panel>
      </div>
      <div className="two-col">
        <Panel title="Hybrid Connector Preview" action={<button onClick={connectorPreview}>Preview REST Source</button>}>
          <DataTable rows={sourcePreview} />
        </Panel>
        <Panel title="Stream Replay" action={<button onClick={replayStream}>Replay Sensor Stream</button>}>
          {streamReplay ? <KeyValueGrid data={{
            status: streamReplay.status,
            stream_id: streamReplay.stream_id,
            target_asset_id: streamReplay.target_asset_id,
            record_count: streamReplay.record_count,
          }} /> : <div className="empty">Replay stream data into a local dataset.</div>}
        </Panel>
      </div>
      <Panel title="Sample Templates">
        <DataTable rows={importsUi.value?.templates || []} />
      </Panel>
      <Panel title="Recent Import Jobs">
        <DataTable rows={jobs.value?.jobs || []} />
      </Panel>
    </Page>
  );
}

function ValidationWorkspace() {
  const [refreshKey, setRefreshKey] = useState(0);
  const [statusFilter, setStatusFilter] = useState("ALL");
  const project = useAsyncState<{ status?: string; summary?: JsonObject; sections?: JsonObject }>(() => api("/project/validate"), [refreshKey]);
  const validationUi = useAsyncState<ValidationUiState>(getValidationState, [refreshKey]);
  const readiness = useAsyncState<ProjectReadiness>(getProjectReadiness, [refreshKey]);
  const summary = project.value?.summary || {};
  const rows = validationUi.value?.rows || [];
  const filteredRows = statusFilter === "ALL" ? rows : rows.filter((row) => row.status === statusFilter);
  return (
    <Page title="Validation and Trust" subtitle="Executable evidence for schema health, migrations, events, snapshots, and docs conformance.">
      <div className="button-row top-actions"><button onClick={() => setRefreshKey((key) => key + 1)}>Refresh</button></div>
      <ErrorBanner message={validationUi.error || readiness.error} />
      {(project.loading || validationUi.loading || readiness.loading) && <LoadingState label="Loading validation evidence..." />}
      <WarningList warnings={validationUi.value?.warnings} />
      <div className="grid metrics">
        <Metric label="Project" value={project.value?.status || "loading"} />
        <Metric label="Readiness" value={readiness.value?.status || "loading"} />
        <Metric label="Schema" value={summary.schema || "-"} />
        <Metric label="Events" value={summary.events || "-"} />
        <Metric label="Docs rows" value={validationUi.value?.summary.docs_row_count || 0} />
      </div>
      <SectionCards sections={validationUi.value?.sections} />
      <div className="two-col">
        <Panel title="Project Readiness">
          <DataTable rows={readiness.value?.checks || []} />
        </Panel>
        <Panel title="Docs Matrix" action={<select aria-label="Filter documentation status" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
          <option value="ALL">All statuses</option>
          <option value="MATCH">Match</option>
          <option value="LOCAL_ANALOG">Local analog</option>
          <option value="INTENTIONAL_DIFFERENCE">Intentional difference</option>
          <option value="PARTIAL">Partial</option>
          <option value="MISSING">Missing</option>
        </select>}>
          <DataTable rows={filteredRows} />
        </Panel>
      </div>
      <DeveloperEvidence title="Developer evidence: UI endpoint inventory">
        <DataTable rows={ENDPOINT_INVENTORY} />
      </DeveloperEvidence>
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
