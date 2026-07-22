import { api, postJson } from "../api";

export type ArtifactType = "pipeline" | "ontology" | "workshop" | "aip_logic" | "investigation_graph" | "platform_graph" | "entity_resolution";

export interface ArtifactNodeData {
  [key: string]: unknown;
  label: string;
  description?: string;
  nodeType: string;
  fields?: Array<{ id: string; name: string; value: string; label?: string; type?: string; required?: boolean; options?: string[] }>;
  configurationSchemaVersion?: number;
}

export interface ArtifactState {
  nodes: Array<{ id: string; type?: string; position: { x: number; y: number }; data: ArtifactNodeData }>;
  edges: Array<{ id: string; source: string; target: string; sourceHandle?: string | null; targetHandle?: string | null }>;
  widgets?: Array<Record<string, unknown>>;
  object_types?: Array<Record<string, unknown>>;
}

export interface PlatformArtifact {
  id: string;
  project_id: string;
  artifact_type: ArtifactType;
  display_name: string;
  description?: string | null;
  status: string;
  current_revision: number;
  published_revision?: number | null;
  lock_version: number;
  owner: string;
  metadata: Record<string, unknown>;
  state: ArtifactState;
  layout: Record<string, unknown>;
  validation: { status?: string; errors?: Array<Record<string, unknown>>; warnings?: Array<Record<string, unknown>> };
  validation_targets: Array<{ target_type: string; target_id: string; severity: string; message: string; path: string }>;
  lease?: { holder: string; expires_at: number } | null;
  permissions: string[];
  dirty_revision?: number | null;
  execution?: ArtifactJob | null;
  evidence_links: Array<{ type: string; label: string; href: string }>;
  created_at: number;
  updated_at: number;
}

export interface BuilderPort {
  id: string;
  label: string;
  data_type: string;
}

export interface BuilderCatalogNode {
  type: string;
  label: string;
  category: string;
  description: string;
  inputs: BuilderPort[];
  outputs: BuilderPort[];
  configuration_schema: { type: "object"; properties: Record<string, unknown> };
}

export interface BuilderCatalog {
  artifact_type: ArtifactType;
  categories: string[];
  nodes: BuilderCatalogNode[];
  commands: string[];
  permissions: string[];
  version: number;
}

export interface BuilderCommand {
  command_id?: string;
  command: string;
  payload: Record<string, unknown>;
}

export interface ArtifactJob {
  id: string;
  job_type: string;
  status: string;
  progress: number;
  result: Record<string, unknown>;
  error?: string | null;
}

export interface ArtifactPreview {
  job_id: string;
  status: string;
  artifact_id: string;
  revision: number;
  schema: Array<{ name: string; type: string }>;
  sample_output: Array<{ node_id: string; node_type: string; label: string; status: string }>;
  warnings: Array<{ path?: string; message: string }>;
  metrics: { node_count: number; edge_count: number; sample_count: number; duration_ms: number };
  evidence_links: Array<{ type: string; label: string; href: string }>;
  trace: Array<{ sequence: number; node_id: string; status: string; inputs: Record<string, unknown>; outputs: Record<string, unknown> }>;
}

export interface ArtifactLease {
  artifact_id: string;
  holder: string;
  token: string;
  expires_at: number;
}

export interface ArtifactVersion {
  id: string;
  revision: number;
  author: string;
  message?: string | null;
  published: boolean;
  restored_from_revision?: number | null;
  validation: Record<string, unknown>;
  created_at: number;
}

export function listArtifacts(artifactType: ArtifactType): Promise<PlatformArtifact[]> {
  return api<PlatformArtifact[]>(`/artifacts?artifact_type=${encodeURIComponent(artifactType)}`);
}

export function createArtifact(artifactType: ArtifactType, displayName: string): Promise<PlatformArtifact> {
  return postJson<PlatformArtifact>("/artifacts", {
    artifact_type: artifactType,
    display_name: displayName,
    state: { nodes: [], edges: [], ...(artifactType === "workshop" ? { widgets: [] } : {}) },
    layout: {}
  });
}

export function acquireArtifactLease(artifactId: string, token?: string): Promise<ArtifactLease> {
  return postJson<ArtifactLease>(`/artifacts/${encodeURIComponent(artifactId)}/leases`, { ttl_seconds: 180, token });
}

export function saveArtifact(
  artifact: PlatformArtifact,
  state: ArtifactState,
  leaseToken: string,
  message = "Autosaved visual edit"
): Promise<PlatformArtifact> {
  return api<PlatformArtifact>(`/artifacts/${encodeURIComponent(artifact.id)}`, {
    method: "PATCH",
    body: JSON.stringify({
      expected_lock_version: artifact.lock_version,
      lease_token: leaseToken,
      state,
      layout: Object.fromEntries(state.nodes.map((node) => [node.id, node.position])),
      message
    })
  });
}

export function getBuilderCatalog(artifactType: ArtifactType): Promise<BuilderCatalog> {
  return api<BuilderCatalog>(`/builder/catalogs/${encodeURIComponent(artifactType)}`);
}

export function applyArtifactCommands(
  artifact: PlatformArtifact,
  commands: BuilderCommand[],
  leaseToken: string,
  message = "Applied visual builder commands",
  idempotencyKey = crypto.randomUUID()
): Promise<PlatformArtifact> {
  return postJson<PlatformArtifact>(`/artifacts/${encodeURIComponent(artifact.id)}/commands`, {
    expected_lock_version: artifact.lock_version,
    lease_token: leaseToken,
    idempotency_key: idempotencyKey,
    commands,
    message
  });
}

export function previewArtifact(artifactId: string, sampleLimit = 20): Promise<ArtifactPreview> {
  return postJson<ArtifactPreview>(`/artifacts/${encodeURIComponent(artifactId)}/preview`, {
    sample_limit: sampleLimit,
    inputs: {}
  });
}

export function publishArtifact(artifact: PlatformArtifact): Promise<PlatformArtifact> {
  return postJson<PlatformArtifact>(`/artifacts/${encodeURIComponent(artifact.id)}/publish`, {
    expected_lock_version: artifact.lock_version,
    message: "Published from visual builder"
  });
}

export function listArtifactVersions(artifactId: string): Promise<ArtifactVersion[]> {
  return api<ArtifactVersion[]>(`/artifacts/${encodeURIComponent(artifactId)}/versions`);
}

export function restoreArtifactVersion(artifactId: string, revision: number): Promise<PlatformArtifact> {
  return postJson<PlatformArtifact>(`/artifacts/${encodeURIComponent(artifactId)}/versions/${revision}/restore`, {});
}
