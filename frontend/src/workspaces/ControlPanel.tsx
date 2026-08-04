import { useState } from "react";
import {
  DataTable,
  EmptyState,
  ErrorBanner,
  KeyValueGrid,
  LoadingState,
  Metric,
  Panel,
  StatusBadge
} from "../components/data/DataDisplay";
import { Page } from "../components/workbench/Workbench";
import { useAsyncState } from "../hooks/useAsyncState";
import { classNames } from "../utils/format";
import * as admin from "../api/controlPanelApi";

const SECTIONS = [
  { id: "organizations", label: "Organizations" },
  { id: "users", label: "Users" },
  { id: "groups", label: "Groups" },
  { id: "roles", label: "Roles" },
  { id: "auth", label: "Auth" },
  { id: "usage", label: "Usage" },
  { id: "recovery", label: "Recovery" },
  { id: "extensions", label: "Extensions" },
  { id: "operations", label: "Runtime" }
];

const SCOPE_TYPES = ["enrollment", "organization", "space", "project"];
const ROLE_OPTIONS = ["viewer", "editor", "owner", "administrator"];
const PRINCIPAL_TYPES = ["user", "group"];
const CAPABILITIES = ["view", "edit", "manage", "administer"];
const PROTOCOLS = ["saml", "oidc"];
const USAGE_METRICS = ["compute_seconds", "storage_bytes", "rows"];
const QUOTA_SCOPES = ["project", "organization"];
const GROUP_BY = ["project", "principal", "organization", "resource", "metric"];
const RUNTIME_METRICS = ["executions", "compute_seconds", "token_units", "record_units", "estimated_cost_usd"];
const SLO_METRICS = ["availability", "error_rate", "latency_p95_ms", "queue_p95_ms", "cost_usd", "throughput_per_minute"];

function toOptions(values: string[]): Array<{ value: string; label: string }> {
  return values.map((value) => ({ value, label: value }));
}

function splitList(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export function ControlPanel() {
  const [section, setSection] = useState("organizations");
  const active = SECTIONS.find((item) => item.id === section) || SECTIONS[0];
  return (
    <Page title="Control Panel" subtitle="Administer organizations, users, groups, roles, authentication, and usage.">
      <div className="workspace-header">
        <div>
          <strong>Administration</strong>
          <span>Admin</span>
        </div>
        <nav>
          {SECTIONS.map((item) => (
            <button key={item.id} className={classNames(section === item.id && "active")} onClick={() => setSection(item.id)}>
              {item.label}
            </button>
          ))}
        </nav>
        <div className="button-row">
          <StatusBadge value={active.label} />
        </div>
      </div>
      {section === "organizations" && <OrganizationsSection />}
      {section === "users" && <UsersSection />}
      {section === "groups" && <GroupsSection />}
      {section === "roles" && <RolesSection />}
      {section === "auth" && <AuthSection />}
      {section === "usage" && <UsageSection />}
      {section === "recovery" && <RecoverySection />}
      {section === "extensions" && <ExtensionsSection />}
      {section === "operations" && <RuntimeOperationsSection />}
    </Page>
  );
}

// ---------------------------------------------------------------------------
// Reusable form field helpers
// ---------------------------------------------------------------------------
function TextField({
  label,
  value,
  onChange,
  placeholder,
  type = "text"
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  type?: string;
}) {
  return (
    <label>
      <span>{label}</span>
      <input type={type} value={value} placeholder={placeholder} onChange={(event) => onChange(event.target.value)} />
    </label>
  );
}

function SelectField({
  label,
  value,
  onChange,
  options,
  placeholder
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: Array<{ value: string; label: string }>;
  placeholder?: string;
}) {
  return (
    <label>
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        {placeholder !== undefined ? <option value="">{placeholder}</option> : null}
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function CheckboxField({ label, checked, onChange }: { label: string; checked: boolean; onChange: (value: boolean) => void }) {
  return (
    <label>
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
      {label}
    </label>
  );
}

// ---------------------------------------------------------------------------
// Organizations
// ---------------------------------------------------------------------------
function OrganizationsSection() {
  const [refreshKey, setRefreshKey] = useState(0);
  const [error, setError] = useState("");
  const enrollments = useAsyncState<admin.Enrollment[]>(admin.listEnrollments, [refreshKey]);
  const organizations = useAsyncState<admin.Organization[]>(admin.listOrganizations, [refreshKey]);
  const spaces = useAsyncState<admin.Space[]>(() => admin.listSpaces(), [refreshKey]);

  const [enrollmentName, setEnrollmentName] = useState("");
  const [orgForm, setOrgForm] = useState({ enrollment_id: "", display_name: "" });

  const reload = () => setRefreshKey((key) => key + 1);
  const enrollmentOptions = (enrollments.value || []).map((item) => ({ value: item.id, label: item.display_name }));

  async function submitEnrollment() {
    if (!enrollmentName.trim()) return;
    try {
      await admin.createEnrollment({ display_name: enrollmentName.trim() });
      setEnrollmentName("");
      setError("");
      reload();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function submitOrganization() {
    if (!orgForm.enrollment_id || !orgForm.display_name.trim()) return;
    try {
      await admin.createOrganization({ enrollment_id: orgForm.enrollment_id, display_name: orgForm.display_name.trim() });
      setOrgForm({ enrollment_id: "", display_name: "" });
      setError("");
      reload();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <>
      <ErrorBanner message={error || enrollments.error || organizations.error || spaces.error} />
      {(enrollments.loading || organizations.loading || spaces.loading) && <LoadingState label="Loading directory..." />}
      <div className="grid metrics">
        <Metric label="Enrollments" value={(enrollments.value || []).length} />
        <Metric label="Organizations" value={(organizations.value || []).length} />
        <Metric label="Spaces" value={(spaces.value || []).length} />
      </div>
      <div className="two-col">
        <Panel title="Create Enrollment" action={<button onClick={submitEnrollment} disabled={!enrollmentName.trim()}>Create</button>}>
          <div className="metadata-edit-grid">
            <TextField label="Display name" value={enrollmentName} onChange={setEnrollmentName} placeholder="Acme Enrollment" />
          </div>
        </Panel>
        <Panel title="Enrollments" action={<button onClick={reload}>Refresh</button>}>
          <DataTable rows={enrollments.value || []} empty="No enrollments yet." />
        </Panel>
      </div>
      <div className="two-col">
        <Panel
          title="Create Organization"
          action={<button onClick={submitOrganization} disabled={!orgForm.enrollment_id || !orgForm.display_name.trim()}>Create</button>}
        >
          <div className="metadata-edit-grid">
            <SelectField
              label="Enrollment"
              value={orgForm.enrollment_id}
              onChange={(value) => setOrgForm({ ...orgForm, enrollment_id: value })}
              options={enrollmentOptions}
              placeholder="Choose enrollment"
            />
            <TextField
              label="Display name"
              value={orgForm.display_name}
              onChange={(value) => setOrgForm({ ...orgForm, display_name: value })}
              placeholder="Engineering Org"
            />
          </div>
        </Panel>
        <Panel title="Organizations">
          <DataTable rows={organizations.value || []} empty="No organizations yet." />
        </Panel>
      </div>
      <Panel title="Spaces" action={<button onClick={reload}>Refresh</button>}>
        <DataTable rows={spaces.value || []} empty="No spaces yet." />
      </Panel>
    </>
  );
}

// ---------------------------------------------------------------------------
// Users
// ---------------------------------------------------------------------------
function UsersSection() {
  const [refreshKey, setRefreshKey] = useState(0);
  const [error, setError] = useState("");
  const users = useAsyncState<admin.AdminUser[]>(admin.listUsers, [refreshKey]);

  const [form, setForm] = useState({ username: "", display_name: "", email: "", organization_ids: "", marking_ids: "" });
  const [statusForm, setStatusForm] = useState({ user_id: "", status: "active" });

  const reload = () => setRefreshKey((key) => key + 1);
  const userOptions = (users.value || []).map((user) => ({ value: user.id, label: `${user.username} (${user.status})` }));

  async function submitUser() {
    if (!form.username.trim() || !form.display_name.trim()) return;
    try {
      await admin.createUser({
        username: form.username.trim(),
        display_name: form.display_name.trim(),
        email: form.email.trim() || undefined,
        organization_ids: splitList(form.organization_ids),
        marking_ids: splitList(form.marking_ids)
      });
      setForm({ username: "", display_name: "", email: "", organization_ids: "", marking_ids: "" });
      setError("");
      reload();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function applyStatus() {
    if (!statusForm.user_id) return;
    try {
      await admin.setUserStatus(statusForm.user_id, statusForm.status);
      setError("");
      reload();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <>
      <ErrorBanner message={error || users.error} />
      {users.loading && <LoadingState label="Loading users..." />}
      <div className="grid metrics">
        <Metric label="Users" value={(users.value || []).length} />
        <Metric label="Active" value={(users.value || []).filter((user) => user.status === "active").length} />
        <Metric label="Inactive" value={(users.value || []).filter((user) => user.status !== "active").length} />
      </div>
      <div className="two-col">
        <Panel title="Create User" action={<button onClick={submitUser} disabled={!form.username.trim() || !form.display_name.trim()}>Create</button>}>
          <div className="metadata-edit-grid">
            <TextField label="Username" value={form.username} onChange={(value) => setForm({ ...form, username: value })} placeholder="jdoe" />
            <TextField label="Display name" value={form.display_name} onChange={(value) => setForm({ ...form, display_name: value })} placeholder="Jane Doe" />
            <TextField label="Email" value={form.email} onChange={(value) => setForm({ ...form, email: value })} placeholder="jane@acme.dev" />
            <TextField
              label="Organization ids (comma separated)"
              value={form.organization_ids}
              onChange={(value) => setForm({ ...form, organization_ids: value })}
              placeholder="org_1, org_2"
            />
            <TextField
              label="Marking ids (comma separated)"
              value={form.marking_ids}
              onChange={(value) => setForm({ ...form, marking_ids: value })}
              placeholder="pii, restricted"
            />
          </div>
        </Panel>
        <Panel title="Change User Status" action={<button onClick={applyStatus} disabled={!statusForm.user_id}>Apply</button>}>
          <div className="metadata-edit-grid">
            <SelectField
              label="User"
              value={statusForm.user_id}
              onChange={(value) => setStatusForm({ ...statusForm, user_id: value })}
              options={userOptions}
              placeholder="Choose user"
            />
            <SelectField
              label="Status"
              value={statusForm.status}
              onChange={(value) => setStatusForm({ ...statusForm, status: value })}
              options={toOptions(["active", "inactive"])}
            />
          </div>
          <p className="notice">Tokens are invalid while an account is inactive.</p>
        </Panel>
      </div>
      <Panel title="Users" action={<button onClick={reload}>Refresh</button>}>
        <DataTable rows={users.value || []} empty="No users yet." />
      </Panel>
    </>
  );
}

// ---------------------------------------------------------------------------
// Groups & memberships
// ---------------------------------------------------------------------------
function GroupsSection() {
  const [refreshKey, setRefreshKey] = useState(0);
  const [error, setError] = useState("");
  const groups = useAsyncState<admin.AdminGroup[]>(admin.listGroups, [refreshKey]);
  const users = useAsyncState<admin.AdminUser[]>(admin.listUsers, [refreshKey]);
  const organizations = useAsyncState<admin.Organization[]>(admin.listOrganizations, [refreshKey]);

  const [groupForm, setGroupForm] = useState({ display_name: "", organization_id: "" });
  const [selectedGroupId, setSelectedGroupId] = useState("");
  const [memberForm, setMemberForm] = useState({ user_id: "", expiration: "", manage_permission: false, manage_membership: false });

  const members = useAsyncState<admin.GroupMember[]>(
    () => (selectedGroupId ? admin.listGroupMembers(selectedGroupId) : Promise.resolve([])),
    [selectedGroupId, refreshKey]
  );

  const reload = () => setRefreshKey((key) => key + 1);
  const groupOptions = (groups.value || []).map((group) => ({ value: group.id, label: group.display_name }));
  const orgOptions = (organizations.value || []).map((org) => ({ value: org.id, label: org.display_name }));
  const userOptions = (users.value || []).map((user) => ({ value: user.id, label: `${user.username} (${user.status})` }));

  async function submitGroup() {
    if (!groupForm.display_name.trim()) return;
    try {
      await admin.createGroup({
        display_name: groupForm.display_name.trim(),
        organization_id: groupForm.organization_id || null
      });
      setGroupForm({ display_name: "", organization_id: "" });
      setError("");
      reload();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function submitMember() {
    if (!selectedGroupId || !memberForm.user_id) return;
    const expiration = memberForm.expiration.trim() ? Number(memberForm.expiration.trim()) : null;
    try {
      await admin.addGroupMember(selectedGroupId, {
        user_id: memberForm.user_id,
        expiration,
        manage_permission: memberForm.manage_permission,
        manage_membership: memberForm.manage_membership
      });
      setMemberForm({ user_id: "", expiration: "", manage_permission: false, manage_membership: false });
      setError("");
      reload();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <>
      <ErrorBanner message={error || groups.error || users.error || members.error} />
      {(groups.loading || users.loading) && <LoadingState label="Loading groups..." />}
      <div className="grid metrics">
        <Metric label="Groups" value={(groups.value || []).length} />
        <Metric label="Selected members" value={selectedGroupId ? (members.value || []).length : "-"} />
      </div>
      <div className="two-col">
        <Panel title="Create Group" action={<button onClick={submitGroup} disabled={!groupForm.display_name.trim()}>Create</button>}>
          <div className="metadata-edit-grid">
            <TextField
              label="Display name"
              value={groupForm.display_name}
              onChange={(value) => setGroupForm({ ...groupForm, display_name: value })}
              placeholder="Platform Admins"
            />
            <SelectField
              label="Organization (optional)"
              value={groupForm.organization_id}
              onChange={(value) => setGroupForm({ ...groupForm, organization_id: value })}
              options={orgOptions}
              placeholder="No organization"
            />
          </div>
        </Panel>
        <Panel title="Groups" action={<button onClick={reload}>Refresh</button>}>
          <DataTable rows={groups.value || []} empty="No groups yet." />
        </Panel>
      </div>
      <div className="two-col">
        <Panel title="Add Member" action={<button onClick={submitMember} disabled={!selectedGroupId || !memberForm.user_id}>Add</button>}>
          <div className="metadata-edit-grid">
            <SelectField
              label="Group"
              value={selectedGroupId}
              onChange={(value) => setSelectedGroupId(value)}
              options={groupOptions}
              placeholder="Choose group"
            />
            <SelectField
              label="User"
              value={memberForm.user_id}
              onChange={(value) => setMemberForm({ ...memberForm, user_id: value })}
              options={userOptions}
              placeholder="Choose user"
            />
            <TextField
              label="Expiration (unix seconds, optional)"
              value={memberForm.expiration}
              onChange={(value) => setMemberForm({ ...memberForm, expiration: value })}
              placeholder="1790000000"
            />
          </div>
          <div className="button-row">
            <CheckboxField
              label="Manage permission"
              checked={memberForm.manage_permission}
              onChange={(value) => setMemberForm({ ...memberForm, manage_permission: value })}
            />
            <CheckboxField
              label="Manage membership"
              checked={memberForm.manage_membership}
              onChange={(value) => setMemberForm({ ...memberForm, manage_membership: value })}
            />
          </div>
        </Panel>
        <Panel title="Members" action={<button onClick={reload} disabled={!selectedGroupId}>Refresh</button>}>
          {selectedGroupId ? (
            <DataTable rows={members.value || []} empty="No members in this group." />
          ) : (
            <EmptyState title="No group selected" description="Choose a group to inspect its members." />
          )}
        </Panel>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Roles & access checks
// ---------------------------------------------------------------------------
function RolesSection() {
  const [refreshKey, setRefreshKey] = useState(0);
  const [error, setError] = useState("");
  const grants = useAsyncState<admin.RoleGrant[]>(() => admin.listRoleGrants(), [refreshKey]);

  const [grantForm, setGrantForm] = useState({
    scope_type: "organization",
    scope_id: "",
    principal_type: "user",
    principal_id: "",
    role: "viewer"
  });
  const [checkForm, setCheckForm] = useState({ user_id: "", scope_type: "organization", scope_id: "", capability: "view" });
  const [checkResult, setCheckResult] = useState<admin.AccessCheckResult | null>(null);

  const reload = () => setRefreshKey((key) => key + 1);

  async function submitGrant() {
    if (!grantForm.scope_id.trim() || !grantForm.principal_id.trim()) return;
    try {
      await admin.grantRole({
        scope_type: grantForm.scope_type,
        scope_id: grantForm.scope_id.trim(),
        principal_type: grantForm.principal_type,
        principal_id: grantForm.principal_id.trim(),
        role: grantForm.role
      });
      setGrantForm({ ...grantForm, scope_id: "", principal_id: "" });
      setError("");
      reload();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function runCheck() {
    if (!checkForm.user_id.trim() || !checkForm.scope_id.trim()) return;
    try {
      const result = await admin.accessCheck({
        user_id: checkForm.user_id.trim(),
        scope_type: checkForm.scope_type,
        scope_id: checkForm.scope_id.trim(),
        capability: checkForm.capability
      });
      setCheckResult(result);
      setError("");
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <>
      <ErrorBanner message={error || grants.error} />
      {grants.loading && <LoadingState label="Loading role grants..." />}
      <div className="grid metrics">
        <Metric label="Role grants" value={(grants.value || []).length} />
        <Metric label="Access check" value={checkResult ? (checkResult.allowed ? "ALLOWED" : "DENIED") : "-"} />
      </div>
      <div className="two-col">
        <Panel
          title="Grant Role"
          action={<button onClick={submitGrant} disabled={!grantForm.scope_id.trim() || !grantForm.principal_id.trim()}>Grant</button>}
        >
          <div className="metadata-edit-grid">
            <SelectField
              label="Scope type"
              value={grantForm.scope_type}
              onChange={(value) => setGrantForm({ ...grantForm, scope_type: value })}
              options={toOptions(SCOPE_TYPES)}
            />
            <TextField label="Scope id" value={grantForm.scope_id} onChange={(value) => setGrantForm({ ...grantForm, scope_id: value })} placeholder="org_1" />
            <SelectField
              label="Principal type"
              value={grantForm.principal_type}
              onChange={(value) => setGrantForm({ ...grantForm, principal_type: value })}
              options={toOptions(PRINCIPAL_TYPES)}
            />
            <TextField
              label="Principal id"
              value={grantForm.principal_id}
              onChange={(value) => setGrantForm({ ...grantForm, principal_id: value })}
              placeholder="user_1 or group_1"
            />
            <SelectField
              label="Role"
              value={grantForm.role}
              onChange={(value) => setGrantForm({ ...grantForm, role: value })}
              options={toOptions(ROLE_OPTIONS)}
            />
          </div>
        </Panel>
        <Panel title="Role Grants" action={<button onClick={reload}>Refresh</button>}>
          <DataTable rows={grants.value || []} empty="No role grants yet." />
        </Panel>
      </div>
      <div className="two-col">
        <Panel
          title="Access Check"
          action={<button onClick={runCheck} disabled={!checkForm.user_id.trim() || !checkForm.scope_id.trim()}>Check</button>}
        >
          <div className="metadata-edit-grid">
            <TextField label="User id" value={checkForm.user_id} onChange={(value) => setCheckForm({ ...checkForm, user_id: value })} placeholder="user_1" />
            <SelectField
              label="Scope type"
              value={checkForm.scope_type}
              onChange={(value) => setCheckForm({ ...checkForm, scope_type: value })}
              options={toOptions(SCOPE_TYPES)}
            />
            <TextField label="Scope id" value={checkForm.scope_id} onChange={(value) => setCheckForm({ ...checkForm, scope_id: value })} placeholder="org_1" />
            <SelectField
              label="Capability"
              value={checkForm.capability}
              onChange={(value) => setCheckForm({ ...checkForm, capability: value })}
              options={toOptions(CAPABILITIES)}
            />
          </div>
        </Panel>
        <Panel title="Access Check Result">
          {checkResult ? (
            <>
              <div className="manager-chip-row">
                <StatusBadge value={checkResult.allowed ? "allowed" : "denied"} />
                {checkResult.reason ? <StatusBadge value={checkResult.reason} /> : null}
              </div>
              <KeyValueGrid data={checkResult} />
            </>
          ) : (
            <EmptyState title="No access check run" description="Resolve effective roles and capabilities for a user at a scope." />
          )}
        </Panel>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Auth: providers, service accounts, tokens, oauth clients
// ---------------------------------------------------------------------------
function AuthSection() {
  const [refreshKey, setRefreshKey] = useState(0);
  const [error, setError] = useState("");
  const providers = useAsyncState<admin.AuthProvider[]>(admin.listAuthProviders, [refreshKey]);
  const serviceAccounts = useAsyncState<admin.ServiceAccount[]>(() => admin.listServiceAccounts(), [refreshKey]);
  const tokens = useAsyncState<admin.ApiToken[]>(() => admin.listTokens(), [refreshKey]);
  const oauthClients = useAsyncState<admin.OAuthClient[]>(admin.listOAuthClients, [refreshKey]);

  const [providerForm, setProviderForm] = useState({ name: "", protocol: "saml" });
  const [serviceForm, setServiceForm] = useState({ id: "", displayName: "", organizationId: "local" });
  const [tokenForm, setTokenForm] = useState({ principalId: "", projectId: "default", ttlHours: "720" });
  const [issuedToken, setIssuedToken] = useState<admin.IssuedApiToken | null>(null);
  const [revokeTokenId, setRevokeTokenId] = useState("");

  const reload = () => setRefreshKey((key) => key + 1);

  async function submitProvider() {
    if (!providerForm.name.trim()) return;
    try {
      await admin.createAuthProvider({ name: providerForm.name.trim(), protocol: providerForm.protocol });
      setProviderForm({ name: "", protocol: "saml" });
      setError("");
      reload();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function submitServiceAccount() {
    if (!serviceForm.id.trim() || !serviceForm.displayName.trim()) return;
    try {
      const account = await admin.createServiceAccount({
        id: serviceForm.id.trim(), display_name: serviceForm.displayName.trim(),
        organization_id: serviceForm.organizationId.trim() || null
      });
      setTokenForm((current) => ({ ...current, principalId: account.id }));
      setServiceForm({ id: "", displayName: "", organizationId: serviceForm.organizationId });
      setError("");
      reload();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function submitWorkerToken() {
    if (!tokenForm.principalId || !tokenForm.projectId.trim()) return;
    try {
      setIssuedToken(await admin.issueToken({
        principal_type: "service_account", principal_id: tokenForm.principalId,
        scopes: [`project:${tokenForm.projectId.trim()}:execute`],
        ttl_seconds: Math.max(1, Number(tokenForm.ttlHours) || 1) * 3600
      }));
      setError("");
      reload();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function revokeWorkerToken() {
    if (!revokeTokenId) return;
    try {
      await admin.revokeToken(revokeTokenId);
      setRevokeTokenId("");
      setError("");
      reload();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <>
      <ErrorBanner message={error || providers.error || serviceAccounts.error || tokens.error || oauthClients.error} />
      {(providers.loading || serviceAccounts.loading || tokens.loading || oauthClients.loading) && (
        <LoadingState label="Loading authentication resources..." />
      )}
      <div className="grid metrics">
        <Metric label="Auth providers" value={(providers.value || []).length} />
        <Metric label="Service accounts" value={(serviceAccounts.value || []).length} />
        <Metric label="Tokens" value={(tokens.value || []).length} />
        <Metric label="OAuth clients" value={(oauthClients.value || []).length} />
      </div>
      <div className="two-col">
        <Panel title="Create Auth Provider" action={<button onClick={submitProvider} disabled={!providerForm.name.trim()}>Create</button>}>
          <div className="metadata-edit-grid">
            <TextField label="Name" value={providerForm.name} onChange={(value) => setProviderForm({ ...providerForm, name: value })} placeholder="Corporate SSO" />
            <SelectField
              label="Protocol"
              value={providerForm.protocol}
              onChange={(value) => setProviderForm({ ...providerForm, protocol: value })}
              options={toOptions(PROTOCOLS)}
            />
          </div>
        </Panel>
        <Panel title="Auth Providers" action={<button onClick={reload}>Refresh</button>}>
          <DataTable rows={providers.value || []} empty="No auth providers yet." />
        </Panel>
      </div>
      <div className="two-col">
        <Panel title="Create Worker Service Account" action={<button onClick={submitServiceAccount} disabled={!serviceForm.id.trim() || !serviceForm.displayName.trim()}>Create</button>}>
          <div className="metadata-edit-grid">
            <TextField label="Service account ID" value={serviceForm.id} onChange={(value) => setServiceForm({ ...serviceForm, id: value })} placeholder="pipeline-worker-prod" />
            <TextField label="Display name" value={serviceForm.displayName} onChange={(value) => setServiceForm({ ...serviceForm, displayName: value })} placeholder="Production pipeline worker" />
            <TextField label="Organization ID" value={serviceForm.organizationId} onChange={(value) => setServiceForm({ ...serviceForm, organizationId: value })} placeholder="acme" />
          </div>
        </Panel>
        <Panel title="Issue Project Worker Token" action={<button onClick={submitWorkerToken} disabled={!tokenForm.principalId || !tokenForm.projectId.trim()}>Issue once</button>}>
          <div className="metadata-edit-grid">
            <SelectField label="Service account" value={tokenForm.principalId} onChange={(value) => setTokenForm({ ...tokenForm, principalId: value })} placeholder="Choose account" options={(serviceAccounts.value || []).map((account) => ({ value: account.id, label: account.display_name }))} />
            <TextField label="Project ID" value={tokenForm.projectId} onChange={(value) => setTokenForm({ ...tokenForm, projectId: value })} placeholder="operations" />
            <TextField label="Lifetime (hours)" value={tokenForm.ttlHours} onChange={(value) => setTokenForm({ ...tokenForm, ttlHours: value })} type="number" />
          </div>
          {issuedToken ? <div className="one-time-secret" role="status">
            <strong>Copy this token now</strong>
            <span>It is shown once and cannot be retrieved again.</span>
            <div><input aria-label="One-time worker token" readOnly value={issuedToken.token} /><button onClick={() => navigator.clipboard.writeText(issuedToken.token)}>Copy</button></div>
          </div> : null}
        </Panel>
      </div>
      <div className="two-col">
        <Panel title="Service Accounts">
          <DataTable rows={serviceAccounts.value || []} empty="No service accounts yet." />
        </Panel>
        <Panel title="API Tokens" action={<div className="button-row"><select aria-label="Token to revoke" value={revokeTokenId} onChange={(event) => setRevokeTokenId(event.target.value)}><option value="">Choose token</option>{(tokens.value || []).filter((token) => !token.revoked).map((token) => <option key={token.id} value={token.id}>{token.token_prefix || token.id}</option>)}</select><button onClick={revokeWorkerToken} disabled={!revokeTokenId}>Revoke</button></div>}>
          <DataTable rows={tokens.value || []} empty="No tokens issued yet." />
        </Panel>
      </div>
      <Panel title="OAuth Clients">
        <DataTable rows={oauthClients.value || []} empty="No OAuth clients yet." />
      </Panel>
    </>
  );
}

// ---------------------------------------------------------------------------
// Usage: summary, quotas, quota checks
// ---------------------------------------------------------------------------
function UsageSection() {
  const [refreshKey, setRefreshKey] = useState(0);
  const [summaryKey, setSummaryKey] = useState(0);
  const [error, setError] = useState("");

  const [summaryFilters, setSummaryFilters] = useState({ project: "", metric: "", group_by: "project" });
  const summary = useAsyncState<admin.UsageSummary>(
    () =>
      admin.getUsageSummary({
        project: summaryFilters.project || undefined,
        metric: summaryFilters.metric || undefined,
        group_by: summaryFilters.group_by || undefined
      }),
    [summaryKey]
  );
  const quotas = useAsyncState<admin.UsageQuota[]>(admin.listQuotas, [refreshKey]);

  const [quotaForm, setQuotaForm] = useState({ scope_type: "project", scope_id: "", metric: "compute_seconds", limit_value: "" });
  const [checkForm, setCheckForm] = useState({ scope_type: "project", scope_id: "", metric: "compute_seconds" });
  const [checkResult, setCheckResult] = useState<admin.QuotaCheckResult | null>(null);

  const reload = () => setRefreshKey((key) => key + 1);

  async function submitQuota() {
    if (!quotaForm.scope_id.trim() || !quotaForm.limit_value.trim()) return;
    try {
      await admin.createQuota({
        scope_type: quotaForm.scope_type,
        scope_id: quotaForm.scope_id.trim(),
        metric: quotaForm.metric,
        limit_value: Number(quotaForm.limit_value)
      });
      setQuotaForm({ scope_type: "project", scope_id: "", metric: "compute_seconds", limit_value: "" });
      setError("");
      reload();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function runCheck() {
    if (!checkForm.scope_id.trim()) return;
    try {
      const result = await admin.checkQuota({
        scope_type: checkForm.scope_type,
        scope_id: checkForm.scope_id.trim(),
        metric: checkForm.metric
      });
      setCheckResult(result);
      setError("");
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <>
      <ErrorBanner message={error || summary.error || quotas.error} />
      {(summary.loading || quotas.loading) && <LoadingState label="Loading usage data..." />}
      <div className="grid metrics">
        <Metric label="Total usage" value={summary.value?.total ?? 0} />
        <Metric label="Records" value={summary.value?.record_count ?? 0} />
        <Metric label="Quotas" value={(quotas.value || []).length} />
        <Metric label="Quota check" value={checkResult ? (checkResult.within_limit ? "WITHIN" : "OVER") : "-"} />
      </div>
      <Panel title="Usage Summary" action={<button onClick={() => setSummaryKey((key) => key + 1)}>Run</button>}>
        <div className="metadata-edit-grid">
          <TextField
            label="Project (optional)"
            value={summaryFilters.project}
            onChange={(value) => setSummaryFilters({ ...summaryFilters, project: value })}
            placeholder="project_1"
          />
          <SelectField
            label="Metric (optional)"
            value={summaryFilters.metric}
            onChange={(value) => setSummaryFilters({ ...summaryFilters, metric: value })}
            options={toOptions(USAGE_METRICS)}
            placeholder="All metrics"
          />
          <SelectField
            label="Group by"
            value={summaryFilters.group_by}
            onChange={(value) => setSummaryFilters({ ...summaryFilters, group_by: value })}
            options={toOptions(GROUP_BY)}
          />
        </div>
        <DataTable rows={summary.value?.breakdown || []} empty="No usage records for these filters." />
      </Panel>
      <div className="two-col">
        <Panel
          title="Create Quota"
          action={<button onClick={submitQuota} disabled={!quotaForm.scope_id.trim() || !quotaForm.limit_value.trim()}>Create</button>}
        >
          <div className="metadata-edit-grid">
            <SelectField
              label="Scope type"
              value={quotaForm.scope_type}
              onChange={(value) => setQuotaForm({ ...quotaForm, scope_type: value })}
              options={toOptions(QUOTA_SCOPES)}
            />
            <TextField label="Scope id" value={quotaForm.scope_id} onChange={(value) => setQuotaForm({ ...quotaForm, scope_id: value })} placeholder="project_1" />
            <SelectField
              label="Metric"
              value={quotaForm.metric}
              onChange={(value) => setQuotaForm({ ...quotaForm, metric: value })}
              options={toOptions(USAGE_METRICS)}
            />
            <TextField
              label="Limit value"
              type="number"
              value={quotaForm.limit_value}
              onChange={(value) => setQuotaForm({ ...quotaForm, limit_value: value })}
              placeholder="1000"
            />
          </div>
        </Panel>
        <Panel title="Quotas" action={<button onClick={reload}>Refresh</button>}>
          <DataTable rows={quotas.value || []} empty="No quotas configured yet." />
        </Panel>
      </div>
      <div className="two-col">
        <Panel title="Check Quota" action={<button onClick={runCheck} disabled={!checkForm.scope_id.trim()}>Check</button>}>
          <div className="metadata-edit-grid">
            <SelectField
              label="Scope type"
              value={checkForm.scope_type}
              onChange={(value) => setCheckForm({ ...checkForm, scope_type: value })}
              options={toOptions(QUOTA_SCOPES)}
            />
            <TextField label="Scope id" value={checkForm.scope_id} onChange={(value) => setCheckForm({ ...checkForm, scope_id: value })} placeholder="project_1" />
            <SelectField
              label="Metric"
              value={checkForm.metric}
              onChange={(value) => setCheckForm({ ...checkForm, metric: value })}
              options={toOptions(USAGE_METRICS)}
            />
          </div>
        </Panel>
        <Panel title="Quota Check Result">
          {checkResult ? (
            <>
              <div className="manager-chip-row">
                <StatusBadge value={checkResult.within_limit ? "within limit" : "over limit"} />
              </div>
              <KeyValueGrid data={checkResult} />
            </>
          ) : (
            <EmptyState title="No quota check run" description="Compare current usage against a configured quota." />
          )}
        </Panel>
      </div>
    </>
  );
}

async function fileBase64(file: File): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = "";
  const chunk = 0x8000;
  for (let index = 0; index < bytes.length; index += chunk) {
    binary += String.fromCharCode(...bytes.subarray(index, index + chunk));
  }
  return btoa(binary);
}

function RecoverySection() {
  const [snapshot, setSnapshot] = useState<admin.PortableSnapshot | null>(null);
  const [validation, setValidation] = useState<admin.SnapshotValidation | null>(null);
  const [result, setResult] = useState<admin.SnapshotImportResult | null>(null);
  const [confirmation, setConfirmation] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  async function downloadSnapshot() {
    setBusy("export");
    try {
      const exported = await admin.exportPortableSnapshot();
      setSnapshot(exported);
      const blob = new Blob([JSON.stringify(exported, null, 2)], { type: "application/json" });
      const href = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = href;
      link.download = `ontology-platform-${new Date().toISOString().replace(/[:.]/g, "-")}.json`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(href), 1_000);
      setValidation(await admin.validatePortableSnapshot(exported));
      setError("");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy("");
    }
  }

  async function loadSnapshot(file: File | undefined) {
    if (!file) return;
    setBusy("validate");
    setResult(null);
    setConfirmation("");
    try {
      const parsed = JSON.parse(await file.text()) as admin.PortableSnapshot;
      const checked = await admin.validatePortableSnapshot(parsed);
      setSnapshot(parsed);
      setValidation(checked);
      setError("");
    } catch (err) {
      setSnapshot(null);
      setValidation(null);
      setError(errorMessage(err));
    } finally {
      setBusy("");
    }
  }

  async function runRestore(dryRun: boolean) {
    if (!snapshot) return;
    setBusy(dryRun ? "dry-run" : "restore");
    try {
      const next = await admin.importPortableSnapshot(snapshot, dryRun);
      setResult(next);
      setValidation(next.validation);
      if (!dryRun) setConfirmation("");
      setError("");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy("");
    }
  }

  return (
    <>
      <ErrorBanner message={error} />
      <div className="two-col">
        <Panel title="Portable Snapshot" action={<button onClick={downloadSnapshot} disabled={Boolean(busy)}>{busy === "export" ? "Exporting..." : "Download snapshot"}</button>}>
          <p className="panel-description">Exports versioned platform resources with a SHA-256 integrity manifest. Runtime credentials and login sessions are excluded.</p>
          <label className="file-picker">
            <span>Load snapshot for recovery</span>
            <input type="file" accept="application/json,.json" onChange={(event) => loadSnapshot(event.target.files?.[0])} />
          </label>
          {snapshot ? <KeyValueGrid data={{
            format: snapshot.snapshot_format,
            version: snapshot.snapshot_version,
            resources: snapshot.integrity?.resource_count,
            checksum: snapshot.integrity?.checksum,
            exported_at: new Date(snapshot.exported_at * 1000).toLocaleString()
          }} /> : <EmptyState title="No snapshot loaded" description="Download the current state or choose a portable JSON snapshot to validate." />}
        </Panel>
        <Panel title="Recovery Validation" action={validation ? <StatusBadge value={validation.status} /> : undefined}>
          {busy === "validate" ? <LoadingState label="Validating snapshot..." /> : null}
          {validation ? <>
            <div className="metric-grid compact-metrics">
              <Metric label="Resources" value={validation.resource_count} />
              <Metric label="Credential rebinds" value={validation.rebind_required.length} />
              <Metric label="Errors" value={validation.errors.length} />
            </div>
            {validation.errors.map((message) => <div key={message} className="inline-alert error">{message}</div>)}
            {validation.warnings.map((message) => <div key={message} className="inline-alert warning">{message}</div>)}
            {validation.rebind_required.length ? <DataTable rows={validation.rebind_required} empty="No credential rebinds required." /> : null}
          </> : <EmptyState title="Validation required" description="A snapshot must pass integrity validation before dry run or restore." />}
        </Panel>
      </div>
      <Panel title="Restore Controls">
        <p className="panel-description">Dry run first. Restore uses transactional merge semantics and preserves existing credential bindings when the portable snapshot contains redacted values.</p>
        <div className="recovery-action-row">
          <button onClick={() => runRestore(true)} disabled={!snapshot || validation?.status !== "VALID" || Boolean(busy)}>{busy === "dry-run" ? "Checking..." : "Run dry run"}</button>
          <label><span>Type RESTORE to confirm</span><input value={confirmation} onChange={(event) => setConfirmation(event.target.value)} /></label>
          <button className="danger-button" onClick={() => runRestore(false)} disabled={!snapshot || validation?.status !== "VALID" || confirmation !== "RESTORE" || Boolean(busy)}>{busy === "restore" ? "Restoring..." : "Restore snapshot"}</button>
          {result ? <StatusBadge value={result.status} /> : null}
        </div>
      </Panel>
    </>
  );
}

function ExtensionsSection() {
  const [projectId, setProjectId] = useState("default");
  const [refreshKey, setRefreshKey] = useState(0);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const catalog = useAsyncState(() => admin.getPluginCatalog(projectId), [projectId, refreshKey]);
  const [selected, setSelected] = useState<admin.PluginVersion | null>(null);
  const [executions, setExecutions] = useState<admin.PluginExecution[]>([]);
  const [keyForm, setKeyForm] = useState({ id: "", organization_id: "local", display_name: "" });
  const [publicKeyFile, setPublicKeyFile] = useState<File | null>(null);
  const [packageForm, setPackageForm] = useState({ signer_key_id: "" });
  const [manifestFile, setManifestFile] = useState<File | null>(null);
  const [bundleFile, setBundleFile] = useState<File | null>(null);
  const [signatureFile, setSignatureFile] = useState<File | null>(null);
  const [registered, setRegistered] = useState<admin.PluginVersion | null>(null);
  const [operation, setOperation] = useState("");
  const [operationInput, setOperationInput] = useState<Record<string, string>>({});
  const [invoking, setInvoking] = useState(false);

  function reload() {
    setRefreshKey((value) => value + 1);
  }

  async function encodedKey(file: File, expectedBytes: number): Promise<string> {
    const bytes = new Uint8Array(await file.arrayBuffer());
    if (bytes.length === expectedBytes) return fileBase64(file);
    return new TextDecoder().decode(bytes).trim();
  }

  async function saveTrustKey() {
    if (!publicKeyFile) return;
    try {
      await admin.createPluginTrustKey({
        id: keyForm.id.trim() || undefined,
        organization_id: keyForm.organization_id.trim(),
        display_name: keyForm.display_name.trim(),
        public_key: await encodedKey(publicKeyFile, 32)
      });
      setError("");
      setNotice("Trust key registered. Signed packages from this vendor can now be verified.");
      setPackageForm({ signer_key_id: keyForm.id.trim() });
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function registerPackage() {
    if (!manifestFile || !bundleFile || !signatureFile) return;
    try {
      const manifest = JSON.parse(await manifestFile.text()) as Record<string, unknown>;
      const next = await admin.registerPlugin({
        project_id: projectId,
        manifest,
        bundle_base64: await fileBase64(bundleFile),
        signer_key_id: packageForm.signer_key_id.trim(),
        signature: await encodedKey(signatureFile, 64)
      });
      setRegistered(next);
      setError("");
      setNotice(`${next.plugin_id} ${next.version} passed signature and bundle verification.`);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function activate(version: admin.PluginVersion) {
    try {
      const next = await admin.activatePlugin(version.id);
      setRegistered(next);
      setError("");
      setNotice(`${next.plugin_id} ${next.version} is active.`);
      reload();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function inspect(version: admin.PluginVersion) {
    try {
      const result = await admin.listPluginExecutions(version.id);
      setSelected(version);
      setExecutions(result.executions);
      setOperation(Object.keys(version.operations)[0] || "");
      setOperationInput({});
      setError("");
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  const operationDefinition = selected && operation
    ? (selected.operations[operation] as Record<string, unknown> | undefined)
    : undefined;
  const inputSchema = operationDefinition?.input_schema as Record<string, unknown> | undefined;
  const inputProperties = (inputSchema?.properties as Record<string, Record<string, unknown>> | undefined) || {};
  const requiredInput = new Set(Array.isArray(inputSchema?.required) ? inputSchema.required.map(String) : []);

  async function invokeSelected() {
    if (!selected || !operation) return;
    const input = Object.fromEntries(Object.entries(inputProperties).filter(([name, spec]) => (
      requiredInput.has(name) || spec.type === "boolean" || Boolean(operationInput[name])
    )).map(([name, spec]) => {
      const value = operationInput[name] || "";
      if (spec.type === "integer") return [name, Number.parseInt(value, 10)];
      if (spec.type === "number") return [name, Number(value)];
      if (spec.type === "boolean") return [name, value === "true"];
      return [name, value];
    }));
    try {
      setInvoking(true);
      const run = await admin.invokePluginAsync(selected.id, {
        operation,
        input,
        idempotency_key: crypto.randomUUID(),
        priority: 50,
        max_attempts: 3
      });
      setExecutions((current) => [run, ...current.filter((item) => item.id !== run.id)]);
      setError("");
      setNotice(`${selected.plugin_id} queued as ${run.job_id || run.id}.`);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setInvoking(false);
    }
  }

  const activeRows = (catalog.value?.plugins || []).map((plugin) => ({
    id: plugin.id,
    plugin: plugin.plugin_id,
    version: plugin.version,
    kind: plugin.kind,
    capabilities: plugin.capabilities.join(", ") || "isolated",
    operations: Object.keys(plugin.operations).join(", "),
    status: plugin.status,
    signer: plugin.signer_key_id
  }));

  return (
    <>
      <ErrorBanner message={error || catalog.error} />
      {notice ? <div className="inline-success" role="status">{notice}</div> : null}
      {catalog.loading ? <LoadingState label="Loading signed extensions..." /> : null}
      <Panel title="Extension Scope" action={<button onClick={reload}>Refresh</button>}>
        <div className="metadata-edit-grid">
          <TextField label="Project" value={projectId} onChange={setProjectId} placeholder="default" />
          <div className="key-value"><span>Execution boundary</span><strong>{catalog.value?.runtime || "signed_sandbox_v1"}</strong></div>
          <div className="key-value"><span>SDK API</span><strong>v{catalog.value?.sdk_api_version || 1}</strong></div>
        </div>
      </Panel>
      <div className="two-col">
        <Panel title="Vendor Trust Key" action={<button onClick={saveTrustKey} disabled={!keyForm.organization_id.trim() || !keyForm.display_name.trim() || !publicKeyFile}>Register key</button>}>
          <p className="panel-description">Add an organization-approved Ed25519 public key. Private signing material never enters OntologyOS.</p>
          <div className="metadata-edit-grid">
            <TextField label="Key ID (optional)" value={keyForm.id} onChange={(value) => setKeyForm({ ...keyForm, id: value })} placeholder="vendor-production-2026" />
            <TextField label="Organization" value={keyForm.organization_id} onChange={(value) => setKeyForm({ ...keyForm, organization_id: value })} />
            <TextField label="Vendor" value={keyForm.display_name} onChange={(value) => setKeyForm({ ...keyForm, display_name: value })} />
            <label><span>Ed25519 public key</span><input type="file" accept=".pub,.key,text/plain,application/octet-stream" onChange={(event) => setPublicKeyFile(event.target.files?.[0] || null)} /></label>
          </div>
        </Panel>
        <Panel title="Signed Package" action={<button onClick={registerPackage} disabled={!packageForm.signer_key_id.trim() || !manifestFile || !bundleFile || !signatureFile}>Verify package</button>}>
          <p className="panel-description">The manifest signature and exact bundle digest are checked before an immutable version is registered.</p>
          <div className="metadata-edit-grid">
            <TextField label="Signer key ID" value={packageForm.signer_key_id} onChange={(value) => setPackageForm({ signer_key_id: value })} />
            <label><span>Manifest</span><input type="file" accept="application/json,.json" onChange={(event) => setManifestFile(event.target.files?.[0] || null)} /></label>
            <label><span>Plugin bundle</span><input type="file" accept="application/zip,.zip" onChange={(event) => setBundleFile(event.target.files?.[0] || null)} /></label>
            <label><span>Ed25519 signature</span><input type="file" accept=".sig,text/plain,application/octet-stream" onChange={(event) => setSignatureFile(event.target.files?.[0] || null)} /></label>
          </div>
          {registered ? (
            <div className="runtime-slo-row">
              <span><strong>{registered.plugin_id} {registered.version}</strong><small>{registered.kind} · {registered.status}</small></span>
              <StatusBadge value={registered.status} />
              {registered.status === "VERIFIED" ? <button onClick={() => activate(registered)}>Activate</button> : null}
            </div>
          ) : null}
        </Panel>
      </div>
      <Panel title="Active Extensions" action={<StatusBadge value={`${activeRows.length} active`} />}>
        {activeRows.length ? <DataTable rows={activeRows} empty="No active extensions." /> : <EmptyState title="No active extensions" description="Register a vendor trust key, verify a signed package, then activate its immutable version." />}
        {(catalog.value?.plugins || []).length ? (
          <div className="button-row extension-inspect-actions">
            {(catalog.value?.plugins || []).map((plugin) => <button key={plugin.id} onClick={() => inspect(plugin)}>Runs: {plugin.plugin_id}</button>)}
          </div>
        ) : null}
      </Panel>
      {selected ? (
        <>
          <Panel title={`Run ${selected.plugin_id}`} action={<button onClick={invokeSelected} disabled={!operation || invoking || Object.entries(inputProperties).some(([name, spec]) => requiredInput.has(name) && spec.type !== "boolean" && !operationInput[name])}>{invoking ? "Queueing..." : "Run extension"}</button>}>
            <p className="panel-description">Inputs are generated from the signed operation contract. Execution is queued to the isolated plugin worker and remains recoverable by job ID.</p>
            <div className="metadata-edit-grid">
              <SelectField label="Operation" value={operation} onChange={(value) => { setOperation(value); setOperationInput({}); }} options={toOptions(Object.keys(selected.operations))} />
              {Object.entries(inputProperties).map(([name, spec]) => spec.type === "boolean" ? (
                <SelectField key={name} label={`${name}${requiredInput.has(name) ? " (required)" : ""}`} value={operationInput[name] || "false"} onChange={(value) => setOperationInput({ ...operationInput, [name]: value })} options={toOptions(["false", "true"])} />
              ) : (
                <TextField key={name} label={`${name}${requiredInput.has(name) ? " (required)" : ""}`} value={operationInput[name] || ""} onChange={(value) => setOperationInput({ ...operationInput, [name]: value })} type={spec.type === "integer" || spec.type === "number" ? "number" : "text"} />
              ))}
            </div>
            {!Object.keys(inputProperties).length ? <p className="muted-copy">This operation has no declared input fields.</p> : null}
          </Panel>
          <Panel title={`${selected.plugin_id} execution evidence`} action={<div className="button-row"><StatusBadge value={selected.status} /><button onClick={() => inspect(selected)}>Refresh runs</button></div>}>
            <DataTable rows={executions.map((run) => ({ id: run.id, job_id: run.job_id || "direct", operation: run.operation, status: run.status, duration_ms: run.duration_ms, sandbox: String(run.sandbox.mode || (run.status === "QUEUED" ? "pending" : "unknown")), error: run.error || "", actor: run.actor, created_at: run.created_at }))} empty="This extension has not run yet." />
          </Panel>
        </>
      ) : null}
    </>
  );
}

function RuntimeOperationsSection() {
  const [projectId, setProjectId] = useState("default");
  const [refreshKey, setRefreshKey] = useState(0);
  const [error, setError] = useState("");
  const summary = useAsyncState(() => admin.getRuntimeSummary(projectId), [projectId, refreshKey]);
  const jobs = useAsyncState(() => admin.listRuntimeJobs(projectId), [projectId, refreshKey]);
  const budgets = useAsyncState(() => admin.listRuntimeBudgets(projectId), [projectId, refreshKey]);
  const slos = useAsyncState(() => admin.listRuntimeSlos(projectId), [projectId, refreshKey]);
  const fleet = useAsyncState(() => admin.getWorkerFleet(projectId), [projectId, refreshKey]);
  const [budgetForm, setBudgetForm] = useState({ metric: "executions", limit_value: "1000", window_seconds: "86400", enforcement: "HARD" });
  const [sloForm, setSloForm] = useState({ display_name: "Runtime availability", job_type: "", metric: "availability", operator: "gte", threshold: "0.99", window_seconds: "86400", severity: "warning" });
  const [workerForm, setWorkerForm] = useState({ worker_name: "pipeline-worker-1", job_types: "pipeline.preview,pipeline.deliver", max_concurrency: "2" });
  const [queueForm, setQueueForm] = useState({ weight: "1", max_concurrency: "10", paused: false });

  const reload = () => setRefreshKey((key) => key + 1);

  async function saveBudget() {
    try {
      await admin.upsertRuntimeBudget({
        project_id: projectId,
        metric: budgetForm.metric,
        limit_value: Number(budgetForm.limit_value),
        window_seconds: Number(budgetForm.window_seconds),
        enforcement: budgetForm.enforcement,
        enabled: true
      });
      setError("");
      reload();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function saveSlo() {
    try {
      await admin.createRuntimeSlo({
        project_id: projectId,
        display_name: sloForm.display_name,
        job_type: sloForm.job_type || null,
        metric: sloForm.metric,
        operator: sloForm.operator,
        threshold: Number(sloForm.threshold),
        window_seconds: Number(sloForm.window_seconds),
        severity: sloForm.severity,
        enabled: true
      });
      setError("");
      reload();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function evaluate(policyId: string) {
    try {
      await admin.evaluateRuntimeSlo(policyId);
      setError("");
      reload();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function saveWorker() {
    try {
      await admin.registerRuntimeWorker(workerForm.worker_name, {
        project_id: projectId,
        supported_job_types: splitList(workerForm.job_types),
        max_concurrency: Number(workerForm.max_concurrency),
        labels: { pool: "default" }
      });
      setError("");
      reload();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function setDrain(workerName: string, draining: boolean) {
    try {
      await admin.setRuntimeWorkerDrain(workerName, draining);
      setError("");
      reload();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function saveQueuePolicy() {
    try {
      await admin.upsertRuntimeQueuePolicy(projectId, {
        weight: Number(queueForm.weight),
        max_concurrency: Number(queueForm.max_concurrency),
        paused: queueForm.paused
      });
      setError("");
      reload();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  const loading = summary.loading || jobs.loading || budgets.loading || slos.loading || fleet.loading;
  return (
    <>
      <ErrorBanner message={error || summary.error || jobs.error || budgets.error || slos.error || fleet.error} />
      {loading && <LoadingState label="Loading runtime operations..." />}
      <Panel title="Runtime Scope" action={<button onClick={reload}>Refresh</button>}>
        <div className="metadata-edit-grid">
          <TextField label="Project" value={projectId} onChange={setProjectId} placeholder="default" />
        </div>
      </Panel>
      <div className="grid metrics">
        <Metric label="Availability" value={`${Math.round((summary.value?.availability || 0) * 10000) / 100}%`} />
        <Metric label="P95 execution" value={`${summary.value?.latency_p95_ms || 0} ms`} />
        <Metric label="P95 queue" value={`${summary.value?.queue_p95_ms || 0} ms`} />
        <Metric label="Estimated cost" value={`$${(summary.value?.estimated_cost_usd || 0).toFixed(4)}`} />
        <Metric label="Active workers" value={fleet.value?.summary.active || 0} />
        <Metric label="Active jobs" value={fleet.value?.summary.active_jobs || 0} />
      </div>
      {(summary.value?.warnings || []).map((warning) => <ErrorBanner key={warning} message={warning} />)}
      {(fleet.value?.warnings || []).map((warning) => <ErrorBanner key={warning} message={warning} />)}
      <Panel title="Durable Job Telemetry">
        <DataTable rows={jobs.value || []} empty="No durable jobs have run in this project." />
      </Panel>
      <div className="two-col">
        <Panel title="Worker Fleet" action={<button onClick={saveWorker} disabled={!workerForm.worker_name.trim() || Number(workerForm.max_concurrency) < 1}>Register worker</button>}>
          <div className="metadata-edit-grid">
            <TextField label="Worker name" value={workerForm.worker_name} onChange={(value) => setWorkerForm({ ...workerForm, worker_name: value })} />
            <TextField label="Job types" value={workerForm.job_types} onChange={(value) => setWorkerForm({ ...workerForm, job_types: value })} placeholder="pipeline.preview,agent.invoke" />
            <TextField label="Concurrency" type="number" value={workerForm.max_concurrency} onChange={(value) => setWorkerForm({ ...workerForm, max_concurrency: value })} />
          </div>
          {fleet.value?.sections.workers.length ? (
            <div className="runtime-slo-list">
              {fleet.value.sections.workers.map((worker) => (
                <div key={worker.id} className="runtime-slo-row runtime-worker-row">
                  <span><strong>{worker.worker_name}</strong><small>{worker.active_jobs}/{worker.max_concurrency} jobs · {worker.supported_job_types.join(", ") || "all job types"}</small></span>
                  <StatusBadge value={worker.status} />
                  <button onClick={() => setDrain(worker.worker_name, worker.configured_status === "ACTIVE")}>
                    {worker.configured_status === "ACTIVE" ? "Drain" : "Resume"}
                  </button>
                </div>
              ))}
            </div>
          ) : <EmptyState title="No workers registered" description="Register a project-scoped worker before enabling scheduled execution." />}
        </Panel>
        <Panel title="Queue Policy" action={<button onClick={saveQueuePolicy} disabled={!projectId || Number(queueForm.max_concurrency) < 1}>Save policy</button>}>
          <div className="metadata-edit-grid">
            <TextField label="Fair-share weight" type="number" value={queueForm.weight} onChange={(value) => setQueueForm({ ...queueForm, weight: value })} />
            <TextField label="Project concurrency" type="number" value={queueForm.max_concurrency} onChange={(value) => setQueueForm({ ...queueForm, max_concurrency: value })} />
            <CheckboxField label="Pause new claims" checked={queueForm.paused} onChange={(value) => setQueueForm({ ...queueForm, paused: value })} />
          </div>
          <DataTable rows={fleet.value?.sections.queue_policies || []} empty="This project uses the default fair-share queue policy." />
        </Panel>
      </div>
      <div className="two-col">
        <Panel title="Project Budgets" action={<button onClick={saveBudget} disabled={!projectId || Number(budgetForm.limit_value) <= 0}>Save budget</button>}>
          <div className="metadata-edit-grid">
            <SelectField label="Metric" value={budgetForm.metric} onChange={(value) => setBudgetForm({ ...budgetForm, metric: value })} options={toOptions(RUNTIME_METRICS)} />
            <TextField label="Limit" type="number" value={budgetForm.limit_value} onChange={(value) => setBudgetForm({ ...budgetForm, limit_value: value })} />
            <TextField label="Window seconds" type="number" value={budgetForm.window_seconds} onChange={(value) => setBudgetForm({ ...budgetForm, window_seconds: value })} />
            <SelectField label="Enforcement" value={budgetForm.enforcement} onChange={(value) => setBudgetForm({ ...budgetForm, enforcement: value })} options={toOptions(["HARD", "WARN"])} />
          </div>
          <DataTable rows={budgets.value || []} empty="No runtime budgets configured." />
        </Panel>
        <Panel title="Service Objectives" action={<button onClick={saveSlo} disabled={!sloForm.display_name.trim()}>Create SLO</button>}>
          <div className="metadata-edit-grid">
            <TextField label="Name" value={sloForm.display_name} onChange={(value) => setSloForm({ ...sloForm, display_name: value })} />
            <TextField label="Job type (optional)" value={sloForm.job_type} onChange={(value) => setSloForm({ ...sloForm, job_type: value })} placeholder="pipeline.preview" />
            <SelectField label="Metric" value={sloForm.metric} onChange={(value) => setSloForm({ ...sloForm, metric: value })} options={toOptions(SLO_METRICS)} />
            <SelectField label="Operator" value={sloForm.operator} onChange={(value) => setSloForm({ ...sloForm, operator: value })} options={[{ value: "gte", label: "At least" }, { value: "lte", label: "At most" }]} />
            <TextField label="Threshold" type="number" value={sloForm.threshold} onChange={(value) => setSloForm({ ...sloForm, threshold: value })} />
            <TextField label="Window seconds" type="number" value={sloForm.window_seconds} onChange={(value) => setSloForm({ ...sloForm, window_seconds: value })} />
          </div>
          {slos.value?.length ? (
            <div className="runtime-slo-list">
              {slos.value.map((slo) => (
                <div key={slo.id} className="runtime-slo-row">
                  <span><strong>{slo.display_name}</strong><small>{slo.metric} {slo.operator} {slo.threshold}</small></span>
                  <StatusBadge value={slo.severity} />
                  <button onClick={() => evaluate(slo.id)}>Evaluate</button>
                </div>
              ))}
            </div>
          ) : <EmptyState title="No SLOs configured" description="Create an availability, latency, queue, cost, or throughput objective." />}
        </Panel>
      </div>
    </>
  );
}
