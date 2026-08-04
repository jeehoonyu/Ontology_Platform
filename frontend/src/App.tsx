import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { Check, LogIn, LogOut, Menu, PlayCircle, Search, User, X, XCircle } from "lucide-react";
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
import { getAuthSession, logout, type AuthSession } from "./api/authApi";
import { getJob, getJobSummary } from "./api/jobApi";
import {
  createConnectionSource,
  getConnectionSource,
  getConnectorAdapters,
  listConnectorCredentials,
  listConnectorFetchAttempts,
  previewLiveConnector,
  rotateConnectorCredential
} from "./api/connectorApi";
import type {
  ConnectionSource,
  ConnectorCredentialMetadata,
  ConnectorFetchAttempt,
  ApprovalRequest,
  AssetReliabilityTriageResult,
  CommandCenterSummary,
  CommandCenterUiState,
  GovernedActionEvidence,
  ImportsUiState,
  IndustrialWorkflowState,
  JsonObject,
  JobSummary,
  PlatformJob,
  ProjectReadiness,
  TableRow,
  ValidationUiState,
  WorkflowState
} from "./types";

const CORE_VIEWS = new Set(["command-center", "imports", "ontology", "pipeline", "object-explorer", "map", "models", "decision", "ops", "workshop", "aip", "investigations", "entity-resolution", "graph", "validation", "control-panel", "security", "automate", "data-media", "vertex", "fusion", "analytics", "delivery"]);
const OntologyManager = lazy(() => import("./workspaces/OntologyManager").then((module) => ({ default: module.OntologyManager })));
const PipelineBuilder = lazy(() => import("./workspaces/PipelineBuilder").then((module) => ({ default: module.PipelineBuilder })));
const ObjectExplorer = lazy(() => import("./workspaces/ObjectExplorer").then((module) => ({ default: module.ObjectExplorer })));
const MapWorkspace = lazy(() => import("./workspaces/MapWorkspace").then((module) => ({ default: module.MapWorkspace })));
const ModelOps = lazy(() => import("./workspaces/ModelOps").then((module) => ({ default: module.ModelOps })));
const DecisionWorkspace = lazy(() => import("./workspaces/DecisionWorkspace").then((module) => ({ default: module.DecisionWorkspace })));
const OpsWorkspace = lazy(() => import("./workspaces/OpsWorkspace").then((module) => ({ default: module.OpsWorkspace })));
const ControlPanel = lazy(() => import("./workspaces/ControlPanel").then((module) => ({ default: module.ControlPanel })));
const Security = lazy(() => import("./workspaces/Security").then((module) => ({ default: module.Security })));
const Automate = lazy(() => import("./workspaces/Automate").then((module) => ({ default: module.Automate })));
const DataMedia = lazy(() => import("./workspaces/DataMedia").then((module) => ({ default: module.DataMedia })));
const Vertex = lazy(() => import("./workspaces/Vertex").then((module) => ({ default: module.Vertex })));
const Fusion = lazy(() => import("./workspaces/Fusion").then((module) => ({ default: module.Fusion })));
const Analytics = lazy(() => import("./workspaces/Analytics").then((module) => ({ default: module.Analytics })));
const Delivery = lazy(() => import("./workspaces/Delivery").then((module) => ({ default: module.Delivery })));
const PlatformGraphWorkspace = lazy(() => import("./workspaces/PlatformGraph").then((module) => ({ default: module.PlatformGraphWorkspace })));
const VisualBuilder = lazy(() => import("./workspaces/VisualBuilder").then((module) => ({ default: module.VisualBuilder })));

const NAV_ITEMS = [
  { id: "command-center", label: "Command Center", hint: "Guided asset reliability workflow" },
  { id: "imports", label: "Data Onboarding", hint: "Upload, map, transform, connect, replay" },
  { id: "ontology", label: "Ontology Manager", hint: "Generate and manage object types" },
  { id: "pipeline", label: "Pipeline Builder", hint: "Canvas, previews, outputs" },
  { id: "object-explorer", label: "Object Explorer", hint: "Search, filter, inspect, and act" },
  { id: "map", label: "Operational Map", hint: "Layers, MGRS, geofences, and risk" },
  { id: "models", label: "ModelOps", hint: "Train, gate, deploy, monitor, and infer" },
  { id: "decision", label: "Decision Intelligence", hint: "Explain risk, history, duplicates, and scenarios" },
  { id: "ops", label: "Operational Control", hint: "Alerts, incidents, runbooks, and reliability" },
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

const LEGACY_ITEMS: string[] = [];

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
    route: "/workspace/object-explorer",
    ui_state: "/object-explorer/query, /object-explorer/explorations",
    primary_actions: "/objects/{type}/{id}/profile, /decision/evaluate, /actions/execute",
    evidence: "/object-explorer/histogram, /object-sets/search-around"
  },
  {
    route: "/workspace/map",
    ui_state: "/gis/map-layers, /gis/map-layers/{id}/features",
    primary_actions: "/gis/feature-collection, /gis/mgrs/encode, /gis/mgrs/decode, /gis/geofence/evaluate",
    evidence: "/gis/spatial-query, /gis/ops/buffer"
  },
  {
    route: "/workspace/models",
    ui_state: "/modelops/summary, /modeling/objectives, /modelops/monitors",
    primary_actions: "/modeling/objectives/{id}/train, /modeling/deployments, /modelops/monitors/{id}/run",
    evidence: "/modeling/submissions/{id}/release-eligibility, /modelops/deployments/{id}/prediction-logs"
  },
  {
    route: "/workspace/decision",
    ui_state: "/decision/rules, /decision/scorecards, /decision/evaluate",
    primary_actions: "/decision/objects/{type}/{id}/explain, /entity-resolution/jobs, /decision/scenarios",
    evidence: "/temporal/objects/{type}/{id}/timeline, /aip/agents/{id}/runs"
  },
  {
    route: "/workspace/ops",
    ui_state: "/ops/summary, /ops/events, /ops/alerts, /reliability/summary",
    primary_actions: "/ops/alerts/evaluate, /ops/incidents, /ops/runbooks/{id}/execute",
    evidence: "/ops/inbox, /ops/incidents/{id}, /reliability/data-contracts/{id}/runs"
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
  const [, setLocationVersion] = useState(0);
  useEffect(() => {
    const handleNavigation = () => setLocationVersion((version) => version + 1);
    window.addEventListener("popstate", handleNavigation);
    return () => window.removeEventListener("popstate", handleNavigation);
  }, []);
  const view = currentWorkspaceView(CORE_VIEWS);
  const backendReadiness = useAsyncState<ProjectReadiness>(getProjectReadiness, []);
  const [runtimeRefresh, setRuntimeRefresh] = useState(0);
  const jobSummary = useAsyncState<JobSummary>(getJobSummary, [runtimeRefresh]);
  const authSession = useAsyncState<AuthSession>(getAuthSession, []);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [navigationOpen, setNavigationOpen] = useState(false);
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
    setNavigationOpen(false);
    const nextRecent = [nextView, ...recentViews.filter((item) => item !== nextView)].slice(0, 5);
    setRecentViews(nextRecent);
    localStorage.setItem("ontology.recentViews", JSON.stringify(nextRecent));
  }

  return (
    <div className="app-shell">
      <aside className={classNames("sidebar", navigationOpen && "navigation-open")}>
        <div className="brand">
          <span>OA</span>
          <div>
            <strong>Ontology AIP</strong>
            <small>React evaluator shell</small>
          </div>
        </div>
        <button className="command-palette-trigger" aria-label="Search and commands" onClick={() => setPaletteOpen(true)}><Search size={16} /><span>Search and commands</span><kbd>Ctrl K</kbd></button>
        <button
          className="sidebar-toggle"
          type="button"
          aria-controls="primary-navigation"
          aria-expanded={navigationOpen}
          aria-label={navigationOpen ? "Close workspace navigation" : "Open workspace navigation"}
          onClick={() => setNavigationOpen((open) => !open)}
        >
          {navigationOpen ? <X size={18} /> : <Menu size={18} />}
        </button>
        <nav id="primary-navigation" aria-label="Workspaces">
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
          {view === "object-explorer" && <ObjectExplorer />}
          {view === "map" && <MapWorkspace />}
          {view === "models" && <ModelOps />}
          {view === "decision" && <DecisionWorkspace />}
          {view === "ops" && <OpsWorkspace />}
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
  const [activeApproval, setActiveApproval] = useState<ApprovalRequest | null>(null);
  const [actionResult, setActionResult] = useState<GovernedActionEvidence | null>(null);
  const [approvalReason, setApprovalReason] = useState("Operational evidence reviewed; escalation is authorized.");
  const [governanceBusy, setGovernanceBusy] = useState(false);
  const [governanceError, setGovernanceError] = useState<string | null>(null);
  const [governanceMessage, setGovernanceMessage] = useState<string | null>(null);
  const [industrialSource, setIndustrialSource] = useState({
    projectId: "default", assetId: "", idField: "id", nameField: "name", statusField: "status",
    criticalityField: "criticality", riskField: "predicted_failure_probability", latitudeField: "latitude", longitudeField: "longitude",
    executionMode: "synchronous" as "synchronous" | "background"
  });
  const [industrialResult, setIndustrialResult] = useState<JsonObject | null>(null);
  const [industrialJob, setIndustrialJob] = useState<PlatformJob | null>(null);
  const [industrialWorkflow, setIndustrialWorkflow] = useState<IndustrialWorkflowState | null>(null);
  const ui = useAsyncState<CommandCenterUiState>(getCommandCenterState, [refreshKey]);
  const workflow = ui.value?.workflow || null;
  const summary: CommandCenterSummary = workflow?.summary || {};
  const kpis = summary.kpis || {};
  const highRisk = summary.high_risk_assets || [];
  const evaluatorSummary = ui.value?.evaluator_summary || {};
  const approval = activeApproval || industrialWorkflow?.summary.latest_approval || summary.approvals?.[0] || summary.latest_approval || null;
  const latestAction = actionResult || industrialWorkflow?.summary.latest_action || summary.latest_action || null;
  const actionMatchesApproval = Boolean(approval?.id && latestAction?.approval_request_id === approval.id);
  const activeWorkflow = industrialWorkflow || workflow;

  async function refreshIndustrialWorkflow(projectId = industrialSource.projectId) {
    const state = await api<IndustrialWorkflowState>(`/api/v1/industrial/workflows/asset-reliability/workflow-state?project_id=${encodeURIComponent(projectId)}`);
    if (state.status !== "NOT_CONFIGURED") setIndustrialWorkflow(state);
    if (state.summary.latest_execution_job) setIndustrialJob(state.summary.latest_execution_job);
    if (state.summary.latest_approval) setActiveApproval(state.summary.latest_approval);
    return state;
  }

  useEffect(() => {
    void refreshIndustrialWorkflow(industrialSource.projectId).catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!industrialJob?.id || !["QUEUED", "RUNNING"].includes(industrialJob.status)) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const next = await getJob(industrialJob.id);
        if (cancelled) return;
        setIndustrialJob(next);
        if (next.status === "SUCCEEDED") {
          setIndustrialResult(next.result);
          await refreshIndustrialWorkflow(industrialSource.projectId);
          setGovernanceMessage("Background onboarding completed. Snapshot, ontology, risk, and execution evidence are ready.");
          setRefreshKey((key) => key + 1);
        } else if (["FAILED", "CANCELLED"].includes(next.status)) {
          setGovernanceError(next.error || `Background onboarding ${next.status.toLowerCase()}.`);
        }
      } catch (error) {
        if (!cancelled) setGovernanceError(error instanceof Error ? error.message : "Could not refresh background onboarding");
      }
    };
    const timer = window.setInterval(() => void poll(), 1500);
    void poll();
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [industrialJob?.id, industrialJob?.status, industrialSource.projectId]);

  async function bootstrap() {
    setGovernanceBusy(true);
    setGovernanceError(null);
    try {
      setLastRun(await bootstrapProjectDemo());
      setIndustrialWorkflow(null);
      setIndustrialResult(null);
      setIndustrialJob(null);
      setGovernanceMessage("Sample data, pipeline evidence, ontology objects, and reliability checks are ready.");
      setRefreshKey((key) => key + 1);
    } catch (error) {
      setGovernanceError(error instanceof Error ? error.message : "Scenario bootstrap failed");
    } finally {
      setGovernanceBusy(false);
    }
  }

  async function resetDemo() {
    setGovernanceBusy(true);
    setGovernanceError(null);
    try {
      setLastRun(await resetProjectDemo());
      setActiveApproval(null);
      setActionResult(null);
      setIndustrialWorkflow(null);
      setIndustrialResult(null);
      setIndustrialJob(null);
      setGovernanceMessage("Demo resources are ready.");
      setRefreshKey((key) => key + 1);
    } catch (error) {
      setGovernanceError(error instanceof Error ? error.message : "Demo reset failed");
    } finally {
      setGovernanceBusy(false);
    }
  }

  async function triage() {
    setGovernanceBusy(true);
    setGovernanceError(null);
    try {
      const result = industrialWorkflow
        ? await postJson<AssetReliabilityTriageResult>("/api/v1/industrial/workflows/asset-reliability/triage", { project_id: industrialWorkflow.project_id })
        : await postJson<AssetReliabilityTriageResult>("/scenarios/asset-reliability/run-triage", { actor: "react" });
      setLastRun(result as unknown as JsonObject);
      setActiveApproval(result.approval);
      setActionResult(null);
      setGovernanceMessage("Triage completed. The proposed action is waiting for human approval.");
      if (industrialWorkflow) await refreshIndustrialWorkflow(industrialWorkflow.project_id);
      setRefreshKey((key) => key + 1);
    } catch (error) {
      setGovernanceError(error instanceof Error ? error.message : "Reliability triage failed");
    } finally {
      setGovernanceBusy(false);
    }
  }

  async function decideApproval(decision: "APPROVED" | "REJECTED") {
    if (!approval) return;
    setGovernanceBusy(true);
    setGovernanceError(null);
    try {
      const decided = await postJson<ApprovalRequest>(`/approvals/${encodeURIComponent(approval.id)}/decision`, {
        actor: "react",
        decision,
        reason: approvalReason
      });
      setActiveApproval(decided);
      setGovernanceMessage(decision === "APPROVED" ? "Approval recorded. The governed action is ready to execute." : "Proposal rejected. No object state was changed.");
      if (industrialWorkflow) await refreshIndustrialWorkflow(industrialWorkflow.project_id);
      setRefreshKey((key) => key + 1);
    } catch (error) {
      setGovernanceError(error instanceof Error ? error.message : "Approval decision failed");
    } finally {
      setGovernanceBusy(false);
    }
  }

  async function executeApprovedAction() {
    if (!approval || approval.status !== "APPROVED") return;
    setGovernanceBusy(true);
    setGovernanceError(null);
    try {
      const result = await postJson<GovernedActionEvidence>("/actions/execute", {
        action_type_id: approval.action_type_id,
        parameters: approval.parameters,
        idempotency_key: `command-center-${approval.id}`,
        actor: "react",
        approval_request_id: approval.id
      });
      setActionResult({ ...result, approval_request_id: approval.id, action_type_id: approval.action_type_id });
      setGovernanceMessage("Governed action executed. Audit and transactional outbox evidence are available.");
      if (industrialWorkflow) await refreshIndustrialWorkflow(industrialWorkflow.project_id);
      setRefreshKey((key) => key + 1);
    } catch (error) {
      setGovernanceError(error instanceof Error ? error.message : "Action execution failed");
    } finally {
      setGovernanceBusy(false);
    }
  }

  async function exportReport() {
    const reportPath = industrialWorkflow
      ? `/api/v1/industrial/workflows/asset-reliability/report?project_id=${encodeURIComponent(industrialWorkflow.project_id)}&format=markdown`
      : "/scenarios/asset-reliability/report?format=markdown";
    const markdown = await api<string>(reportPath);
    const blob = new Blob([markdown], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = industrialWorkflow ? `${industrialWorkflow.project_id}-asset-reliability-report.md` : "asset-reliability-report.md";
    link.click();
    URL.revokeObjectURL(url);
    setRefreshKey((key) => key + 1);
  }

  async function onboardPromotedDataset() {
    setGovernanceBusy(true);
    setGovernanceError(null);
    try {
      const result = await postJson<JsonObject>("/api/v1/industrial/workflows/asset-reliability/onboard", {
        project_id: industrialSource.projectId,
        source_asset_id: industrialSource.assetId,
        display_name: "Industrial Asset",
        mapping: {
          id_field: industrialSource.idField,
          name_field: industrialSource.nameField || null,
          status_field: industrialSource.statusField || null,
          criticality_field: industrialSource.criticalityField || null,
          risk_field: industrialSource.riskField || null,
          latitude_field: industrialSource.latitudeField || null,
          longitude_field: industrialSource.longitudeField || null,
          serial_number_field: null
        },
        risk_threshold: 0.7,
        run_pipeline: true,
        publish_ontology: true,
        allow_breaking_ontology: false,
        execution_mode: industrialSource.executionMode
      });
      setIndustrialResult(result);
      const queuedJob = result.execution as unknown as PlatformJob | undefined;
      setIndustrialJob(queuedJob?.id ? queuedJob : null);
      if (asString(result.status) !== "QUEUED") await refreshIndustrialWorkflow(industrialSource.projectId);
      setActiveApproval(null);
      setActionResult(null);
      setLastRun(result);
      setGovernanceMessage(asString(result.status) === "QUEUED"
        ? "Background onboarding queued. A worker will deliver the snapshot and reconcile ontology objects with resumable checkpoints."
        : "Your dataset is connected to a project-owned ontology, hydration pipeline, and explainable risk scorecard.");
      setRefreshKey((key) => key + 1);
    } catch (error) {
      setGovernanceError(error instanceof Error ? error.message : "Industrial dataset onboarding failed");
    } finally {
      setGovernanceBusy(false);
    }
  }

  return (
    <Page title="Asset Reliability Command Center" subtitle="Guided path from data onboarding to governed operational action.">
      <ErrorBanner message={ui.error || governanceError || undefined} />
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
        <button onClick={bootstrap} disabled={governanceBusy}>Start with sample data</button>
        <button onClick={triage} disabled={governanceBusy || Boolean(industrialResult && !industrialWorkflow)}>{governanceBusy ? "Working..." : industrialWorkflow ? "Analyze your highest-risk asset" : "Run reliability triage"}</button>
        <button onClick={exportReport} disabled={governanceBusy}>Export proof report</button>
        <button onClick={resetDemo} disabled={governanceBusy}>Reset demo state</button>
      </div>
      <Panel title="Use your promoted dataset" action={<StatusBadge value={industrialResult ? "READY" : "OPTIONAL"} />}>
        <p className="panel-intro">Compile a project-owned asset ontology, executable hydration pipeline, geospatial fields, and governed reliability scorecard from imported data.</p>
        <div className="form-grid industrial-onboarding-grid">
          <label><span>Project ID</span><input value={industrialSource.projectId} onChange={(event) => setIndustrialSource((value) => ({ ...value, projectId: event.target.value }))} /></label>
          <label><span>Promoted dataset ID</span><input value={industrialSource.assetId} placeholder="asset-import-output" onChange={(event) => setIndustrialSource((value) => ({ ...value, assetId: event.target.value }))} /></label>
          <label><span>Unique asset field</span><input value={industrialSource.idField} onChange={(event) => setIndustrialSource((value) => ({ ...value, idField: event.target.value }))} /></label>
          <label><span>Display name field</span><input value={industrialSource.nameField} onChange={(event) => setIndustrialSource((value) => ({ ...value, nameField: event.target.value }))} /></label>
          <label><span>Status field</span><input value={industrialSource.statusField} onChange={(event) => setIndustrialSource((value) => ({ ...value, statusField: event.target.value }))} /></label>
          <label><span>Criticality field</span><input value={industrialSource.criticalityField} onChange={(event) => setIndustrialSource((value) => ({ ...value, criticalityField: event.target.value }))} /></label>
          <label><span>Failure probability field</span><input value={industrialSource.riskField} onChange={(event) => setIndustrialSource((value) => ({ ...value, riskField: event.target.value }))} /></label>
          <label><span>Latitude / longitude fields</span><div className="inline-field-pair"><input aria-label="Latitude field" value={industrialSource.latitudeField} onChange={(event) => setIndustrialSource((value) => ({ ...value, latitudeField: event.target.value }))} /><input aria-label="Longitude field" value={industrialSource.longitudeField} onChange={(event) => setIndustrialSource((value) => ({ ...value, longitudeField: event.target.value }))} /></div></label>
          <label><span>Execution mode</span><select aria-label="Execution mode" value={industrialSource.executionMode} onChange={(event) => setIndustrialSource((value) => ({ ...value, executionMode: event.target.value as "synchronous" | "background" }))}><option value="synchronous">Immediate - small datasets</option><option value="background">Background worker - large datasets</option></select></label>
        </div>
        <div className="button-row">
          <button className="primary" onClick={() => void onboardPromotedDataset()} disabled={governanceBusy || !industrialSource.projectId.trim() || !industrialSource.assetId.trim() || !industrialSource.idField.trim()}>Compile and run workflow</button>
          <a className="button-link" href="/workspace/imports">Import or promote data</a>
        </div>
        {industrialResult ? <div className="governed-action-summary industrial-result-summary">
          <div><span>Workflow</span><strong>{asString(industrialResult.status, "READY")}</strong></div>
          <div><span>Ontology contract</span><strong>{asString(((industrialResult.ontology_contract as JsonObject | undefined)?.registry as JsonObject | undefined)?.version, "published")}</strong></div>
          <div><span>Objects hydrated</span><strong>{asString((industrialResult.summary as JsonObject | undefined)?.objects_hydrated, "0")}</strong></div>
          <div><span>High-risk assets</span><strong>{asString((industrialResult.summary as JsonObject | undefined)?.high_risk_assets, "0")}</strong></div>
          <div><span>Immutable source</span><strong>{asString((industrialResult.resources as JsonObject | undefined)?.source_snapshot, "not created")}</strong></div>
          <div><span>Execution plan</span><strong>{asString((industrialResult.resources as JsonObject | undefined)?.pipeline_plan, "not compiled")}</strong></div>
        </div> : null}
        {industrialJob ? <div className="operation-feedback" role="status" aria-label="Background onboarding status">
          <StatusBadge value={industrialJob.status} />
          <span>Background onboarding {industrialJob.progress}%</span>
          <span>Attempt {industrialJob.attempt}</span>
          {industrialJob.error ? <span>{industrialJob.error}</span> : null}
        </div> : null}
      </Panel>
      <section className="stepper">
        {(activeWorkflow?.steps || []).map((step, index) => (
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
      <Panel title="Governed Approval and Action" action={<StatusBadge value={actionMatchesApproval ? "EXECUTED" : approval?.status || "NOT_STAGED"} />}>
        {approval ? (
          <div className="governed-action-panel">
            <div className="governed-action-summary">
              <div><span>Action</span><strong>{approval.action_type_id}</strong></div>
              <div><span>Requested by</span><strong>{approval.requester}</strong></div>
              <div><span>Approval</span><StatusBadge value={approval.status} /></div>
              <div><span>Execution</span><StatusBadge value={actionMatchesApproval ? latestAction?.status || "EXECUTED" : "NOT_EXECUTED"} /></div>
            </div>
            <KeyValueGrid data={approval.parameters} />
            {approval.status === "PENDING" ? (
              <>
                <label className="approval-reason-field"><span>Decision reason</span><input value={approvalReason} onChange={(event) => setApprovalReason(event.target.value)} /></label>
                <div className="button-row">
                  <button onClick={() => void decideApproval("APPROVED")} disabled={governanceBusy || !approvalReason.trim()}><Check size={15} /> Approve action</button>
                  <button className="secondary" onClick={() => void decideApproval("REJECTED")} disabled={governanceBusy || !approvalReason.trim()}><XCircle size={15} /> Reject</button>
                </div>
              </>
            ) : null}
            {approval.status === "APPROVED" && !actionMatchesApproval ? (
              <button onClick={() => void executeApprovedAction()} disabled={governanceBusy}><PlayCircle size={15} /> Execute approved action</button>
            ) : null}
            {actionMatchesApproval && latestAction ? (
              <div className="action-evidence" aria-label="Governed action evidence">
                <strong>Execution evidence</strong>
                <KeyValueGrid data={{
                  status: latestAction.status,
                  outbox_event_id: latestAction.id || latestAction.outbox_event_id || "recorded",
                  delivery_status: latestAction.outbox_status || "QUEUED",
                  mutated_objects: latestAction.mutated_object_ids?.join(", ") || "No direct mutation"
                }} />
              </div>
            ) : null}
          </div>
        ) : <EmptyState title="No action is staged" description="Run reliability triage to produce an explainable recommendation and approval request." action={<button onClick={triage}>Run triage</button>} />}
        {governanceMessage ? <div className="operation-feedback" role="status">{governanceMessage}</div> : null}
      </Panel>
      <div className="two-col">
        <Panel title="High-Risk Assets" action={<button onClick={() => setRefreshKey((key) => key + 1)}>Refresh</button>}>
          {highRisk.length ? <DataTable rows={highRisk.map((item) => {
            const properties = (item.object?.properties || {}) as JsonObject;
            return {
              id: item.object_id,
              name: asString(properties.name || properties.display_name || item.object?.id),
              risk: asString(item.risk?.band),
              score: item.risk?.score,
              explanation: item.risk?.explanation
            };
          })} /> : <EmptyState title="No high-risk assets yet" description="Start with sample data or run triage to populate risk evidence." action={<button onClick={bootstrap}>Bootstrap scenario</button>} />}
        </Panel>
        <Panel title="Proof Trail" action={<button onClick={() => navigate("graph")}>Open graph</button>}>
          <ProofTrail workflow={activeWorkflow} />
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
  const [activeSource, setActiveSource] = useState<ConnectionSource | null>(null);
  const [credentials, setCredentials] = useState<ConnectorCredentialMetadata[]>([]);
  const [fetchAttempts, setFetchAttempts] = useState<ConnectorFetchAttempt[]>([]);
  const [connectorError, setConnectorError] = useState<string | null>(null);
  const [connectorBusy, setConnectorBusy] = useState(false);
  const [connectorForm, setConnectorForm] = useState({
    sourceId: "react_live_rest_source",
    displayName: "Live Asset REST Source",
    adapter: "rest" as "rest" | "jdbc" | "s3" | "sftp" | "kafka",
    endpoint: "http://localhost:9100",
    recordsPath: "records",
    table: "assets",
    bucket: "operations-data",
    region: "us-west-2",
    prefix: "assets/",
    port: "22",
    username: "operator",
    remotePath: "/incoming",
    hostKey: "",
    topic: "asset-events",
    securityProtocol: "PLAINTEXT" as "PLAINTEXT" | "SSL" | "SASL_PLAINTEXT" | "SASL_SSL",
    saslMechanism: "PLAIN" as "PLAIN" | "SCRAM-SHA-256" | "SCRAM-SHA-512",
    credentialType: "bearer" as "none" | "bearer" | "api_key" | "basic" | "aws" | "sftp_password" | "sftp_private_key" | "kafka_sasl_plain",
    secret: "",
    identity: "",
    sessionToken: ""
  });
  const [streamReplay, setStreamReplay] = useState<JsonObject | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const importsUi = useAsyncState<ImportsUiState>(getImportsState, [job?.id, streamReplay?.stream_id, refreshKey]);
  const jobs = useAsyncState<ImportJobsResponse>(() => api<ImportJobsResponse>("/imports/jobs"), [job?.id, streamReplay?.stream_id]);
  const connectorCatalog = useAsyncState(getConnectorAdapters, [refreshKey]);

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

  async function refreshConnectorEvidence(sourceId: string) {
    const [credentialRows, attemptRows] = await Promise.all([
      listConnectorCredentials(sourceId).catch(() => []),
      listConnectorFetchAttempts(sourceId)
    ]);
    setCredentials(credentialRows);
    setFetchAttempts(attemptRows);
  }

  async function connectorPreview() {
    setConnectorBusy(true);
    setConnectorError(null);
    const sourceId = connectorForm.sourceId.trim();
    try {
      const config: JsonObject = connectorForm.adapter === "rest"
        ? { execution_mode: "live", base_url: connectorForm.endpoint.trim(), records_path: connectorForm.recordsPath.trim() || "records" }
        : connectorForm.adapter === "jdbc"
          ? { execution_mode: "live", sqlalchemy_url: connectorForm.endpoint.trim(), table: connectorForm.table.trim(), driver_class: "sqlalchemy" }
          : connectorForm.adapter === "s3" ? {
              execution_mode: "live", endpoint_url: connectorForm.endpoint.trim(), bucket: connectorForm.bucket.trim(),
              region: connectorForm.region.trim(), prefix: connectorForm.prefix.trim(), format: "auto",
              max_objects: 100, max_object_bytes: 10_000_000, max_records: 100_000
            } : connectorForm.adapter === "sftp" ? {
              execution_mode: "live", host: connectorForm.endpoint.trim(), port: Number(connectorForm.port),
              username: connectorForm.username.trim(), remote_path: connectorForm.remotePath.trim(),
              host_key_sha256: connectorForm.hostKey.trim(), format: "auto",
              max_files: 100, max_file_bytes: 10_000_000, max_records: 100_000
            } : {
              execution_mode: "live", bootstrap_servers: connectorForm.endpoint.trim(), topic: connectorForm.topic.trim(),
              security_protocol: connectorForm.securityProtocol, sasl_mechanism: connectorForm.saslMechanism,
              auto_offset_reset: "earliest", poll_timeout_ms: 1000, max_records: 1000
            };
      const source = await createConnectionSource({
        id: sourceId,
        display_name: connectorForm.displayName.trim(),
        source_type: connectorForm.adapter,
        config
      }).catch(() => getConnectionSource(sourceId));
      setActiveSource(source);
      if (connectorForm.secret && connectorForm.credentialType !== "none") {
        const metadata: Record<string, string> = connectorForm.credentialType === "api_key"
          ? { header_name: connectorForm.identity.trim() || "X-API-Key" }
          : connectorForm.credentialType === "basic"
            ? { username: connectorForm.identity.trim() }
            : connectorForm.credentialType === "aws"
              ? { access_key_id: connectorForm.identity.trim(), ...(connectorForm.sessionToken ? { session_token: connectorForm.sessionToken } : {}) }
              : connectorForm.credentialType === "kafka_sasl_plain"
                ? { username: connectorForm.identity.trim() }
                : {};
        await rotateConnectorCredential(source.id, {
          credential_type: connectorForm.credentialType,
          secret: connectorForm.secret,
          metadata
        });
        setConnectorForm((current) => ({ ...current, secret: "", sessionToken: "" }));
      }
      const preview = await previewLiveConnector(source.id, 25);
      setSourcePreview(preview.preview_rows || []);
      await refreshConnectorEvidence(source.id);
    } catch (error) {
      setConnectorError(error instanceof Error ? error.message : "Connector preview failed");
      if (sourceId) await listConnectorFetchAttempts(sourceId).then(setFetchAttempts).catch(() => undefined);
    } finally {
      setConnectorBusy(false);
      setRefreshKey((key) => key + 1);
    }
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
      <ErrorBanner message={importsUi.error || connectorCatalog.error || connectorError || undefined} />
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
      <div className="two-col connector-onboarding-grid">
        <Panel title="Live Connector" action={<button onClick={connectorPreview} disabled={connectorBusy || !connectorForm.sourceId.trim()}>{connectorBusy ? "Connecting..." : "Save and Preview"}</button>}>
          <div className="connector-form-grid">
            <label><span>Adapter</span><select value={connectorForm.adapter} onChange={(event) => {
              const adapter = event.target.value as "rest" | "jdbc" | "s3" | "sftp" | "kafka";
              setConnectorForm((current) => ({
                ...current, adapter,
                credentialType: adapter === "s3" ? "aws" : adapter === "sftp" ? "sftp_password" : adapter === "kafka" ? "none" : ["aws", "sftp_password", "sftp_private_key", "kafka_sasl_plain", "none"].includes(current.credentialType) ? "bearer" : current.credentialType
              }));
            }}><option value="rest">REST API</option><option value="jdbc">PostgreSQL / SQL</option><option value="s3">S3-compatible storage</option><option value="sftp">SFTP files</option><option value="kafka">Kafka stream</option></select></label>
            <label><span>Source ID</span><input value={connectorForm.sourceId} onChange={(event) => setConnectorForm((current) => ({ ...current, sourceId: event.target.value }))} /></label>
            <label className="connector-wide-field"><span>Display name</span><input value={connectorForm.displayName} onChange={(event) => setConnectorForm((current) => ({ ...current, displayName: event.target.value }))} /></label>
            <label className="connector-wide-field"><span>{connectorForm.adapter === "rest" ? "Base URL" : connectorForm.adapter === "jdbc" ? "SQLAlchemy URL" : connectorForm.adapter === "s3" ? "S3 endpoint URL" : connectorForm.adapter === "sftp" ? "SFTP host" : "Bootstrap servers"}</span><input value={connectorForm.endpoint} onChange={(event) => setConnectorForm((current) => ({ ...current, endpoint: event.target.value }))} placeholder={connectorForm.adapter === "rest" ? "https://api.example.com/assets" : connectorForm.adapter === "jdbc" ? "postgresql+psycopg2://user@host/database" : connectorForm.adapter === "s3" ? "https://s3.us-west-2.amazonaws.com" : connectorForm.adapter === "sftp" ? "files.example.com" : "kafka.example.com:9093"} /></label>
            {connectorForm.adapter === "rest" ? <label><span>Records path</span><input value={connectorForm.recordsPath} onChange={(event) => setConnectorForm((current) => ({ ...current, recordsPath: event.target.value }))} /></label> : connectorForm.adapter === "jdbc" ? <label><span>Table</span><input value={connectorForm.table} onChange={(event) => setConnectorForm((current) => ({ ...current, table: event.target.value }))} /></label> : connectorForm.adapter === "s3" ? <>
              <label><span>Bucket</span><input value={connectorForm.bucket} onChange={(event) => setConnectorForm((current) => ({ ...current, bucket: event.target.value }))} /></label>
              <label><span>Region</span><input value={connectorForm.region} onChange={(event) => setConnectorForm((current) => ({ ...current, region: event.target.value }))} /></label>
              <label className="connector-wide-field"><span>Object prefix</span><input value={connectorForm.prefix} onChange={(event) => setConnectorForm((current) => ({ ...current, prefix: event.target.value }))} placeholder="assets/" /></label>
            </> : connectorForm.adapter === "sftp" ? <>
              <label><span>Port</span><input inputMode="numeric" value={connectorForm.port} onChange={(event) => setConnectorForm((current) => ({ ...current, port: event.target.value }))} /></label>
              <label><span>Username</span><input value={connectorForm.username} onChange={(event) => setConnectorForm((current) => ({ ...current, username: event.target.value }))} /></label>
              <label className="connector-wide-field"><span>Remote path</span><input value={connectorForm.remotePath} onChange={(event) => setConnectorForm((current) => ({ ...current, remotePath: event.target.value }))} /></label>
              <label className="connector-wide-field"><span>Host key SHA256</span><input value={connectorForm.hostKey} onChange={(event) => setConnectorForm((current) => ({ ...current, hostKey: event.target.value }))} placeholder="SHA256:..." /></label>
            </> : <>
              <label><span>Topic</span><input value={connectorForm.topic} onChange={(event) => setConnectorForm((current) => ({ ...current, topic: event.target.value }))} /></label>
              <label><span>Security protocol</span><select value={connectorForm.securityProtocol} onChange={(event) => {
                const securityProtocol = event.target.value as "PLAINTEXT" | "SSL" | "SASL_PLAINTEXT" | "SASL_SSL";
                setConnectorForm((current) => ({ ...current, securityProtocol, credentialType: securityProtocol.startsWith("SASL") ? "kafka_sasl_plain" : "none" }));
              }}><option value="PLAINTEXT">PLAINTEXT (development)</option><option value="SSL">TLS</option><option value="SASL_PLAINTEXT">SASL plaintext</option><option value="SASL_SSL">SASL over TLS</option></select></label>
              {connectorForm.securityProtocol.startsWith("SASL") && <label><span>SASL mechanism</span><select value={connectorForm.saslMechanism} onChange={(event) => setConnectorForm((current) => ({ ...current, saslMechanism: event.target.value as "PLAIN" | "SCRAM-SHA-256" | "SCRAM-SHA-512" }))}><option value="PLAIN">PLAIN</option><option value="SCRAM-SHA-256">SCRAM-SHA-256</option><option value="SCRAM-SHA-512">SCRAM-SHA-512</option></select></label>}
            </>}
            <label><span>Authentication</span><select value={connectorForm.credentialType} disabled={connectorForm.adapter === "s3" || connectorForm.adapter === "kafka"} onChange={(event) => setConnectorForm((current) => ({ ...current, credentialType: event.target.value as "none" | "bearer" | "api_key" | "basic" | "aws" | "sftp_password" | "sftp_private_key" | "kafka_sasl_plain" }))}>{connectorForm.adapter === "s3" ? <option value="aws">AWS SigV4</option> : connectorForm.adapter === "sftp" ? <><option value="sftp_password">Password</option><option value="sftp_private_key">Private key</option></> : connectorForm.adapter === "kafka" ? <option value={connectorForm.securityProtocol.startsWith("SASL") ? "kafka_sasl_plain" : "none"}>{connectorForm.securityProtocol.startsWith("SASL") ? "SASL credential" : "No credential"}</option> : <><option value="bearer">Bearer token</option><option value="api_key">API key</option><option value="basic">Username/password</option></>}</select></label>
            {["basic", "api_key", "aws", "kafka_sasl_plain"].includes(connectorForm.credentialType) && <label><span>{connectorForm.credentialType === "basic" || connectorForm.credentialType === "kafka_sasl_plain" ? "Username" : connectorForm.credentialType === "aws" ? "Access key ID" : "Header name"}</span><input value={connectorForm.identity} onChange={(event) => setConnectorForm((current) => ({ ...current, identity: event.target.value }))} /></label>}
            {connectorForm.credentialType !== "none" && (connectorForm.credentialType === "sftp_private_key" ? <label className="connector-wide-field"><span>Private key (write only)</span><textarea value={connectorForm.secret} onChange={(event) => setConnectorForm((current) => ({ ...current, secret: event.target.value }))} placeholder="-----BEGIN OPENSSH PRIVATE KEY-----" /></label> : <label className="connector-wide-field"><span>{connectorForm.credentialType === "basic" || connectorForm.credentialType === "sftp_password" || connectorForm.credentialType === "kafka_sasl_plain" ? "Password" : connectorForm.credentialType === "aws" ? "Secret access key (write only)" : "Secret (write only)"}</span><input type="password" autoComplete="new-password" value={connectorForm.secret} onChange={(event) => setConnectorForm((current) => ({ ...current, secret: event.target.value }))} placeholder={credentials.some((item) => item.status === "ACTIVE") ? "Leave blank to keep active credential" : connectorForm.adapter === "s3" || connectorForm.adapter === "sftp" || connectorForm.credentialType === "kafka_sasl_plain" ? "Required for source access" : "Optional for public sources"} /></label>)}
            {connectorForm.credentialType === "aws" && <label className="connector-wide-field"><span>Session token (optional, write only)</span><input type="password" autoComplete="new-password" value={connectorForm.sessionToken} onChange={(event) => setConnectorForm((current) => ({ ...current, sessionToken: event.target.value }))} /></label>}
          </div>
          <div className="connector-runtime-summary"><StatusBadge value={activeSource?.status || "NOT_CONNECTED"} /><span>{activeSource ? `${activeSource.display_name} uses ${activeSource.source_type}` : "Configure a live source to test access and inspect records."}</span></div>
          <DataTable rows={sourcePreview} empty="No live records previewed." />
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
      <div className="two-col">
        <Panel title="Connector Adapters">
          <DataTable rows={(connectorCatalog.value?.adapters || []).map((adapter) => ({ adapter: adapter.id, status: adapter.available ? "AVAILABLE" : "PLUGIN_REQUIRED", modes: adapter.modes?.join(", ") || "-", reason: adapter.reason || "Installed" }))} empty="No connector adapters are registered." />
        </Panel>
        <Panel title="Fetch Evidence">
          <DataTable rows={fetchAttempts.map((attempt) => ({ status: attempt.status, adapter: attempt.adapter_id, operation: attempt.operation, records: attempt.records_read, bytes: attempt.bytes_read, duration_ms: attempt.duration_ms, error: attempt.error || "-" }))} empty="Run a live preview to create durable fetch evidence." />
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

function ProofTrail({ workflow }: { workflow: Pick<WorkflowState, "steps" | "evidence_links"> | Pick<IndustrialWorkflowState, "steps" | "evidence_links"> | null }) {
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
