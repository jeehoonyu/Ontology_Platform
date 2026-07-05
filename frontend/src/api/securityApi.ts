import { api, postJson } from "../api";

// ---------------------------------------------------------------------------
// Types are declared as `type` aliases (not interfaces) so they carry an
// implicit index signature and stay assignable to TableRow / JsonObject when
// passed to DataTable / KeyValueGrid in the workspace.
// ---------------------------------------------------------------------------

// ---- Markings & resource markings -----------------------------------------

export type Marking = {
  id: string;
  display_name: string;
  category: string;
  description?: string | null;
  created_at: number;
};

export type MarkingGrant = {
  id: string;
  marking_id: string;
  principal: string;
  permission: string;
  created_at: number;
};

export type ResourceMarkingResult = {
  id: string;
  resource_id: string;
  marking_id: string;
};

export type AccessDecisionResult = {
  principal: string;
  resource_id: string;
  required_markings: string[];
  held_markings: string[];
  allowed: boolean;
  missing_markings: string[];
};

export function listMarkings(): Promise<Marking[]> {
  return api<Marking[]>("/markings");
}

export function createMarking(body: {
  id?: string;
  display_name: string;
  category: string;
  description?: string;
}): Promise<Marking> {
  return postJson<Marking>("/markings", body);
}

export function grantMarking(markingId: string, principal: string): Promise<MarkingGrant> {
  return postJson<MarkingGrant>(`/markings/${encodeURIComponent(markingId)}/grant`, { principal });
}

export function assignResourceMarking(body: {
  resource_type?: string;
  resource_id: string;
  marking_id: string;
  actor?: string;
}): Promise<ResourceMarkingResult> {
  return postJson<ResourceMarkingResult>("/security/resource-markings", body);
}

export function decideAccess(body: {
  principal: string;
  resource_type?: string;
  resource_id: string;
}): Promise<AccessDecisionResult> {
  return postJson<AccessDecisionResult>("/security/access-decision", body);
}

// ---- Classification / CBAC -------------------------------------------------

export type ClsScheme = {
  id: string;
  display_name: string;
  levels: string[];
  category_groups: string[][];
  created_at: number;
};

export type ClsClassification = {
  id: string;
  scheme_id: string;
  kind: string;
  level: string;
  categories: string[];
  derived: boolean;
  created_at: number;
};

export type ClearanceResult = {
  id: string;
  principal_id: string;
  max_level: string;
};

export type ClassificationCheckResult = {
  allowed: boolean;
  reason: string;
  level_ok: boolean;
  required_level?: string;
  clearance_level?: string;
  category_failures: string[];
};

export function listSchemes(): Promise<ClsScheme[]> {
  return api<ClsScheme[]>("/classification/schemes");
}

export function createScheme(body: {
  id?: string;
  display_name: string;
  levels: string[];
  category_groups?: string[][];
}): Promise<ClsScheme> {
  return postJson<ClsScheme>("/classification/schemes", body);
}

export function listClassifications(): Promise<ClsClassification[]> {
  return api<ClsClassification[]>("/classification/classifications");
}

export function createClassification(body: {
  id?: string;
  scheme_id: string;
  kind: string;
  level: string;
  categories?: string[];
}): Promise<ClsClassification> {
  return postJson<ClsClassification>("/classification/classifications", body);
}

export function createClearance(body: {
  id?: string;
  principal_id: string;
  scheme_id: string;
  max_level: string;
  categories?: string[];
}): Promise<ClearanceResult> {
  return postJson<ClearanceResult>("/classification/clearances", body);
}

export function checkClassificationAccess(body: {
  principal_id: string;
  classification_id: string;
}): Promise<ClassificationCheckResult> {
  return postJson<ClassificationCheckResult>("/classification/check-access", body);
}

// ---- Projects, Roles & Grants ----------------------------------------------

export type Project = {
  id: string;
  display_name: string;
  description?: string | null;
  organization: string;
  created_at: number;
  updated_at: number;
};

export type Role = {
  id: string;
  display_name: string;
  permissions: string[];
  created_at: number;
};

export type RoleGrant = {
  id: string;
  project_id: string;
  principal: string;
  role_id: string;
  created_at: number;
};

export type ProjectAccessCheckResult = {
  allowed: boolean;
  project_id: string;
  principal: string;
  permission: string;
  matched_roles: string[];
};

export function listProjects(): Promise<Project[]> {
  return api<Project[]>("/projects");
}

export function createProject(body: {
  id?: string;
  display_name: string;
  description?: string;
  organization?: string;
}): Promise<Project> {
  return postJson<Project>("/projects", body);
}

export function listRoles(): Promise<Role[]> {
  return api<Role[]>("/roles");
}

export function createRole(body: {
  id?: string;
  display_name: string;
  permissions: string[];
}): Promise<Role> {
  return postJson<Role>("/roles", body);
}

export function listProjectGrants(projectId: string): Promise<RoleGrant[]> {
  return api<RoleGrant[]>(`/projects/${encodeURIComponent(projectId)}/grants`);
}

export function createProjectGrant(
  projectId: string,
  body: { principal: string; role_id: string }
): Promise<RoleGrant> {
  return postJson<RoleGrant>(`/projects/${encodeURIComponent(projectId)}/grants`, body);
}

export function checkProjectAccess(body: {
  project_id: string;
  principal: string;
  permission: string;
}): Promise<ProjectAccessCheckResult> {
  return postJson<ProjectAccessCheckResult>("/access/check", body);
}

// ---- Cipher ----------------------------------------------------------------

export type CipherChannel = {
  id: string;
  display_name: string;
  mode: string;
  key_ref: string;
  algorithm?: string | null;
  require_justification: boolean;
  created_at: number;
};

export type EncryptResult = { ciphertext: string };
export type DecryptResult = { value: string };
export type HashResult = { algorithm: string; digest: string };

export function listCipherChannels(): Promise<CipherChannel[]> {
  return api<CipherChannel[]>("/cipher/channels");
}

export function createCipherChannel(body: {
  id?: string;
  display_name: string;
  mode: string;
  key_ref: string;
  algorithm?: string;
  require_justification?: boolean;
}): Promise<CipherChannel> {
  return postJson<CipherChannel>("/cipher/channels", body);
}

export function cipherEncrypt(body: {
  channel_id: string;
  value: string;
  principal?: string;
  license_id?: string;
}): Promise<EncryptResult> {
  return postJson<EncryptResult>("/cipher/encrypt", body);
}

export function cipherDecrypt(body: {
  channel_id: string;
  ciphertext: string;
  principal: string;
  justification?: string;
  license_id?: string;
}): Promise<DecryptResult> {
  return postJson<DecryptResult>("/cipher/decrypt", body);
}

export function cipherHash(body: {
  channel_id: string;
  value: string;
  algorithm: string;
  principal?: string;
  license_id?: string;
}): Promise<HashResult> {
  return postJson<HashResult>("/cipher/hash", body);
}
