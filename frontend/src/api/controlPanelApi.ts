import { api, postJson } from "../api";
import type { TableRow } from "../types";

// ---------------------------------------------------------------------------
// Organizations / directory
// ---------------------------------------------------------------------------
export interface Enrollment extends TableRow {
  id: string;
  display_name: string;
}

export interface Organization extends TableRow {
  id: string;
  enrollment_id: string;
  display_name: string;
}

export interface Space extends TableRow {
  id: string;
  organization_id: string;
  display_name: string;
}

export function listEnrollments(): Promise<Enrollment[]> {
  return api<Enrollment[]>("/admin/enrollments");
}

export function createEnrollment(body: { id?: string; display_name: string }): Promise<Enrollment> {
  return postJson<Enrollment>("/admin/enrollments", body);
}

export function listOrganizations(): Promise<Organization[]> {
  return api<Organization[]>("/admin/organizations");
}

export function createOrganization(body: { id?: string; enrollment_id: string; display_name: string }): Promise<Organization> {
  return postJson<Organization>("/admin/organizations", body);
}

export function listSpaces(organizationId?: string): Promise<Space[]> {
  const suffix = organizationId ? `?organization_id=${encodeURIComponent(organizationId)}` : "";
  return api<Space[]>(`/admin/spaces${suffix}`);
}

// ---------------------------------------------------------------------------
// Users
// ---------------------------------------------------------------------------
export interface AdminUser extends TableRow {
  id: string;
  username: string;
  status: string;
  organization_ids: string[];
  marking_ids: string[];
}

export interface UserStatusResult extends TableRow {
  id: string;
  status: string;
  note?: string;
}

export function listUsers(): Promise<AdminUser[]> {
  return api<AdminUser[]>("/admin/users");
}

export function createUser(body: {
  id?: string;
  username: string;
  display_name: string;
  email?: string;
  organization_ids: string[];
  marking_ids: string[];
}): Promise<AdminUser> {
  return postJson<AdminUser>("/admin/users", body);
}

export function setUserStatus(userId: string, status: string): Promise<UserStatusResult> {
  return postJson<UserStatusResult>(`/admin/users/${encodeURIComponent(userId)}/status`, { status });
}

// ---------------------------------------------------------------------------
// Groups & memberships
// ---------------------------------------------------------------------------
export interface AdminGroup extends TableRow {
  id: string;
  organization_id: string | null;
  display_name: string;
}

export interface GroupMember extends TableRow {
  user_id: string;
  expiration: number | null;
  expired: boolean;
  manage_permission: boolean;
  manage_membership: boolean;
}

export interface MembershipResult extends TableRow {
  id: string;
  group_id: string;
  user_id: string;
  expiration: number | null;
}

export function listGroups(): Promise<AdminGroup[]> {
  return api<AdminGroup[]>("/admin/groups");
}

export function createGroup(body: { id?: string; organization_id?: string | null; display_name: string }): Promise<AdminGroup> {
  return postJson<AdminGroup>("/admin/groups", body);
}

export function listGroupMembers(groupId: string): Promise<GroupMember[]> {
  return api<GroupMember[]>(`/admin/groups/${encodeURIComponent(groupId)}/members`);
}

export function addGroupMember(
  groupId: string,
  body: { user_id: string; expiration?: number | null; manage_permission?: boolean; manage_membership?: boolean; actor?: string }
): Promise<MembershipResult> {
  return postJson<MembershipResult>(`/admin/groups/${encodeURIComponent(groupId)}/members`, body);
}

// ---------------------------------------------------------------------------
// Roles & access
// ---------------------------------------------------------------------------
export interface RoleGrant extends TableRow {
  scope_type: string;
  scope_id: string;
  principal_type: string;
  principal_id: string;
  role: string;
}

export interface RoleGrantResult extends TableRow {
  id: string;
  scope: string;
  principal: string;
  role: string;
}

export interface AccessCheckResult extends TableRow {
  allowed: boolean;
  reason?: string;
  user_id?: string;
  scope?: string;
  effective_roles?: string[];
  capabilities?: string[];
  via_groups?: string[];
  scopes_considered?: string[];
}

export function listRoleGrants(scopeId?: string): Promise<RoleGrant[]> {
  const suffix = scopeId ? `?scope_id=${encodeURIComponent(scopeId)}` : "";
  return api<RoleGrant[]>(`/admin/roles${suffix}`);
}

export function grantRole(body: {
  scope_type: string;
  scope_id: string;
  principal_type: string;
  principal_id: string;
  role: string;
}): Promise<RoleGrantResult> {
  return postJson<RoleGrantResult>("/admin/roles/grant", body);
}

export function accessCheck(body: {
  user_id: string;
  scope_type: string;
  scope_id: string;
  capability: string;
}): Promise<AccessCheckResult> {
  return postJson<AccessCheckResult>("/admin/access-check", body);
}

// ---------------------------------------------------------------------------
// Auth: providers, service accounts, tokens, oauth clients
// ---------------------------------------------------------------------------
export interface AuthProvider extends TableRow {
  id: string;
  name: string;
  protocol: string;
  enabled: boolean;
}

export interface ServiceAccount extends TableRow {
  id: string;
  display_name: string;
  organization_id: string | null;
}

export interface ApiToken extends TableRow {
  id: string;
  principal_id: string;
  principal_type: string;
  token_prefix: string | null;
  scopes: string[];
  revoked: boolean;
  expires_at: number | null;
  created_at: number;
  last_used_at: number | null;
}

export interface IssuedApiToken {
  id: string;
  token: string;
  principal_id: string;
  scopes: string[];
  expires_at: number | null;
}

export interface OAuthClient extends TableRow {
  id: string;
  display_name: string;
  client_id: string;
  scopes: string[];
  redirect_uris: string[];
}

export function listAuthProviders(): Promise<AuthProvider[]> {
  return api<AuthProvider[]>("/admin/auth-providers");
}

export function createAuthProvider(body: {
  id?: string;
  name: string;
  protocol: string;
  config?: Record<string, unknown>;
  attribute_mapping?: Record<string, string>;
}): Promise<AuthProvider> {
  return postJson<AuthProvider>("/admin/auth-providers", body);
}

export function listServiceAccounts(organizationId?: string): Promise<ServiceAccount[]> {
  const suffix = organizationId ? `?organization_id=${encodeURIComponent(organizationId)}` : "";
  return api<ServiceAccount[]>(`/admin/service-accounts${suffix}`);
}

export function listTokens(principalId?: string): Promise<ApiToken[]> {
  const suffix = principalId ? `?principal_id=${encodeURIComponent(principalId)}` : "";
  return api<ApiToken[]>(`/admin/tokens${suffix}`);
}

export function listOAuthClients(): Promise<OAuthClient[]> {
  return api<OAuthClient[]>("/admin/oauth-clients");
}

// ---------------------------------------------------------------------------
// Usage: summary, quotas, quota checks
// ---------------------------------------------------------------------------
export interface UsageBreakdownItem extends TableRow {
  key: string;
  value: number;
}

export interface UsageSummary {
  group_by: string;
  record_count: number;
  total: number;
  breakdown: UsageBreakdownItem[];
}

export interface UsageQuota extends TableRow {
  scope_type: string;
  scope_id: string;
  metric: string;
  limit_value: number;
}

export interface QuotaResult extends TableRow {
  id: string;
  scope: string;
  metric: string;
  limit_value: number;
}

export interface QuotaCheckResult extends TableRow {
  scope: string;
  metric: string;
  usage: number;
  limit: number | null;
  remaining?: number;
  within_limit: boolean;
  note?: string;
}

export function getUsageSummary(params: { project?: string; metric?: string; group_by?: string } = {}): Promise<UsageSummary> {
  const query = new URLSearchParams();
  if (params.project) query.set("project", params.project);
  if (params.metric) query.set("metric", params.metric);
  if (params.group_by) query.set("group_by", params.group_by);
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return api<UsageSummary>(`/admin/usage/summary${suffix}`);
}

export function listQuotas(): Promise<UsageQuota[]> {
  return api<UsageQuota[]>("/admin/usage/quotas");
}

export function createQuota(body: { scope_type: string; scope_id: string; metric: string; limit_value: number }): Promise<QuotaResult> {
  return postJson<QuotaResult>("/admin/usage/quotas", body);
}

export function checkQuota(body: { scope_type: string; scope_id: string; metric: string }): Promise<QuotaCheckResult> {
  return postJson<QuotaCheckResult>("/admin/usage/check-quota", body);
}

// ---------------------------------------------------------------------------
// Recovery
// ---------------------------------------------------------------------------
export interface SnapshotIntegrity {
  algorithm: "sha256";
  checksum: string;
  counts: Record<string, number>;
  resource_count: number;
}

export interface CredentialRebind extends TableRow {
  resource_type: string;
  resource_id: string;
  field: string;
}

export interface PortableSnapshot {
  snapshot_format: string;
  snapshot_version: number;
  exported_at: number;
  integrity: SnapshotIntegrity;
  rebind_required: CredentialRebind[];
  [key: string]: unknown;
}

export interface SnapshotValidation {
  status: "VALID" | "INVALID";
  snapshot_version: number;
  errors: string[];
  warnings: string[];
  counts: Record<string, number>;
  resource_count: number;
  rebind_required: CredentialRebind[];
}

export interface SnapshotImportResult {
  status: "VALIDATED" | "IMPORTED";
  mode: string;
  counts?: Record<string, number>;
  validation: SnapshotValidation;
}

export function exportPortableSnapshot(): Promise<PortableSnapshot> {
  return api<PortableSnapshot>("/project/export");
}

export function validatePortableSnapshot(snapshot: PortableSnapshot): Promise<SnapshotValidation> {
  return postJson<SnapshotValidation>("/project/import/validate", { snapshot, mode: "merge" });
}

export function importPortableSnapshot(snapshot: PortableSnapshot, dryRun: boolean): Promise<SnapshotImportResult> {
  return postJson<SnapshotImportResult>("/project/import", { snapshot, mode: "merge", dry_run: dryRun });
}

export function createServiceAccount(body: { id?: string; display_name: string; organization_id?: string | null }): Promise<ServiceAccount> {
  return postJson<ServiceAccount>("/admin/service-accounts", body);
}

export function issueToken(body: {
  principal_type: "user" | "service_account";
  principal_id: string;
  scopes: string[];
  ttl_seconds?: number;
}): Promise<IssuedApiToken> {
  return postJson<IssuedApiToken>("/admin/tokens", body);
}

export function revokeToken(tokenId: string): Promise<{ id: string; revoked: boolean }> {
  return postJson(`/admin/tokens/${encodeURIComponent(tokenId)}/revoke`, {});
}

// ---------------------------------------------------------------------------
// Runtime operations: durable jobs, budgets, and service objectives
// ---------------------------------------------------------------------------
export interface RuntimeSummary {
  project_id: string;
  total_jobs: number;
  status_counts: Record<string, number>;
  availability: number;
  latency_p95_ms: number;
  queue_p95_ms: number;
  compute_seconds: number;
  token_units: number;
  record_units: number;
  estimated_cost_usd: number;
  warnings: string[];
  last_updated: number;
}

export interface RuntimeObservation extends TableRow {
  id: string;
  project_id: string;
  job_id: string;
  job_type: string;
  status: string;
  progress: number;
  duration_ms: number;
  queue_latency_ms: number;
  estimated_cost_usd: number;
}

export interface RuntimeBudget extends TableRow {
  id: string;
  project_id: string;
  metric: string;
  limit_value: number;
  window_seconds: number;
  enforcement: string;
  enabled: boolean;
}

export interface RuntimeSlo extends TableRow {
  id: string;
  project_id: string;
  display_name: string;
  job_type?: string | null;
  metric: string;
  operator: string;
  threshold: number;
  window_seconds: number;
  severity: string;
  enabled: boolean;
}

export function getRuntimeSummary(projectId: string): Promise<RuntimeSummary> {
  return api<RuntimeSummary>(`/runtime/observability/summary?project_id=${encodeURIComponent(projectId)}`);
}

export function listRuntimeJobs(projectId: string): Promise<RuntimeObservation[]> {
  return api<RuntimeObservation[]>(`/runtime/observability/jobs?project_id=${encodeURIComponent(projectId)}&limit=50`);
}

export function listRuntimeBudgets(projectId: string): Promise<RuntimeBudget[]> {
  return api<RuntimeBudget[]>(`/runtime/observability/budgets?project_id=${encodeURIComponent(projectId)}`);
}

export function upsertRuntimeBudget(body: Omit<RuntimeBudget, "id">): Promise<RuntimeBudget> {
  return api<RuntimeBudget>("/runtime/observability/budgets", { method: "PUT", body: JSON.stringify(body) });
}

export function listRuntimeSlos(projectId: string): Promise<RuntimeSlo[]> {
  return api<RuntimeSlo[]>(`/runtime/observability/slo-policies?project_id=${encodeURIComponent(projectId)}`);
}

export function createRuntimeSlo(body: Omit<RuntimeSlo, "id"> & { id?: string }): Promise<RuntimeSlo> {
  return postJson<RuntimeSlo>("/runtime/observability/slo-policies", body);
}

export function evaluateRuntimeSlo(policyId: string): Promise<TableRow> {
  return postJson<TableRow>(`/runtime/observability/slo-policies/${encodeURIComponent(policyId)}/evaluate`, {});
}

export interface RuntimeWorker extends TableRow {
  id: string;
  worker_name: string;
  project_id?: string | null;
  status: string;
  configured_status: string;
  supported_job_types: string[];
  max_concurrency: number;
  active_jobs: number;
  available_slots: number;
  heartbeat_at: number;
}

export interface RuntimeQueuePolicy extends TableRow {
  id: string;
  project_id: string;
  weight: number;
  max_concurrency: number;
  paused: boolean;
}

export interface WorkerFleetState {
  summary: { workers: number; active: number; draining: number; offline: number; active_jobs: number };
  primary_actions: string[];
  sections: { workers: RuntimeWorker[]; queue_policies: RuntimeQueuePolicy[] };
  warnings: string[];
  last_updated: number;
}

export function getWorkerFleet(projectId: string): Promise<WorkerFleetState> {
  return api<WorkerFleetState>(`/ui-state/worker-fleet?project_id=${encodeURIComponent(projectId)}`);
}

export function registerRuntimeWorker(workerName: string, body: {
  project_id: string;
  supported_job_types: string[];
  max_concurrency: number;
  labels?: Record<string, string>;
}): Promise<RuntimeWorker> {
  return api<RuntimeWorker>(`/runtime/workers/${encodeURIComponent(workerName)}`, { method: "PUT", body: JSON.stringify(body) });
}

export function setRuntimeWorkerDrain(workerName: string, draining: boolean): Promise<RuntimeWorker> {
  return postJson<RuntimeWorker>(`/runtime/workers/${encodeURIComponent(workerName)}/${draining ? "drain" : "resume"}`, {});
}

export function upsertRuntimeQueuePolicy(projectId: string, body: {
  weight: number;
  max_concurrency: number;
  paused: boolean;
}): Promise<RuntimeQueuePolicy> {
  return api<RuntimeQueuePolicy>(`/runtime/queues/${encodeURIComponent(projectId)}`, { method: "PUT", body: JSON.stringify(body) });
}
