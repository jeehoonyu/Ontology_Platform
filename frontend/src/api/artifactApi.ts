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
  collaboration?: {
    active_participants: number;
    event_cursor: number;
    stream_href: string;
    open_comments?: number;
    open_proposals?: number;
    comments_href?: string;
    proposals_href?: string;
  };
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

export interface ArtifactCollaborator {
  id: string;
  artifact_id: string;
  principal_id: string;
  display_name: string;
  client_id: string;
  color: string;
  cursor: Record<string, unknown>;
  selection: string[];
  joined_at: number;
  heartbeat_at: number;
  expires_at: number;
}

export interface ArtifactCollaborationEvent {
  id: number;
  artifact_id: string;
  participant_id?: string | null;
  actor: string;
  event_type: string;
  lock_version: number;
  revision: number;
  payload: Record<string, unknown>;
  created_at: number;
}

export interface ArtifactCollaborationSession {
  participant: ArtifactCollaborator;
  participant_token: string;
  artifact: PlatformArtifact;
  event_cursor: number;
}

export interface ArtifactCollaborationState {
  artifact_id: string;
  lock_version: number;
  revision: number;
  participants: ArtifactCollaborator[];
  event_cursor: number;
  last_updated: number;
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

export interface ArtifactReviewComment {
  id: string;
  artifact_id: string;
  revision: number;
  target: string;
  thread_id: string;
  parent_id?: string | null;
  body: string;
  status: "OPEN" | "RESOLVED";
  author: string;
  resolved_by?: string | null;
  resolved_at?: number | null;
  created_at: number;
  updated_at: number;
}

export interface ArtifactChangeProposal {
  id: string;
  artifact_id: string;
  base_revision: number;
  base_lock_version: number;
  version: number;
  title: string;
  description?: string | null;
  commands: BuilderCommand[];
  targets: string[];
  validation: { status?: string; errors?: Array<Record<string, unknown>>; warnings?: Array<Record<string, unknown>> };
  status: "OPEN" | "APPROVED" | "REJECTED" | "CONFLICT" | "APPLIED";
  author: string;
  reviewer?: string | null;
  review_note?: string | null;
  applied_revision?: number | null;
  created_at: number;
  updated_at: number;
}

export interface ArtifactProposalApplyResult extends ArtifactChangeProposal {
  artifact: PlatformArtifact;
  idempotent_replay: boolean;
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

export function joinArtifactCollaboration(artifactId: string, clientId: string): Promise<ArtifactCollaborationSession> {
  return postJson<ArtifactCollaborationSession>(`/artifacts/${encodeURIComponent(artifactId)}/collaboration/join`, {
    client_id: clientId,
    ttl_seconds: 90
  });
}

export function getArtifactCollaboration(artifactId: string): Promise<ArtifactCollaborationState> {
  return api<ArtifactCollaborationState>(`/artifacts/${encodeURIComponent(artifactId)}/collaboration`);
}

export function heartbeatArtifactCollaboration(
  artifactId: string,
  participantToken: string,
  selection: string[]
): Promise<ArtifactCollaborator> {
  return postJson<ArtifactCollaborator>(`/artifacts/${encodeURIComponent(artifactId)}/collaboration/heartbeat`, {
    participant_token: participantToken,
    ttl_seconds: 90,
    selection
  });
}

export function leaveArtifactCollaboration(artifactId: string, participantToken: string): Promise<{ status: string }> {
  return postJson<{ status: string }>(`/artifacts/${encodeURIComponent(artifactId)}/collaboration/leave`, {
    participant_token: participantToken
  });
}

export function applyCollaborativeCommands(
  artifact: PlatformArtifact,
  participantToken: string,
  commands: BuilderCommand[],
  message = "Applied collaborative visual edit",
  idempotencyKey = crypto.randomUUID()
): Promise<PlatformArtifact> {
  return postJson<PlatformArtifact>(`/artifacts/${encodeURIComponent(artifact.id)}/collaboration/commands`, {
    participant_token: participantToken,
    expected_lock_version: artifact.lock_version,
    idempotency_key: idempotencyKey,
    commands,
    message
  });
}

export function artifactCollaborationStreamUrl(artifactId: string, after = 0): string {
  return `/artifacts/${encodeURIComponent(artifactId)}/collaboration/stream?after=${after}`;
}

export function artifactCollaborationWebSocketUrl(artifactId: string, after = 0): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/artifacts/${encodeURIComponent(artifactId)}/collaboration/ws?after=${after}`;
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

export function listArtifactComments(artifactId: string): Promise<{ comments: ArtifactReviewComment[]; count: number }> {
  return api(`/api/v1/artifacts/${encodeURIComponent(artifactId)}/comments`);
}

export function createArtifactComment(artifactId: string, target: string, body: string): Promise<ArtifactReviewComment> {
  return postJson(`/api/v1/artifacts/${encodeURIComponent(artifactId)}/comments`, { target, body });
}

export function setArtifactCommentStatus(
  artifactId: string,
  commentId: string,
  status: "OPEN" | "RESOLVED"
): Promise<ArtifactReviewComment> {
  return api(`/api/v1/artifacts/${encodeURIComponent(artifactId)}/comments/${encodeURIComponent(commentId)}`, {
    method: "PATCH",
    body: JSON.stringify({ status })
  });
}

export function listArtifactProposals(artifactId: string): Promise<{ proposals: ArtifactChangeProposal[]; count: number }> {
  return api(`/api/v1/artifacts/${encodeURIComponent(artifactId)}/proposals`);
}

export function createArtifactProposal(
  artifact: PlatformArtifact,
  title: string,
  commands: BuilderCommand[]
): Promise<ArtifactChangeProposal> {
  return postJson(`/api/v1/artifacts/${encodeURIComponent(artifact.id)}/proposals`, {
    title,
    expected_lock_version: artifact.lock_version,
    commands
  });
}

export function reviewArtifactProposal(
  artifactId: string,
  proposal: ArtifactChangeProposal,
  decision: "APPROVE" | "REJECT"
): Promise<ArtifactChangeProposal> {
  return postJson(`/api/v1/artifacts/${encodeURIComponent(artifactId)}/proposals/${encodeURIComponent(proposal.id)}/review`, {
    expected_version: proposal.version,
    decision
  });
}

export function applyArtifactProposal(artifactId: string, proposal: ArtifactChangeProposal): Promise<ArtifactProposalApplyResult> {
  return postJson(`/api/v1/artifacts/${encodeURIComponent(artifactId)}/proposals/${encodeURIComponent(proposal.id)}/apply`, {
    expected_version: proposal.version
  });
}
