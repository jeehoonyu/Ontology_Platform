import { api, postJson } from "../api";
import type { JsonObject } from "../types";

export type OpsEvent = { id: string; source: string; event_type: string; severity: string; status: string; title: string; message?: string | null; subject_type?: string | null; subject_id?: string | null; object_type_id?: string | null; object_id?: string | null; created_at: number };
export type AlertRule = { id: string; display_name: string; source?: string | null; event_type?: string | null; min_severity: string; active: boolean };
export type AlertEvent = { id: string; rule_id: string; event_id: string; source: string; severity: string; status: string; title: string; message?: string | null; subject_type?: string | null; subject_id?: string | null; created_at: number };
export type Incident = { id: string; display_name: string; description?: string | null; severity: string; status: string; owner?: string | null; linked_objects: JsonObject[]; alert_ids: string[]; approval_ids: string[]; runbook_execution_ids: string[]; timeline: JsonObject[]; created_at: number; updated_at: number };
export type Runbook = { id: string; display_name: string; description?: string | null; steps: JsonObject[]; enabled: boolean; updated_at: number };
export type RunbookExecution = { id: string; runbook_id: string; incident_id?: string | null; actor: string; status: string; step_results: JsonObject[]; created_at: number; completed_at?: number | null };
export type OpsNotification = { id: string; severity: string; title: string; message?: string | null; source: string; status: string; created_at: number };
export type OpsSummary = { events: number; open_alerts: number; open_incidents: number; runbooks: number; pending_approvals: number; unread_notifications: number; severity_counts: Record<string, number>; latest_events: OpsEvent[]; latest_alerts: AlertEvent[]; latest_incidents: Incident[] };
export type ReliabilitySummary = { status: string; data_contracts: number; latest_contract_status: Record<string, number>; backfills: number; lineage_impact_runs: number; latest_contract_runs: JsonObject[] };

export const getOpsSummary = () => api<OpsSummary>("/ops/summary");
export const listOpsEvents = () => api<OpsEvent[]>("/ops/events?limit=250");
export const ingestOpsEvent = (body: { source: string; event_type: string; severity: string; title: string; message?: string }) => postJson<OpsEvent>("/ops/events/ingest", body);
export const listAlertRules = () => api<AlertRule[]>("/ops/alert-rules");
export const createAlertRule = (body: { display_name: string; source?: string; event_type?: string; min_severity: string }) => postJson<AlertRule>("/ops/alert-rules", body);
export const evaluateAlerts = () => postJson<{ evaluated_events: number; created_alerts: number; alerts: AlertEvent[] }>("/ops/alerts/evaluate", { limit: 500 });
export const listAlerts = () => api<AlertEvent[]>("/ops/alerts");
export const listIncidents = () => api<Incident[]>("/ops/incidents");
export const createIncident = (body: { display_name: string; description?: string; severity: string; alert_ids?: string[] }) => postJson<Incident>("/ops/incidents", body);
export const updateIncident = (id: string, body: { status?: string; owner?: string }) => api<Incident>(`/ops/incidents/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(body) });
export const listRunbooks = () => api<Runbook[]>("/ops/runbooks");
export const createRunbook = (body: { display_name: string; description?: string; steps: JsonObject[] }) => postJson<Runbook>("/ops/runbooks", body);
export const executeRunbook = (id: string, incidentId?: string) => postJson<RunbookExecution>(`/ops/runbooks/${encodeURIComponent(id)}/execute`, { incident_id: incidentId || null, actor: "ops-workspace", inputs: {} });
export const listInbox = () => api<OpsNotification[]>("/ops/inbox");
export const acknowledgeNotification = (id: string) => postJson<OpsNotification>(`/ops/inbox/${encodeURIComponent(id)}/ack`, {});
export const getReliabilitySummary = () => api<ReliabilitySummary>("/reliability/summary");
