import { api, postJson } from "../api";
import type { JsonObject } from "../types";

// Rows rendered by DataTable/KeyValueGrid extend TableRow via an index signature
// so plain API objects drop straight into the shared data components.
export interface Automation {
  [key: string]: string | number | boolean | null | JsonObject | undefined;
  id: string;
  display_name: string;
  description?: string | null;
  scope_mode: string;
  enabled: boolean;
  muted: boolean;
  owner: string;
  created_at: number;
  updated_at: number;
  last_evaluated_at?: number | null;
}

export interface AutomationCondition {
  id: string;
  automation_id: string;
  condition_type: string;
  config: JsonObject;
  last_snapshot: JsonObject;
  last_state: JsonObject;
}

export interface AutomationEffect {
  id: string;
  automation_id: string;
  effect_type: string;
  execution_order: number;
  parent_effect_id?: string | null;
  config: JsonObject;
}

export interface AutomationRun {
  id: string;
  status: string;
  manual: boolean;
  condition_result: boolean;
  triggered_object_ids?: string[];
  effect_results?: JsonObject[];
  created_at: number;
  completed_at?: number | null;
}

export interface AutomationActivity {
  id: string;
  event_type: string;
  payload: JsonObject;
  created_at: number;
}

export interface AutomationHistory {
  automation_id: string;
  runs: AutomationRun[];
  activities: AutomationActivity[];
  run_count: number;
  activity_count: number;
}

export interface AutomationRunResult {
  run_id: string;
  status: string;
  condition_result: boolean;
  triggered_object_ids: string[];
  effect_results: JsonObject[];
  batch_count: number;
  dependent_run_ids: string[];
}

export interface CreateAutomationInput {
  display_name: string;
  scope_mode: string;
  enabled: boolean;
  description?: string;
}

export interface AutomationDetail {
  automation: Automation;
  conditions: AutomationCondition[];
  effects: AutomationEffect[];
}

function base(id: string): string {
  return `/automations/${encodeURIComponent(id)}`;
}

export function listAutomations(): Promise<Automation[]> {
  return api<Automation[]>("/automations");
}

export function getAutomation(id: string): Promise<Automation> {
  return api<Automation>(base(id));
}

export function listConditions(id: string): Promise<AutomationCondition[]> {
  return api<AutomationCondition[]>(`${base(id)}/conditions`);
}

export function listEffects(id: string): Promise<AutomationEffect[]> {
  return api<AutomationEffect[]>(`${base(id)}/effects`);
}

export async function getAutomationDetail(id: string): Promise<AutomationDetail> {
  const [automation, conditions, effects] = await Promise.all([
    getAutomation(id),
    listConditions(id),
    listEffects(id)
  ]);
  return { automation, conditions, effects };
}

export function createAutomation(input: CreateAutomationInput): Promise<Automation> {
  return postJson<Automation>("/automations", input);
}

export function runAutomation(id: string): Promise<AutomationRunResult> {
  return postJson<AutomationRunResult>(`${base(id)}/run`, { manual: true });
}

export function pauseAutomation(id: string): Promise<Automation> {
  return postJson<Automation>(`${base(id)}/pause`, {});
}

export function resumeAutomation(id: string): Promise<Automation> {
  return postJson<Automation>(`${base(id)}/resume`, {});
}

export function muteAutomation(id: string): Promise<Automation> {
  return postJson<Automation>(`${base(id)}/mute`, {});
}

export function unmuteAutomation(id: string): Promise<Automation> {
  return postJson<Automation>(`${base(id)}/unmute`, {});
}

export function getAutomationHistory(id: string): Promise<AutomationHistory> {
  return api<AutomationHistory>(`${base(id)}/history`);
}

export function getAutomationActivities(id: string): Promise<AutomationActivity[]> {
  return api<AutomationActivity[]>(`${base(id)}/activities`);
}
