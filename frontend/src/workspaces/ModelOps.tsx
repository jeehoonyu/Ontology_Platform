import { useCallback, useEffect, useMemo, useState } from "react";
import { Activity, Beaker, Check, ChevronRight, Gauge, Play, Plus, RefreshCw, Rocket, ShieldCheck, Trash2, X } from "lucide-react";
import { DataTable, EmptyState, ErrorBanner, KeyValueGrid, LoadingState, Metric, Panel, StatusBadge } from "../components/data/DataDisplay";
import { Page } from "../components/workbench/Workbench";
import type { JsonObject, JsonValue, TableRow } from "../types";
import {
  createCheck,
  createDeployment,
  createMonitor,
  createObjective,
  createRelease,
  decideCheck,
  evaluateChecks,
  getModelOpsSummary,
  getReleaseEligibility,
  listCheckResults,
  listChecks,
  listDeployments,
  listModelAssets,
  listMonitorRuns,
  listMonitors,
  listObjectives,
  listPredictionLogs,
  listReleases,
  listSubmissions,
  promoteRelease,
  releaseSubmission,
  runInference,
  runMonitor,
  trainObjective,
  type DataAssetSummary,
  type InferenceResponse,
  type ModelCheck,
  type ModelCheckResult,
  type ModelDeployment,
  type ModelMonitor,
  type ModelObjective,
  type ModelOpsSummary,
  type ModelRelease,
  type ModelSubmission,
  type MonitorRun,
  type PredictionLog,
  type ReleaseEligibility
} from "../api/modelOpsApi";

type Tab = "objectives" | "training" | "gates" | "releases" | "monitoring" | "inference";
const TABS: Array<{ id: Tab; label: string }> = [
  { id: "objectives", label: "Objectives" },
  { id: "training", label: "Training" },
  { id: "gates", label: "Evaluation Gates" },
  { id: "releases", label: "Releases & Deployments" },
  { id: "monitoring", label: "Monitoring" },
  { id: "inference", label: "Inference Playground" }
];

function splitFields(value: string): string[] {
  return value.split(",").map((item) => item.trim()).filter(Boolean);
}

function inferValue(value: string): JsonValue {
  const trimmed = value.trim();
  if (trimmed === "") return null;
  if (trimmed.toLowerCase() === "true") return true;
  if (trimmed.toLowerCase() === "false") return false;
  const number = Number(trimmed);
  return Number.isFinite(number) ? number : trimmed;
}

function formatTime(epoch?: number | null): string {
  return epoch ? new Date(epoch * 1000).toLocaleString() : "not recorded";
}

export function ModelOps() {
  const [tab, setTab] = useState<Tab>("objectives");
  const [summary, setSummary] = useState<ModelOpsSummary | null>(null);
  const [assets, setAssets] = useState<DataAssetSummary[]>([]);
  const [objectives, setObjectives] = useState<ModelObjective[]>([]);
  const [deployments, setDeployments] = useState<ModelDeployment[]>([]);
  const [monitors, setMonitors] = useState<ModelMonitor[]>([]);
  const [objectiveId, setObjectiveId] = useState("");
  const [submissionId, setSubmissionId] = useState("");
  const [deploymentId, setDeploymentId] = useState("");
  const [monitorId, setMonitorId] = useState("");
  const [submissions, setSubmissions] = useState<ModelSubmission[]>([]);
  const [checks, setChecks] = useState<ModelCheck[]>([]);
  const [checkResults, setCheckResults] = useState<ModelCheckResult[]>([]);
  const [eligibility, setEligibility] = useState<ReleaseEligibility | null>(null);
  const [releases, setReleases] = useState<ModelRelease[]>([]);
  const [monitorRuns, setMonitorRuns] = useState<MonitorRun[]>([]);
  const [predictionLogs, setPredictionLogs] = useState<PredictionLog[]>([]);
  const [inferenceResult, setInferenceResult] = useState<InferenceResponse | null>(null);
  const [inferenceRows, setInferenceRows] = useState<Array<Record<string, string>>>([{}]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const selectedObjective = objectives.find((item) => item.id === objectiveId) || null;
  const selectedSubmission = submissions.find((item) => item.id === submissionId) || null;
  const selectedDeployment = deployments.find((item) => item.id === deploymentId) || null;
  const selectedMonitor = monitors.find((item) => item.id === monitorId) || null;
  const selectedRun = monitorRuns[0] || selectedMonitor?.latest_run || null;

  const loadObjectiveDetails = useCallback(async (nextObjectiveId: string, preferredSubmission = "") => {
    if (!nextObjectiveId) {
      setSubmissions([]); setChecks([]); setReleases([]); setSubmissionId(""); setEligibility(null); setCheckResults([]);
      return;
    }
    const [nextSubmissions, nextChecks, nextReleases] = await Promise.all([
      listSubmissions(nextObjectiveId), listChecks(nextObjectiveId), listReleases(nextObjectiveId)
    ]);
    setSubmissions(nextSubmissions);
    setChecks(nextChecks);
    setReleases(nextReleases);
    const nextSubmissionId = nextSubmissions.some((item) => item.id === preferredSubmission) ? preferredSubmission : nextSubmissions[0]?.id || "";
    setSubmissionId(nextSubmissionId);
    if (nextSubmissionId) {
      const [nextResults, nextEligibility] = await Promise.all([listCheckResults(nextSubmissionId), getReleaseEligibility(nextSubmissionId)]);
      setCheckResults(nextResults);
      setEligibility(nextEligibility);
    } else {
      setCheckResults([]); setEligibility(null);
    }
  }, []);

  const loadMonitorDetails = useCallback(async (nextMonitorId: string) => {
    setMonitorRuns(nextMonitorId ? await listMonitorRuns(nextMonitorId) : []);
  }, []);

  const loadDeploymentDetails = useCallback(async (nextDeploymentId: string) => {
    setPredictionLogs(nextDeploymentId ? await listPredictionLogs(nextDeploymentId) : []);
  }, []);

  const refresh = useCallback(async (preferred?: { objective?: string; submission?: string; deployment?: string; monitor?: string }) => {
    setLoading(true);
    setError("");
    try {
      const [nextSummary, nextAssets, nextObjectives, nextDeployments, nextMonitors] = await Promise.all([
        getModelOpsSummary(), listModelAssets(), listObjectives(), listDeployments(), listMonitors()
      ]);
      setSummary(nextSummary); setAssets(nextAssets); setObjectives(nextObjectives); setDeployments(nextDeployments); setMonitors(nextMonitors);
      const nextObjective = preferred?.objective || objectiveId || nextObjectives[0]?.id || "";
      const nextDeployment = preferred?.deployment || deploymentId || nextDeployments[0]?.id || "";
      const nextMonitor = preferred?.monitor || monitorId || nextMonitors[0]?.id || "";
      setObjectiveId(nextObjective); setDeploymentId(nextDeployment); setMonitorId(nextMonitor);
      await Promise.all([
        loadObjectiveDetails(nextObjective, preferred?.submission || submissionId),
        loadDeploymentDetails(nextDeployment),
        loadMonitorDetails(nextMonitor)
      ]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "ModelOps failed to load");
    } finally {
      setLoading(false);
    }
  }, [deploymentId, loadDeploymentDetails, loadMonitorDetails, loadObjectiveDetails, monitorId, objectiveId, submissionId]);

  useEffect(() => { void refresh(); }, []); // Initial lifecycle load only.

  useEffect(() => {
    const fields = selectedObjective?.feature_fields || [];
    setInferenceRows((rows) => rows.map((row) => Object.fromEntries(fields.map((field) => [field, row[field] || ""]))));
  }, [selectedObjective?.id]);

  const act = async (label: string, operation: () => Promise<void>) => {
    setBusy(label); setError(""); setNotice("");
    try { await operation(); setNotice(label); } catch (cause) { setError(cause instanceof Error ? cause.message : `${label} failed`); }
    finally { setBusy(""); }
  };

  const changeObjective = async (next: string) => {
    setObjectiveId(next); setLoading(true); setError("");
    try { await loadObjectiveDetails(next); } catch (cause) { setError(cause instanceof Error ? cause.message : "Objective details failed to load"); }
    finally { setLoading(false); }
  };

  const changeSubmission = async (next: string) => {
    setSubmissionId(next);
    if (!next) return;
    try {
      const [results, nextEligibility] = await Promise.all([listCheckResults(next), getReleaseEligibility(next)]);
      setCheckResults(results); setEligibility(nextEligibility);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Submission evidence failed to load"); }
  };

  return (
    <Page title="ModelOps" subtitle="Train, evaluate, release, deploy, monitor, and query deterministic models through governed lifecycle controls.">
      <div className="modelops-topbar">
        <label><span>Objective</span><select aria-label="Selected objective" value={objectiveId} onChange={(event) => void changeObjective(event.target.value)}><option value="">Choose objective</option>{objectives.map((item) => <option key={item.id} value={item.id}>{item.display_name}</option>)}</select></label>
        <label><span>Submission</span><select aria-label="Selected submission" value={submissionId} onChange={(event) => void changeSubmission(event.target.value)}><option value="">Choose submission</option>{submissions.map((item) => <option key={item.id} value={item.id}>{item.algorithm} · {item.status}</option>)}</select></label>
        <label><span>Deployment</span><select aria-label="Selected deployment" value={deploymentId} onChange={(event) => { setDeploymentId(event.target.value); void loadDeploymentDetails(event.target.value); }}><option value="">Choose deployment</option>{deployments.map((item) => <option key={item.id} value={item.id}>{item.id} · {item.mode}</option>)}</select></label>
        <button aria-label="Refresh ModelOps" title="Refresh" onClick={() => void refresh()}><RefreshCw size={15} /></button>
      </div>
      <ErrorBanner message={error} />
      {notice ? <div className="inline-success" role="status">{notice}</div> : null}
      <div className="modelops-metrics metrics grid">
        <Metric label="Objectives" value={summary?.objectives || 0} />
        <Metric label="Submissions" value={summary?.submissions || 0} />
        <Metric label="Deployments" value={summary?.deployments || 0} />
        <Metric label="Monitors" value={summary?.monitors || 0} />
        <Metric label="Prediction logs" value={summary?.prediction_logs || 0} />
      </div>
      <nav className="modelops-tabs" aria-label="ModelOps lifecycle">{TABS.map((item) => <button key={item.id} className={tab === item.id ? "active" : ""} onClick={() => setTab(item.id)}>{item.label}</button>)}</nav>
      {loading ? <LoadingState label="Loading model lifecycle evidence..." /> : null}
      {!loading && tab === "objectives" ? <ObjectivesTab assets={assets} objectives={objectives} selectedId={objectiveId} busy={busy} onSelect={(id) => void changeObjective(id)} onCreate={(body) => void act("Objective created", async () => { const created = await createObjective(body); await refresh({ objective: created.id }); })} /> : null}
      {!loading && tab === "training" ? <TrainingTab assets={assets} objective={selectedObjective} submissions={submissions} selectedId={submissionId} busy={busy} onSelect={(id) => void changeSubmission(id)} onTrain={(body) => void act("Training completed", async () => { if (!objectiveId) return; const created = await trainObjective(objectiveId, body); await refresh({ objective: objectiveId, submission: created.id }); })} /> : null}
      {!loading && tab === "gates" ? <GatesTab submission={selectedSubmission} checks={checks} results={checkResults} eligibility={eligibility} busy={busy} onCreate={(body) => void act("Evaluation gate created", async () => { await createCheck(objectiveId, body); await refresh({ objective: objectiveId, submission: submissionId }); })} onEvaluate={() => void act("Evaluation gates executed", async () => { await evaluateChecks(submissionId); await refresh({ objective: objectiveId, submission: submissionId }); })} onDecide={(checkId, status) => void act(`Manual gate ${status}`, async () => { await decideCheck(submissionId, checkId, status); await refresh({ objective: objectiveId, submission: submissionId }); })} /> : null}
      {!loading && tab === "releases" ? <ReleasesTab objective={selectedObjective} submission={selectedSubmission} releases={releases} deployments={deployments.filter((item) => !objectiveId || item.objective_id === objectiveId)} busy={busy} onRelease={(version, environment) => void act("Release created", async () => { await releaseSubmission(objectiveId, submissionId); await createRelease(objectiveId, { submission_id: submissionId, version, environment, notes: "Published from React ModelOps" }); await refresh({ objective: objectiveId, submission: submissionId }); })} onPromote={(releaseId) => void act("Release promoted to production", async () => { await promoteRelease(releaseId); await refresh({ objective: objectiveId, submission: submissionId }); })} onDeploy={(mode) => void act("Deployment started", async () => { const created = await createDeployment({ objective_id: objectiveId, submission_id: submissionId, mode }); await refresh({ objective: objectiveId, submission: submissionId, deployment: created.id }); })} /> : null}
      {!loading && tab === "monitoring" ? <MonitoringTab assets={assets} objective={selectedObjective} deployments={deployments.filter((item) => !objectiveId || item.objective_id === objectiveId)} monitors={monitors.filter((item) => !objectiveId || item.objective_id === objectiveId)} monitorId={monitorId} selectedRun={selectedRun} runs={monitorRuns} busy={busy} onSelect={(id) => { setMonitorId(id); void loadMonitorDetails(id); }} onCreate={(body) => void act("Monitor created", async () => { const created = await createMonitor(body); await refresh({ objective: objectiveId, submission: submissionId, deployment: deploymentId, monitor: created.id }); })} onRun={(currentAssetId) => void act("Monitor run completed", async () => { await runMonitor(monitorId, currentAssetId); await refresh({ objective: objectiveId, submission: submissionId, deployment: deploymentId, monitor: monitorId }); })} /> : null}
      {!loading && tab === "inference" ? <InferenceTab objective={selectedObjective} deployment={selectedDeployment} rows={inferenceRows} setRows={setInferenceRows} result={inferenceResult} logs={predictionLogs} busy={busy} onRun={() => void act("Inference completed", async () => { if (!deploymentId) return; const records = inferenceRows.map((row) => Object.fromEntries(Object.entries(row).map(([field, value]) => [field, inferValue(value)])) as JsonObject); const result = await runInference(deploymentId, records); setInferenceResult(result); await loadDeploymentDetails(deploymentId); })} /> : null}
    </Page>
  );
}

function ObjectivesTab({ assets, objectives, selectedId, busy, onSelect, onCreate }: { assets: DataAssetSummary[]; objectives: ModelObjective[]; selectedId: string; busy: string; onSelect: (id: string) => void; onCreate: (body: { display_name: string; description?: string; problem_type: "classification" | "regression"; target_field: string; feature_fields: string[]; input_asset_id?: string }) => void }) {
  const [name, setName] = useState("Asset Risk Objective"); const [description, setDescription] = useState("Predict operational asset risk from governed features."); const [problem, setProblem] = useState<"classification" | "regression">("regression"); const [target, setTarget] = useState("risk_score"); const [features, setFeatures] = useState("temperature, pressure"); const [asset, setAsset] = useState("");
  return <div className="modelops-layout"><Panel title="Modeling Objectives" action={<Beaker size={16} />}><div className="modelops-resource-list">{objectives.map((item) => <button key={item.id} className={item.id === selectedId ? "selected" : ""} onClick={() => onSelect(item.id)}><span><strong>{item.display_name}</strong><small>{item.target_field} from {item.feature_fields.join(", ")}</small></span><StatusBadge value={item.problem_type} /></button>)}</div>{!objectives.length ? <EmptyState title="No objectives yet" description="Define what the model should predict and which governed dataset provides its features." /> : null}</Panel><Panel title="New Objective"><div className="form-grid"><label><span>Name</span><input aria-label="Objective name" value={name} onChange={(event) => setName(event.target.value)} /></label><label><span>Problem</span><select aria-label="Problem type" value={problem} onChange={(event) => setProblem(event.target.value as typeof problem)}><option value="regression">Regression</option><option value="classification">Classification</option></select></label><label className="span-2"><span>Description</span><input aria-label="Objective description" value={description} onChange={(event) => setDescription(event.target.value)} /></label><label><span>Target field</span><input aria-label="Target field" value={target} onChange={(event) => setTarget(event.target.value)} /></label><label><span>Feature fields</span><input aria-label="Feature fields" value={features} onChange={(event) => setFeatures(event.target.value)} /></label><label className="span-2"><span>Input dataset</span><select aria-label="Objective input dataset" value={asset} onChange={(event) => setAsset(event.target.value)}><option value="">No dataset selected</option>{assets.map((item) => <option key={item.id} value={item.id}>{item.display_name}</option>)}</select></label></div><button className="primary" disabled={!!busy || !name.trim() || !target.trim() || !splitFields(features).length} onClick={() => onCreate({ display_name: name, description, problem_type: problem, target_field: target, feature_fields: splitFields(features), input_asset_id: asset || undefined })}><Plus size={15} />Create objective</button></Panel></div>;
}

function TrainingTab({ assets, objective, submissions, selectedId, busy, onSelect, onTrain }: { assets: DataAssetSummary[]; objective: ModelObjective | null; submissions: ModelSubmission[]; selectedId: string; busy: string; onSelect: (id: string) => void; onTrain: (body: { trainer_type: string; algorithm?: string; training_dataset_id?: string; target_column?: string; eval_metric?: string; quality_preset?: string }) => void }) {
  const [trainer, setTrainer] = useState("regression"); const [algorithm, setAlgorithm] = useState("deterministic-linear"); const [asset, setAsset] = useState(""); const [metric, setMetric] = useState("mae"); const [preset, setPreset] = useState("balanced");
  useEffect(() => { if (objective) { setTrainer(objective.problem_type); setAsset(objective.input_asset_id || ""); } }, [objective?.id]);
  return <div className="modelops-layout"><Panel title="Training & Submissions" action={<Activity size={16} />}><div className="modelops-resource-list">{submissions.map((item) => <button key={item.id} className={item.id === selectedId ? "selected" : ""} onClick={() => onSelect(item.id)}><span><strong>{item.algorithm}</strong><small>{item.trainer_type || objective?.problem_type} · {formatTime(item.created_at)}</small></span><StatusBadge value={item.released ? "released" : item.status} /></button>)}</div>{!submissions.length ? <EmptyState title="No trained submissions" description="Choose an objective and run deterministic training." /> : null}</Panel><Panel title="Train Submission"><div className="form-grid"><label><span>Trainer</span><select aria-label="Trainer type" value={trainer} onChange={(event) => setTrainer(event.target.value)}><option value="regression">Regression</option><option value="classification">Classification</option><option value="forecasting">Forecasting</option></select></label><label><span>Algorithm</span><input aria-label="Algorithm" value={algorithm} onChange={(event) => setAlgorithm(event.target.value)} /></label><label className="span-2"><span>Training dataset</span><select aria-label="Training dataset" value={asset} onChange={(event) => setAsset(event.target.value)}><option value="">Choose dataset</option>{assets.map((item) => <option key={item.id} value={item.id}>{item.display_name}</option>)}</select></label><label><span>Evaluation metric</span><input aria-label="Evaluation metric" value={metric} onChange={(event) => setMetric(event.target.value)} /></label><label><span>Quality preset</span><select aria-label="Quality preset" value={preset} onChange={(event) => setPreset(event.target.value)}><option value="fast">Fast</option><option value="balanced">Balanced</option><option value="quality">Quality</option></select></label></div><button className="primary" disabled={!!busy || !objective} onClick={() => onTrain({ trainer_type: trainer, algorithm, training_dataset_id: asset || objective?.input_asset_id || undefined, target_column: objective?.target_field, eval_metric: metric, quality_preset: preset })}><Play size={15} />Train model</button>{submissions.find((item) => item.id === selectedId) ? <div className="model-metric-evidence"><h3>Submission metrics</h3><KeyValueGrid data={submissions.find((item) => item.id === selectedId)?.metrics || {}} /></div> : null}</Panel></div>;
}

function GatesTab({ submission, checks, results, eligibility, busy, onCreate, onEvaluate, onDecide }: { submission: ModelSubmission | null; checks: ModelCheck[]; results: ModelCheckResult[]; eligibility: ReleaseEligibility | null; busy: string; onCreate: (body: { name: string; check_type: string; metric?: string; operator?: string; threshold?: number }) => void; onEvaluate: () => void; onDecide: (checkId: string, status: "approved" | "rejected") => void }) {
  const [name, setName] = useState("mae_gate"); const [type, setType] = useState("automatic"); const [metric, setMetric] = useState("mae"); const [operator, setOperator] = useState("<="); const [threshold, setThreshold] = useState(10);
  const resultByCheck = Object.fromEntries(results.map((item) => [item.check_id, item]));
  return <div className="modelops-layout"><Panel title="Release Eligibility" action={<StatusBadge value={eligibility?.eligible ? "eligible" : "blocked"} />}><div className="modelops-gate-list">{checks.map((check) => { const result = resultByCheck[check.id]; return <article key={check.id}><header><div><strong>{check.name}</strong><small>{check.check_type}{check.metric ? ` · ${check.metric} ${check.operator} ${check.threshold}` : ""}</small></div><StatusBadge value={result?.status || "not evaluated"} /></header>{check.check_type === "manual" ? <div className="button-row"><button disabled={!submission || !!busy} onClick={() => onDecide(check.id, "approved")}><Check size={14} />Approve</button><button disabled={!submission || !!busy} onClick={() => onDecide(check.id, "rejected")}><X size={14} />Reject</button></div> : null}</article>; })}</div>{!checks.length ? <EmptyState title="No evaluation gates" description="Add automatic metric thresholds or a manual review requirement." /> : null}<button className="primary" disabled={!submission || !checks.length || !!busy} onClick={onEvaluate}><ShieldCheck size={15} />Evaluate all gates</button></Panel><Panel title="Add Evaluation Gate"><div className="form-grid"><label><span>Name</span><input aria-label="Gate name" value={name} onChange={(event) => setName(event.target.value)} /></label><label><span>Type</span><select aria-label="Gate type" value={type} onChange={(event) => setType(event.target.value)}><option value="automatic">Automatic</option><option value="manual">Manual</option></select></label>{type === "automatic" ? <><label><span>Metric</span><input aria-label="Gate metric" value={metric} onChange={(event) => setMetric(event.target.value)} /></label><label><span>Condition</span><div className="inline-inputs"><select aria-label="Gate operator" value={operator} onChange={(event) => setOperator(event.target.value)}>{["<=", "<", ">=", ">", "==", "!="].map((item) => <option key={item}>{item}</option>)}</select><input aria-label="Gate threshold" type="number" value={threshold} onChange={(event) => setThreshold(Number(event.target.value))} /></div></label></> : null}</div><button disabled={!submission || !!busy || !name.trim()} onClick={() => onCreate({ name, check_type: type, ...(type === "automatic" ? { metric, operator, threshold } : {}) })}><Plus size={15} />Add gate</button></Panel></div>;
}

function ReleasesTab({ objective, submission, releases, deployments, busy, onRelease, onPromote, onDeploy }: { objective: ModelObjective | null; submission: ModelSubmission | null; releases: ModelRelease[]; deployments: ModelDeployment[]; busy: string; onRelease: (version: string, environment: string) => void; onPromote: (id: string) => void; onDeploy: (mode: string) => void }) {
  const [version, setVersion] = useState("v1.0"); const [environment, setEnvironment] = useState("staging"); const [mode, setMode] = useState("live");
  return <div className="modelops-layout"><Panel title="Releases"><div className="modelops-resource-list">{releases.map((item) => <article className="modelops-release-row" key={item.id}><span><strong>{item.version}</strong><small>{item.submission_id} · {formatTime(item.created_at)}</small></span><StatusBadge value={item.environment} />{item.environment !== "production" ? <button disabled={!!busy} onClick={() => onPromote(item.id)}>Promote</button> : null}</article>)}</div>{!releases.length ? <EmptyState title="No releases" description="A submission must pass its gates before it is published." /> : null}</Panel><Panel title="Publish and Deploy"><div className="form-grid"><label><span>Version</span><input aria-label="Release version" value={version} onChange={(event) => setVersion(event.target.value)} /></label><label><span>Environment</span><select aria-label="Release environment" value={environment} onChange={(event) => setEnvironment(event.target.value)}><option value="staging">Staging</option><option value="production">Production</option></select></label></div><button className="primary" disabled={!objective || !submission || !!busy || eligibilityBlocked(submission)} onClick={() => onRelease(version, environment)}><Rocket size={15} />Create release</button><hr /><label className="stacked-field"><span>Deployment mode</span><select aria-label="Deployment mode" value={mode} onChange={(event) => setMode(event.target.value)}><option value="live">Live</option><option value="batch">Batch</option></select></label><button disabled={!submission?.released || !!busy} onClick={() => onDeploy(mode)}><Play size={15} />Start deployment</button><div className="modelops-deployment-list">{deployments.map((item) => <article key={item.id}><span><strong>{item.id}</strong><small>{item.mode} · {item.submission_id}</small></span><StatusBadge value={item.status} /></article>)}</div></Panel></div>;
}

function eligibilityBlocked(submission: ModelSubmission): boolean { return submission.status !== "success"; }

function MonitoringTab({ assets, objective, deployments, monitors, monitorId, selectedRun, runs, busy, onSelect, onCreate, onRun }: { assets: DataAssetSummary[]; objective: ModelObjective | null; deployments: ModelDeployment[]; monitors: ModelMonitor[]; monitorId: string; selectedRun: MonitorRun | null; runs: MonitorRun[]; busy: string; onSelect: (id: string) => void; onCreate: (body: { display_name: string; objective_id: string; deployment_id?: string; baseline_asset_id: string; feature_fields: string[]; prediction_field: string; target_field?: string; thresholds: JsonObject }) => void; onRun: (assetId: string) => void }) {
  const [name, setName] = useState("Deployment Drift Monitor"); const [deployment, setDeployment] = useState(""); const [baseline, setBaseline] = useState(""); const [current, setCurrent] = useState(""); const [fields, setFields] = useState(""); const [warn, setWarn] = useState(0.2); const [fail, setFail] = useState(0.5);
  useEffect(() => { if (objective) setFields(objective.feature_fields.join(", ")); }, [objective?.id]);
  const driftRows = Object.entries(selectedRun?.drift_metrics || {}).map(([field, metric]) => ({ field, type: metric.type, status: metric.status, mean_shift: metric.mean_shift_ratio ?? "n/a", missing_delta: metric.missing_rate_delta, unseen_categories: metric.unseen_category_rate ?? "n/a", frequency_shift: metric.frequency_shift ?? "n/a" }));
  return <><div className="modelops-layout"><Panel title="Monitors" action={<Gauge size={16} />}><div className="modelops-resource-list">{monitors.map((item) => <button key={item.id} className={item.id === monitorId ? "selected" : ""} onClick={() => onSelect(item.id)}><span><strong>{item.display_name}</strong><small>{item.feature_fields.join(", ")} · baseline {item.baseline_asset_id}</small></span><StatusBadge value={item.latest_run?.status || "not run"} /></button>)}</div>{!monitors.length ? <EmptyState title="No monitors" description="Bind a baseline dataset to a deployed model and define drift thresholds." /> : null}</Panel><Panel title="Configure Monitor"><div className="form-grid"><label className="span-2"><span>Name</span><input aria-label="Monitor name" value={name} onChange={(event) => setName(event.target.value)} /></label><label><span>Deployment</span><select aria-label="Monitor deployment" value={deployment} onChange={(event) => setDeployment(event.target.value)}><option value="">Optional</option>{deployments.map((item) => <option key={item.id} value={item.id}>{item.id}</option>)}</select></label><label><span>Baseline dataset</span><select aria-label="Baseline dataset" value={baseline} onChange={(event) => setBaseline(event.target.value)}><option value="">Choose baseline</option>{assets.map((item) => <option key={item.id} value={item.id}>{item.display_name}</option>)}</select></label><label className="span-2"><span>Watched features</span><input aria-label="Monitor feature fields" value={fields} onChange={(event) => setFields(event.target.value)} /></label><label><span>Warn shift</span><input aria-label="Drift warning threshold" type="number" step="0.05" value={warn} onChange={(event) => setWarn(Number(event.target.value))} /></label><label><span>Fail shift</span><input aria-label="Drift failure threshold" type="number" step="0.05" value={fail} onChange={(event) => setFail(Number(event.target.value))} /></label></div><button disabled={!objective || !baseline || !splitFields(fields).length || !!busy} onClick={() => onCreate({ display_name: name, objective_id: objective?.id || "", deployment_id: deployment || undefined, baseline_asset_id: baseline, feature_fields: splitFields(fields), prediction_field: "prediction", target_field: objective?.target_field, thresholds: { numeric_mean_shift_warn: warn, numeric_mean_shift_fail: fail, unseen_category_rate_warn: warn, unseen_category_rate_fail: fail, frequency_shift_warn: warn, frequency_shift_fail: fail } })}><Plus size={15} />Create monitor</button><hr /><label className="stacked-field"><span>Current dataset</span><select aria-label="Current monitor dataset" value={current} onChange={(event) => setCurrent(event.target.value)}><option value="">Choose current data</option>{assets.map((item) => <option key={item.id} value={item.id}>{item.display_name}</option>)}</select></label><button className="primary" disabled={!monitorId || !current || !!busy} onClick={() => onRun(current)}><Activity size={15} />Run drift check</button></Panel></div>{selectedRun ? <div className="modelops-monitor-evidence"><Panel title="Latest Drift Evidence" action={<StatusBadge value={selectedRun.status} />}><DataTable rows={driftRows} empty="No feature drift metrics" /></Panel><Panel title="Quality & Alerts"><KeyValueGrid data={selectedRun.quality_metrics} /><div className="modelops-alert-list">{selectedRun.alerts.map((alert, index) => <article key={index}><StatusBadge value={String(alert.status || "WARN")} /><span>{String(alert.message || "Monitor threshold exceeded")}</span></article>)}</div>{!selectedRun.alerts.length ? <div className="empty">No alerts for this run.</div> : null}</Panel><Panel title="Run History"><div className="modelops-run-history">{runs.map((run) => <div key={run.id}><StatusBadge value={run.status} /><span>{run.current_asset_id}</span><time>{formatTime(run.created_at)}</time></div>)}</div></Panel></div> : null}</>;
}

function InferenceTab({ objective, deployment, rows, setRows, result, logs, busy, onRun }: { objective: ModelObjective | null; deployment: ModelDeployment | null; rows: Array<Record<string, string>>; setRows: React.Dispatch<React.SetStateAction<Array<Record<string, string>>>>; result: InferenceResponse | null; logs: PredictionLog[]; busy: string; onRun: () => void }) {
  const fields = objective?.feature_fields || [];
  const outputRows: TableRow[] = (result?.output_data || result?.predictions?.map((prediction) => ({ prediction })) || []) as TableRow[];
  return <div className="modelops-inference-layout"><Panel title="Inference Input" action={<StatusBadge value={deployment?.status || "no deployment"} />}><p className="panel-description">Enter governed feature values. Numeric and boolean values are typed automatically.</p><div className="inference-records">{rows.map((row, index) => <article key={index}><header><strong>Record {index + 1}</strong><button aria-label={`Remove inference record ${index + 1}`} disabled={rows.length === 1} onClick={() => setRows((items) => items.filter((_, itemIndex) => itemIndex !== index))}><Trash2 size={14} /></button></header><div className="form-grid">{fields.map((field) => <label key={field}><span>{field}</span><input aria-label={`Record ${index + 1} ${field}`} value={row[field] || ""} onChange={(event) => setRows((items) => items.map((item, itemIndex) => itemIndex === index ? { ...item, [field]: event.target.value } : item))} /></label>)}</div></article>)}</div><div className="button-row"><button onClick={() => setRows((items) => [...items, Object.fromEntries(fields.map((field) => [field, ""]))])}><Plus size={14} />Add record</button><button className="primary" disabled={!deployment || !fields.length || !!busy} onClick={onRun}><Play size={14} />Run inference</button></div></Panel><Panel title="Predictions"><DataTable rows={outputRows} empty="Run inference to see predictions." /></Panel><Panel title="Prediction Evidence"><div className="modelops-run-history">{logs.map((log) => <div key={log.id}><StatusBadge value={log.request_shape} /><span>{log.output_count} predictions</span><time>{formatTime(log.created_at)}</time></div>)}</div>{!logs.length ? <EmptyState title="No prediction logs" description="Every successful deployment query creates a compact, auditable summary." /> : null}</Panel></div>;
}
