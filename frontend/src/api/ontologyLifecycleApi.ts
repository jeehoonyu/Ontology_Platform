import { api, postJson } from "../api";
import type { JsonObject } from "../types";

export interface OntologyRevisionSummary {
  id: string;
  project_id: string;
  revision: number;
  status: string;
  parent_revision_id?: string | null;
  branch_id?: string | null;
  checksum: string;
  validation: {
    status?: string;
    summary?: JsonObject;
    issues?: Array<{ severity: string; path: string; code: string; message: string }>;
  };
  created_by: string;
  created_at: number;
  published_at?: number | null;
}

export interface OntologyDiffEntry {
  kind: string;
  resource_type: string;
  resource_id: string;
  property_name?: string | null;
  breaking: boolean;
}

export interface OntologyChangeSet {
  id: string;
  project_id: string;
  title: string;
  description?: string | null;
  base_revision_id?: string | null;
  draft_revision_id: string;
  proposal_id?: string | null;
  status: string;
  checksum?: string | null;
  changes: JsonObject[];
  diff: {
    classification?: string;
    summary?: { changes?: number; breaking?: number; non_breaking?: number };
    entries?: OntologyDiffEntry[];
  };
  impact: {
    severity?: string;
    affected_object_types?: string[];
    live_object_counts?: Record<string, number>;
    live_objects?: number;
    requires_approval?: boolean;
  };
  validation: { status?: string; summary?: JsonObject; issues?: Array<{ severity: string; path: string; code: string; message: string }> };
  migration_plan: {
    status?: string;
    blocking_steps?: number;
    preserves_existing_values?: boolean;
    steps?: Array<{ order: number; strategy: string; resource_type: string; resource_id: string; property_name?: string | null; requires_backfill: boolean }>;
  };
  created_by: string;
  reviewer?: string | null;
  created_at: number;
  updated_at: number;
}

export interface OntologyEnvironmentState {
  id: string;
  project_id: string;
  name: string;
  current_revision_id?: string | null;
  previous_revision_id?: string | null;
  updated_by: string;
  updated_at: number;
}

export interface OntologyChangeInput {
  operation: "add_property" | "update_property" | "archive_property";
  object_type_id: string;
  property_name: string;
  spec?: JsonObject;
  patch?: JsonObject;
}

export function captureOntologyRevision(projectId = "default"): Promise<OntologyRevisionSummary> {
  return postJson<OntologyRevisionSummary>("/ontology/revisions/capture", { project_id: projectId });
}

export function listOntologyRevisions(projectId = "default"): Promise<OntologyRevisionSummary[]> {
  return api<OntologyRevisionSummary[]>(`/ontology/revisions?project_id=${encodeURIComponent(projectId)}`);
}

export function listOntologyChangeSets(projectId = "default"): Promise<OntologyChangeSet[]> {
  return api<OntologyChangeSet[]>(`/ontology/change-sets?project_id=${encodeURIComponent(projectId)}`);
}

export function listOntologyEnvironments(projectId = "default"): Promise<OntologyEnvironmentState[]> {
  return api<OntologyEnvironmentState[]>(`/ontology/environments?project_id=${encodeURIComponent(projectId)}`);
}

export function createOntologyChangeSet(input: {
  project_id: string;
  title: string;
  description?: string;
  base_revision_id?: string;
  changes: OntologyChangeInput[];
}): Promise<OntologyChangeSet> {
  return postJson<OntologyChangeSet>("/ontology/change-sets", input);
}

export function validateOntologyChangeSet(changeSetId: string): Promise<OntologyChangeSet> {
  return postJson<OntologyChangeSet>(`/ontology/change-sets/${encodeURIComponent(changeSetId)}/validate`, {});
}

export function decideOntologyChangeSet(changeSetId: string, approve: boolean): Promise<OntologyChangeSet> {
  return postJson<OntologyChangeSet>(`/ontology/change-sets/${encodeURIComponent(changeSetId)}/decision`, { approve });
}

export function publishOntologyChangeSet(changeSetId: string, checksum: string | null | undefined, allowBreaking: boolean): Promise<{ change_set: OntologyChangeSet; revision: OntologyRevisionSummary; environment: OntologyEnvironmentState }> {
  return postJson(`/ontology/change-sets/${encodeURIComponent(changeSetId)}/publish`, {
    environment: "production",
    expected_checksum: checksum || undefined,
    allow_breaking: allowBreaking
  });
}

export function rollbackOntologyEnvironment(projectId: string, revisionId: string): Promise<{ revision: OntologyRevisionSummary; restored_from_revision_id: string }> {
  return postJson("/ontology/environments/production/rollback", { project_id: projectId, revision_id: revisionId });
}
