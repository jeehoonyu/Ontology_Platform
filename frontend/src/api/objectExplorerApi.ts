import { api, postJson } from "../api";
import type { JsonObject } from "../types";

export type Primitive = string | number | boolean | null;
export type ObjectRecord = {
  id: string;
  object_type_id?: string;
  properties: JsonObject;
  lineage?: JsonObject;
  updated_at?: number;
};

export type ObjectTypeSummary = {
  id: string;
  project_id: string;
  display_name: string;
  description?: string | null;
  properties: JsonObject;
};

export type FacetBucket = { value?: Primitive; label?: string; count: number; range?: [number, number] };
export type ExplorerFacet = { field: string; type: "histogram" | "listogram"; buckets: FacetBucket[] };
export type ExplorerAction = { id: string; display_name: string; description?: string | null; parameters: JsonObject };
export type ExplorerQuery = {
  object_type_id: string;
  filters: Record<string, unknown>;
  result_count: number;
  objects: ObjectRecord[];
  columns: string[];
  facets: ExplorerFacet[];
  selected_objects: ObjectProfile[];
  available_actions: ExplorerAction[];
  object_type?: ObjectTypeSummary | null;
};

export type ObjectProfile = {
  object: ObjectRecord;
  object_type: ObjectTypeSummary;
  inbound_links: Record<string, unknown>[];
  outbound_links: Record<string, unknown>[];
  linked_objects: ObjectRecord[];
  metrics: JsonObject;
};

export type Exploration = {
  id: string;
  project_id: string;
  display_name: string;
  description?: string | null;
  object_type_id: string;
  filters: Record<string, unknown>;
  columns: string[];
  charts: Record<string, unknown>[];
  perspective: Record<string, unknown>;
  owner: string;
  created_at: number;
  updated_at: number;
};

export type RiskFinding = { object_id: string; risk: { score: number; band: string; drivers?: Record<string, unknown>[]; explanation?: string } };
export type ActionResult = { status: string; message: string; approval_request_id?: string | null; mutated_object_ids: string[] };

export const listObjectTypes = () => api<ObjectTypeSummary[]>("/object-types");
export const listExplorations = () => api<Exploration[]>("/object-explorer/explorations");
export const queryObjects = (body: {
  object_type_id: string;
  query?: string;
  filters?: Record<string, unknown>;
  columns?: string[];
  chart_fields?: string[];
  selected_ids?: string[];
  limit?: number;
}) => postJson<ExplorerQuery>("/object-explorer/query", body);
export const getObjectProfile = (typeId: string, objectId: string) =>
  api<ObjectProfile>(`/objects/${encodeURIComponent(typeId)}/${encodeURIComponent(objectId)}/profile`);
export const evaluateRisk = (objectTypeId: string, objectIds: string[]) => postJson<{ findings: RiskFinding[] }>("/decision/evaluate", {
  object_type_id: objectTypeId,
  object_ids: objectIds,
  limit: objectIds.length,
  persist_run: false
});
export const saveExploration = (body: Omit<Exploration, "id" | "created_at" | "updated_at"> & { id?: string }) =>
  postJson<Exploration>("/object-explorer/explorations", body);
export const executeExplorerAction = (actionTypeId: string, parameters: Record<string, unknown>) =>
  postJson<ActionResult>("/actions/execute", {
    action_type_id: actionTypeId,
    parameters,
    actor: "object-explorer-ui",
    idempotency_key: `object-explorer-${actionTypeId}-${Date.now()}`
  });
