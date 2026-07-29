import { api, postJson } from "../api";
import type { JsonObject } from "../types";

export interface OntologyHealthFinding {
  id: string;
  code: string;
  severity: "ERROR" | "WARN" | "INFO";
  category: string;
  resource_type: string;
  resource_id: string;
  object_type_id?: string | null;
  title: string;
  detail: string;
  recommendation: string;
  count: number;
  target_href: string;
}

export interface OntologyHealthRun {
  id?: string;
  project_id: string;
  object_type_id?: string | null;
  status: string;
  score?: number | null;
  summary: { findings?: number; errors?: number; warnings?: number; info?: number };
  metrics: Record<string, number>;
  findings: OntologyHealthFinding[];
  created_by?: string;
  created_at?: number | null;
}

export interface OntologyHealthUiState {
  summary: { status: string; score?: number | null; findings?: number; errors?: number; warnings?: number; info?: number };
  primary_actions: Array<{ id: string; label: string; method: string; path: string }>;
  sections: { metrics: Record<string, number>; findings: OntologyHealthFinding[]; latest_run: OntologyHealthRun };
  evidence_links: Array<{ label: string; href: string; kind: string }>;
  warnings: OntologyHealthFinding[];
  permissions: string[];
  last_updated?: number | null;
}

export interface OntologyPolicyDecision {
  decision: string;
  allowed: boolean;
  matched_rule_ids: string[];
  masks: string[];
  row_filter: JsonObject;
  approval: JsonObject;
  explanation: string;
}

export function getOntologyHealthUiState(objectTypeId: string, projectId = "default"): Promise<OntologyHealthUiState> {
  return api(`/ui-state/ontology/health?project_id=${encodeURIComponent(projectId)}&object_type_id=${encodeURIComponent(objectTypeId)}`);
}

export function runOntologyHealth(objectTypeId: string, projectId = "default"): Promise<OntologyHealthRun> {
  return postJson("/ontology/health/run", { project_id: projectId, object_type_id: objectTypeId });
}

export function generateStandardObjectView(objectTypeId: string, replace = false): Promise<{ created: boolean; view_id: string; published_version_id?: string | null }> {
  return postJson(`/ontology/object-types/${encodeURIComponent(objectTypeId)}/generate-standard-view`, { replace, publish: true });
}

export function simulateOntologyPolicy(objectTypeId: string, input: {
  principal: string;
  action: string;
  purpose?: string;
  effect: "ALLOW" | "DENY" | "MASK" | "ROW_FILTER" | "REQUIRE_APPROVAL";
  maskProperties?: string[];
}): Promise<{ object_type_id: string; persisted: false; decision: OntologyPolicyDecision; hypothetical_rule_count: number }> {
  return postJson(`/ontology/object-types/${encodeURIComponent(objectTypeId)}/policies/simulate`, {
    principal: input.principal,
    action: input.action,
    purpose: input.purpose || undefined,
    hypothetical_rules: [{
      display_name: `Simulation ${input.effect}`,
      effect: input.effect,
      principal: input.principal,
      action: input.action,
      resource_kind: "object_type",
      object_type_id: objectTypeId,
      mask_properties: input.maskProperties || [],
      approval: input.effect === "REQUIRE_APPROVAL" ? { reason: "Simulated approval policy" } : {},
      priority: 1
    }]
  });
}
