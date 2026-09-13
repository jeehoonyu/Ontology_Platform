import { api, postJson } from "../api";
import type { JsonObject } from "../types";
import type { ObjectRecord } from "./objectExplorerApi";

export type DecisionRule = { id: string; project_id: string; display_name: string; object_type_id: string; expression: JsonObject; severity: string; recommended_actions: string[]; active: boolean };
export type DecisionScorecard = { id: string; project_id: string; display_name: string; object_type_id: string; features: Array<{ rule_id?: string; weight?: number; reason?: string }>; thresholds: JsonObject; recommended_actions: string[]; active: boolean };
export type RiskDriver = { feature?: string; rule_id?: string; reason?: string; weight?: number; contribution?: number };
export type RiskResult = { score: number; band: string; drivers: RiskDriver[]; recommended_actions: string[]; explanation: string };
export type DecisionFinding = { object: ObjectRecord; object_id: string; object_type_id: string; rule_results: Array<{ rule_id?: string; matched?: boolean; severity?: string }>; risk: RiskResult };
// `object_count`, `band_counts`, `high_risk_count` and `average_score` describe every
// object scored; `findings` holds only the highest-risk ones kept, and
// `objects_in_scope` counts the scope the scan was cut from.
export type DecisionEvaluation = { id: string; project_id: string; status: string; object_count: number; objects_in_scope: number; scan_limit: number; band_counts: Record<string, number>; high_risk_count: number; average_score: number; findings: DecisionFinding[]; findings_retained: number; finding_order: "score_desc" | "id_asc"; unlisted_max_score: number | null; created_at: number; completed_at: number };
// `duplicate_warnings` lists at most five; `duplicate_warning_count` counts them all, and
// `duplicate_coverage` says whether the latest entity-resolution job compared the object.
export type DecisionExplanation = { object: ObjectRecord; risk: RiskResult; explanation: string; recommended_actions: string[]; duplicate_warnings: Array<Record<string, unknown>>; duplicate_warning_count?: number; duplicate_coverage?: { job_id: string; compared: boolean; objects_scanned: number | null; objects_in_scope: number | null } | null; temporal_summary: JsonObject };
export type ObjectSnapshot = { id: string; project_id: string; object_id: string; object_type_id: string; properties: JsonObject; lineage: JsonObject; event_type: string; actor: string; source_type?: string | null; source_id?: string | null; created_at: number; seq: number };
export type EntityCandidate = { id: string; project_id: string; job_id: string; object_type_id: string; object_ids: string[]; score: number; reasons: Array<Record<string, unknown>>; status: string; merged_object_id?: string | null; objects?: ObjectRecord[] };
// A job compares every pair among the first `objects_scanned` objects of its type by id,
// out of `objects_in_scope`. Both are null on a job that ran before they were kept.
export type EntityJob = { id: string; project_id: string; object_type_id: string; fields: string[]; status: string; candidate_count: number; objects_in_scope: number | null; objects_scanned: number | null; last_scanned_id: string | null; scan_order?: string; scan_limit?: number; candidates: EntityCandidate[] };
export type DecisionScenario = { id: string; project_id: string; display_name: string; seed_object_ids: string[]; baseline: Record<string, JsonObject>; scenario_output: Record<string, JsonObject>; impact: { changed_object_count: number; changed_object_ids: string[]; by_object: Record<string, JsonObject> }; created_at: number; updated_at: number };

export const bootstrapDecision = (projectId: string, objectTypeId: string) => postJson<{ project_id: string; object_type_id: string; created: string[] }>("/decision/bootstrap", { project_id: projectId, object_type_id: objectTypeId });
export const listDecisionRules = (projectId: string, objectTypeId: string) => api<DecisionRule[]>(`/decision/rules?project_id=${encodeURIComponent(projectId)}&object_type_id=${encodeURIComponent(objectTypeId)}`);
export const listDecisionScorecards = (projectId: string, objectTypeId: string) => api<DecisionScorecard[]>(`/decision/scorecards?project_id=${encodeURIComponent(projectId)}&object_type_id=${encodeURIComponent(objectTypeId)}`);
// Scores the whole scope up to the server's ceiling and keeps the 250 highest-risk
// findings. It asked for `limit: 250`, which scored the first 250 objects by id and
// nothing else, while the board and its metrics read as the whole type.
export const evaluateDecision = (projectId: string, objectTypeId: string) => postJson<DecisionEvaluation>("/decision/evaluate", { project_id: projectId, object_type_id: objectTypeId, filters: {}, limit: 10000, finding_limit: 250, persist_run: true });
export const explainDecisionObject = (objectTypeId: string, objectId: string) => api<DecisionExplanation>(`/decision/objects/${encodeURIComponent(objectTypeId)}/${encodeURIComponent(objectId)}/explain`);
export const getObjectTimeline = (objectTypeId: string, objectId: string) => api<{ timeline: ObjectSnapshot[] }>(`/temporal/objects/${encodeURIComponent(objectTypeId)}/${encodeURIComponent(objectId)}/timeline`);
export const createEntityJob = (projectId: string, objectTypeId: string, fields: string[], threshold: number) => postJson<EntityJob>("/entity-resolution/jobs", { project_id: projectId, object_type_id: objectTypeId, fields, threshold, limit: 1000 });
export const acceptEntityCandidate = (candidateId: string) => postJson<EntityCandidate>(`/entity-resolution/candidates/${encodeURIComponent(candidateId)}/accept`, { actor: "decision-workspace" });
export const rejectEntityCandidate = (candidateId: string) => postJson<EntityCandidate>(`/entity-resolution/candidates/${encodeURIComponent(candidateId)}/reject`, { actor: "decision-workspace", reason: "Rejected after analyst review" });
export const createDecisionScenario = (body: { project_id: string; display_name: string; seed_object_ids: string[]; overrides: Record<string, JsonObject> }) => postJson<DecisionScenario>("/decision/scenarios", { ...body, propagation_rules: [] });
