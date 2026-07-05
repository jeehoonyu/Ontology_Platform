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
  scopes: string[];
  revoked: boolean;
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
