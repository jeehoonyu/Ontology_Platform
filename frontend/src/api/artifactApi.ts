import { api, postJson } from "../api";

export type ArtifactType = "pipeline" | "ontology" | "workshop" | "aip_logic" | "investigation_graph" | "platform_graph" | "entity_resolution";

export interface ArtifactNodeData {
  [key: string]: unknown;
  label: string;
  description?: string;
  nodeType: string;
  fields?: Array<{ id: string; name: string; value: string }>;
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
  lease?: { holder: string; expires_at: number } | null;
  permissions: string[];
  created_at: number;
  updated_at: number;
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
