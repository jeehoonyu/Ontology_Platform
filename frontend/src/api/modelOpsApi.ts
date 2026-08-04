import { api, postJson } from "../api";
import type { JsonObject, JsonValue } from "../types";

export type DataAssetSummary = {
  id: string;
  project_id?: string;
  display_name: string;
  kind: string;
  asset_schema: JsonObject;
  records?: JsonObject[];
};

export type ModelObjective = {
  id: string;
  project_id: string;
  display_name: string;
  description?: string | null;
  problem_type: "classification" | "regression";
  target_field: string;
  feature_fields: string[];
  input_asset_id?: string | null;
  created_at: number;
  updated_at: number;
};

export type ModelSubmission = {
  id: string;
  project_id: string;
  objective_id: string;
  algorithm: string;
  metrics: JsonObject;
  released: boolean;
  status: string;
  trainer_type?: string | null;
  training_dataset_id?: string | null;
  target_column?: string | null;
  eval_metric?: string | null;
  quality_preset?: string | null;
  created_at: number;
};

export type ModelCheck = {
  id: string;
  project_id: string;
  objective_id: string;
  name: string;
  check_type: "manual" | "automatic";
  metric?: string | null;
  operator?: string | null;
  threshold?: number | null;
  created_at: number;
};

export type ModelCheckResult = {
  id: string;
  project_id: string;
  submission_id: string;
  check_id: string;
  status: "pending" | "approved" | "rejected";
  reviewer?: string | null;
  comment?: string | null;
  decided_at?: number | null;
};

export type ReleaseEligibility = { eligible: boolean; reason?: string; checks?: JsonObject[]; summary?: JsonObject };
export type ModelRelease = {
  id: string;
  project_id: string;
  objective_id: string;
  submission_id: string;
  version: string;
  environment: "staging" | "production";
  notes?: string | null;
  created_at: number;
};
export type ModelDeployment = {
  id: string;
  project_id: string;
  objective_id: string;
  submission_id: string;
  mode: "live" | "batch";
  status: string;
  created_at: number;
};

export type DriftMetric = {
  type: string;
  missing_rate_delta: number;
  mean_shift_abs?: number;
  mean_shift_ratio?: number;
  unseen_category_rate?: number;
  frequency_shift?: number;
  status: string;
};
export type MonitorRun = {
  id: string;
  project_id: string;
  monitor_id: string;
  objective_id: string;
  deployment_id?: string | null;
  baseline_asset_id: string;
  current_asset_id: string;
  baseline_profile: JsonObject;
  current_profile: JsonObject;
  drift_metrics: Record<string, DriftMetric>;
  quality_metrics: JsonObject;
  alerts: JsonObject[];
  status: string;
  created_at: number;
};
export type ModelMonitor = {
  id: string;
  project_id: string;
  display_name: string;
  description?: string | null;
  objective_id: string;
  deployment_id?: string | null;
  baseline_asset_id: string;
  feature_fields: string[];
  prediction_field: string;
  target_field?: string | null;
  thresholds: JsonObject;
  enabled: boolean;
  created_at: number;
  updated_at: number;
  latest_run?: MonitorRun | null;
};
export type PredictionLog = {
  id: string;
  project_id: string;
  deployment_id: string;
  objective_id: string;
  submission_id: string;
  request_shape: string;
  input_count: number;
  output_count: number;
  prediction_summary: JsonObject;
  created_at: number;
};
export type ModelOpsSummary = {
  objectives: number;
  submissions: number;
  deployments: number;
  monitors: number;
  prediction_logs: number;
  latest_monitor_status: Record<string, number>;
  latest_runs: MonitorRun[];
};
export type InferenceResponse = { output_data?: Array<Record<string, JsonValue>>; predictions?: JsonValue[] };

export const getModelOpsSummary = () => api<ModelOpsSummary>("/modelops/summary");
export const listModelAssets = () => api<DataAssetSummary[]>("/data-assets");
export const listObjectives = () => api<ModelObjective[]>("/modeling/objectives");
export const createObjective = (body: Pick<ModelObjective, "display_name" | "problem_type" | "target_field" | "feature_fields"> & { description?: string; input_asset_id?: string; project_id?: string }) => postJson<ModelObjective>("/modeling/objectives", body);
export const listSubmissions = (objectiveId: string) => api<ModelSubmission[]>(`/modeling/objectives/${encodeURIComponent(objectiveId)}/submissions`);
export const trainObjective = (objectiveId: string, body: { trainer_type: string; algorithm?: string; training_dataset_id?: string; target_column?: string; eval_metric?: string; quality_preset?: string }) => postJson<ModelSubmission>(`/modeling/objectives/${encodeURIComponent(objectiveId)}/train`, body);
export const releaseSubmission = (objectiveId: string, submissionId: string) => postJson<ModelSubmission>(`/modeling/objectives/${encodeURIComponent(objectiveId)}/release`, { submission_id: submissionId });
export const listChecks = (objectiveId: string) => api<ModelCheck[]>(`/modeling/objectives/${encodeURIComponent(objectiveId)}/checks`);
export const createCheck = (objectiveId: string, body: { name: string; check_type: string; metric?: string; operator?: string; threshold?: number }) => postJson<ModelCheck>(`/modeling/objectives/${encodeURIComponent(objectiveId)}/checks`, body);
export const evaluateChecks = (submissionId: string) => postJson<ModelCheckResult[]>(`/modeling/submissions/${encodeURIComponent(submissionId)}/evaluate-checks`, {});
export const listCheckResults = (submissionId: string) => api<ModelCheckResult[]>(`/modeling/submissions/${encodeURIComponent(submissionId)}/check-results`);
export const decideCheck = (submissionId: string, checkId: string, status: "approved" | "rejected") => postJson<ModelCheckResult>(`/modeling/submissions/${encodeURIComponent(submissionId)}/check-results`, { check_id: checkId, status, reviewer: "modelops-ui", comment: `Reviewed in ModelOps: ${status}` });
export const getReleaseEligibility = (submissionId: string) => api<ReleaseEligibility>(`/modeling/submissions/${encodeURIComponent(submissionId)}/release-eligibility`);
export const listReleases = (objectiveId: string) => api<ModelRelease[]>(`/modeling/objectives/${encodeURIComponent(objectiveId)}/releases`);
export const createRelease = (objectiveId: string, body: { submission_id: string; version: string; environment: string; notes?: string }) => postJson<ModelRelease>(`/modeling/objectives/${encodeURIComponent(objectiveId)}/releases`, body);
export const promoteRelease = (releaseId: string) => postJson<ModelRelease>(`/modeling/releases/${encodeURIComponent(releaseId)}/promote`, {});
export const listDeployments = () => api<ModelDeployment[]>("/modeling/deployments");
export const createDeployment = (body: { id?: string; objective_id: string; submission_id: string; mode: string }) => postJson<ModelDeployment>("/modeling/deployments", body);
export const runInference = (deploymentId: string, records: JsonObject[]) => postJson<InferenceResponse>(`/modeling/deployments/${encodeURIComponent(deploymentId)}/infer`, { inference_data: records });
export const listPredictionLogs = (deploymentId: string) => api<PredictionLog[]>(`/modelops/deployments/${encodeURIComponent(deploymentId)}/prediction-logs`);
export const listMonitors = () => api<ModelMonitor[]>("/modelops/monitors");
export const createMonitor = (body: { display_name: string; project_id?: string; objective_id: string; deployment_id?: string; baseline_asset_id: string; feature_fields: string[]; prediction_field: string; target_field?: string; thresholds: JsonObject }) => postJson<ModelMonitor>("/modelops/monitors", body);
export const runMonitor = (monitorId: string, currentAssetId: string) => postJson<MonitorRun>(`/modelops/monitors/${encodeURIComponent(monitorId)}/run`, { current_asset_id: currentAssetId });
export const listMonitorRuns = (monitorId: string) => api<MonitorRun[]>(`/modelops/monitors/${encodeURIComponent(monitorId)}/runs`);
