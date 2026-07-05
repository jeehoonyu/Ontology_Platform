import { useState, type ReactNode } from "react";
import {
  DataTable,
  DeveloperEvidence,
  ErrorBanner,
  KeyValueGrid,
  LoadingState,
  Metric,
  Panel,
  StatusBadge
} from "../components/data/DataDisplay";
import { useAsyncState } from "../hooks/useAsyncState";
import { classNames } from "../utils/format";
import {
  assignResourceMarking,
  checkClassificationAccess,
  checkProjectAccess,
  cipherDecrypt,
  cipherEncrypt,
  cipherHash,
  createCipherChannel,
  createClassification,
  createClearance,
  createMarking,
  createProject,
  createProjectGrant,
  createRole,
  createScheme,
  decideAccess,
  grantMarking,
  listCipherChannels,
  listClassifications,
  listMarkings,
  listProjectGrants,
  listProjects,
  listRoles,
  listSchemes,
  type AccessDecisionResult,
  type ClassificationCheckResult,
  type ClearanceResult,
  type DecryptResult,
  type EncryptResult,
  type HashResult,
  type ProjectAccessCheckResult
} from "../api/securityApi";

const TABS = [
  { id: "markings", label: "Markings" },
  { id: "classification", label: "Classification / CBAC" },
  { id: "projects", label: "Projects & Roles" },
  { id: "cipher", label: "Cipher" }
] as const;

type TabId = (typeof TABS)[number]["id"];

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

function csv(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function parseGroups(text: string): string[][] {
  return text
    .split("\n")
    .map((line) => csv(line))
    .filter((group) => group.length > 0);
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label>
      <span>{label}</span>
      {children}
    </label>
  );
}

function DecisionBanner({ allowed, detail }: { allowed: boolean; detail: string }) {
  return (
    <div className="button-row" style={{ alignItems: "center", gap: 10 }}>
      <StatusBadge value={allowed ? "allowed" : "denied"} />
      <strong>{allowed ? "ALLOWED" : "DENIED"}</strong>
      <span>{detail}</span>
    </div>
  );
}

export function Security() {
  const [tab, setTab] = useState<TabId>("markings");
  const [refreshKey, setRefreshKey] = useState(0);
  const bump = () => setRefreshKey((key) => key + 1);

  return (
    <section className="workbench-page">
      <header className="workspace-header">
        <div>
          <span>SG</span>
          <strong>Security &amp; Governance</strong>
        </div>
        <nav>
          {TABS.map((item) => (
            <button
              key={item.id}
              className={classNames(tab === item.id && "active")}
              onClick={() => setTab(item.id)}
            >
              {item.label}
            </button>
          ))}
        </nav>
        <div className="button-row">
          <button onClick={bump}>Refresh</button>
        </div>
      </header>
      {tab === "markings" && <MarkingsSection refreshKey={refreshKey} onChange={bump} />}
      {tab === "classification" && <ClassificationSection refreshKey={refreshKey} onChange={bump} />}
      {tab === "projects" && <ProjectsSection refreshKey={refreshKey} onChange={bump} />}
      {tab === "cipher" && <CipherSection refreshKey={refreshKey} onChange={bump} />}
    </section>
  );
}

interface SectionProps {
  refreshKey: number;
  onChange: () => void;
}

// ---------------------------------------------------------------------------
// Markings
// ---------------------------------------------------------------------------

function MarkingsSection({ refreshKey, onChange }: SectionProps) {
  const markings = useAsyncState(listMarkings, [refreshKey]);
  const [error, setError] = useState("");

  const [newMarking, setNewMarking] = useState({ display_name: "", category: "PII", description: "" });
  const [grant, setGrant] = useState({ marking_id: "", principal: "" });
  const [resource, setResource] = useState({ resource_id: "", marking_id: "", actor: "" });
  const [decision, setDecision] = useState({ principal: "", resource_id: "" });
  const [decisionResult, setDecisionResult] = useState<AccessDecisionResult | null>(null);

  const markingOptions = markings.value || [];

  async function run(fn: () => Promise<void>) {
    setError("");
    try {
      await fn();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <>
      <ErrorBanner message={error || markings.error} />
      {markings.loading && <LoadingState label="Loading markings..." />}
      <div className="grid metrics">
        <Metric label="Markings" value={markingOptions.length} />
      </div>
      <div className="two-col">
        <Panel title="Markings">
          <DataTable rows={markingOptions} empty="No markings yet." />
        </Panel>
        <Panel title="Create Marking">
          <div className="metadata-edit-grid">
            <Field label="Display name">
              <input
                value={newMarking.display_name}
                onChange={(event) => setNewMarking({ ...newMarking, display_name: event.target.value })}
                placeholder="Personally Identifiable Information"
              />
            </Field>
            <Field label="Category">
              <input
                value={newMarking.category}
                onChange={(event) => setNewMarking({ ...newMarking, category: event.target.value })}
                placeholder="PII / PHI / SECRET / CUI"
              />
            </Field>
            <Field label="Description">
              <input
                value={newMarking.description}
                onChange={(event) => setNewMarking({ ...newMarking, description: event.target.value })}
              />
            </Field>
            <div className="button-row">
              <button
                disabled={!newMarking.display_name || !newMarking.category}
                onClick={() =>
                  run(async () => {
                    await createMarking({
                      display_name: newMarking.display_name,
                      category: newMarking.category,
                      description: newMarking.description || undefined
                    });
                    setNewMarking({ display_name: "", category: "PII", description: "" });
                    onChange();
                  })
                }
              >
                Create marking
              </button>
            </div>
          </div>
        </Panel>
      </div>
      <div className="two-col">
        <Panel title="Grant Marking to Principal">
          <div className="metadata-edit-grid">
            <Field label="Marking">
              <select value={grant.marking_id} onChange={(event) => setGrant({ ...grant, marking_id: event.target.value })}>
                <option value="">Choose marking</option>
                {markingOptions.map((marking) => (
                  <option key={marking.id} value={marking.id}>
                    {marking.display_name} ({marking.id})
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Principal">
              <input
                value={grant.principal}
                onChange={(event) => setGrant({ ...grant, principal: event.target.value })}
                placeholder="user:alice or group:analysts"
              />
            </Field>
            <div className="button-row">
              <button
                disabled={!grant.marking_id || !grant.principal}
                onClick={() =>
                  run(async () => {
                    await grantMarking(grant.marking_id, grant.principal);
                    setGrant({ marking_id: "", principal: "" });
                    onChange();
                  })
                }
              >
                Grant marking
              </button>
            </div>
          </div>
        </Panel>
        <Panel title="Assign Marking to Resource">
          <div className="metadata-edit-grid">
            <Field label="Resource id">
              <input
                value={resource.resource_id}
                onChange={(event) => setResource({ ...resource, resource_id: event.target.value })}
                placeholder="dataset id"
              />
            </Field>
            <Field label="Marking">
              <select value={resource.marking_id} onChange={(event) => setResource({ ...resource, marking_id: event.target.value })}>
                <option value="">Choose marking</option>
                {markingOptions.map((marking) => (
                  <option key={marking.id} value={marking.id}>
                    {marking.display_name} ({marking.id})
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Actor (optional, enforces APPLY)">
              <input
                value={resource.actor}
                onChange={(event) => setResource({ ...resource, actor: event.target.value })}
                placeholder="leave blank to skip enforcement"
              />
            </Field>
            <div className="button-row">
              <button
                disabled={!resource.resource_id || !resource.marking_id}
                onClick={() =>
                  run(async () => {
                    await assignResourceMarking({
                      resource_id: resource.resource_id,
                      marking_id: resource.marking_id,
                      actor: resource.actor || undefined
                    });
                    setResource({ resource_id: "", marking_id: "", actor: "" });
                    onChange();
                  })
                }
              >
                Assign marking
              </button>
            </div>
          </div>
        </Panel>
      </div>
      <Panel title="Access Decision (resource markings vs. principal grants)">
        <div className="metadata-edit-grid">
          <Field label="Principal">
            <input
              value={decision.principal}
              onChange={(event) => setDecision({ ...decision, principal: event.target.value })}
              placeholder="user:alice"
            />
          </Field>
          <Field label="Resource id">
            <input
              value={decision.resource_id}
              onChange={(event) => setDecision({ ...decision, resource_id: event.target.value })}
              placeholder="dataset id"
            />
          </Field>
          <div className="button-row">
            <button
              disabled={!decision.principal || !decision.resource_id}
              onClick={() =>
                run(async () => {
                  setDecisionResult(
                    await decideAccess({ principal: decision.principal, resource_id: decision.resource_id })
                  );
                })
              }
            >
              Evaluate access
            </button>
          </div>
        </div>
        {decisionResult ? (
          <>
            <DecisionBanner
              allowed={decisionResult.allowed}
              detail={
                decisionResult.missing_markings.length
                  ? `missing: ${decisionResult.missing_markings.join(", ")}`
                  : "principal holds every required marking"
              }
            />
            <KeyValueGrid
              data={{
                required_markings: decisionResult.required_markings.join(", ") || "none",
                held_markings: decisionResult.held_markings.join(", ") || "none",
                missing_markings: decisionResult.missing_markings.join(", ") || "none"
              }}
            />
          </>
        ) : null}
      </Panel>
    </>
  );
}

// ---------------------------------------------------------------------------
// Classification / CBAC
// ---------------------------------------------------------------------------

function ClassificationSection({ refreshKey, onChange }: SectionProps) {
  const schemes = useAsyncState(listSchemes, [refreshKey]);
  const classifications = useAsyncState(listClassifications, [refreshKey]);
  const [error, setError] = useState("");

  const [newScheme, setNewScheme] = useState({ display_name: "", levels: "unclassified, confidential, secret, top_secret", groups: "" });
  const [newClassification, setNewClassification] = useState({ scheme_id: "", kind: "data", level: "", categories: "" });
  const [newClearance, setNewClearance] = useState({ principal_id: "", scheme_id: "", max_level: "", categories: "" });
  const [clearanceResult, setClearanceResult] = useState<ClearanceResult | null>(null);
  const [check, setCheck] = useState({ principal_id: "", classification_id: "" });
  const [checkResult, setCheckResult] = useState<ClassificationCheckResult | null>(null);

  const schemeOptions = schemes.value || [];
  const classificationOptions = classifications.value || [];
  const selectedScheme = schemeOptions.find((scheme) => scheme.id === newClassification.scheme_id);

  async function run(fn: () => Promise<void>) {
    setError("");
    try {
      await fn();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <>
      <ErrorBanner message={error || schemes.error || classifications.error} />
      {(schemes.loading || classifications.loading) && <LoadingState label="Loading classification model..." />}
      <div className="grid metrics">
        <Metric label="Schemes" value={schemeOptions.length} />
        <Metric label="Classifications" value={classificationOptions.length} />
      </div>
      <div className="two-col">
        <Panel title="Classification Schemes">
          <DataTable rows={schemeOptions} empty="No schemes yet." />
        </Panel>
        <Panel title="Create Scheme">
          <div className="metadata-edit-grid">
            <Field label="Display name">
              <input
                value={newScheme.display_name}
                onChange={(event) => setNewScheme({ ...newScheme, display_name: event.target.value })}
              />
            </Field>
            <Field label="Levels (low to high, comma separated)">
              <input value={newScheme.levels} onChange={(event) => setNewScheme({ ...newScheme, levels: event.target.value })} />
            </Field>
            <Field label="Category groups (one OR-group per line, comma separated)">
              <textarea
                value={newScheme.groups}
                onChange={(event) => setNewScheme({ ...newScheme, groups: event.target.value })}
                placeholder={"NATO, FVEY\nNOFORN"}
              />
            </Field>
            <div className="button-row">
              <button
                disabled={!newScheme.display_name || csv(newScheme.levels).length === 0}
                onClick={() =>
                  run(async () => {
                    await createScheme({
                      display_name: newScheme.display_name,
                      levels: csv(newScheme.levels),
                      category_groups: parseGroups(newScheme.groups)
                    });
                    setNewScheme({ display_name: "", levels: "", groups: "" });
                    onChange();
                  })
                }
              >
                Create scheme
              </button>
            </div>
          </div>
        </Panel>
      </div>
      <div className="two-col">
        <Panel title="Classifications">
          <DataTable rows={classificationOptions} empty="No classifications yet." />
        </Panel>
        <Panel title="Apply Classification">
          <div className="metadata-edit-grid">
            <Field label="Scheme">
              <select
                value={newClassification.scheme_id}
                onChange={(event) => setNewClassification({ ...newClassification, scheme_id: event.target.value, level: "" })}
              >
                <option value="">Choose scheme</option>
                {schemeOptions.map((scheme) => (
                  <option key={scheme.id} value={scheme.id}>
                    {scheme.display_name} ({scheme.id})
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Kind">
              <select
                value={newClassification.kind}
                onChange={(event) => setNewClassification({ ...newClassification, kind: event.target.value })}
              >
                <option value="file">file</option>
                <option value="data">data</option>
                <option value="project">project</option>
              </select>
            </Field>
            <Field label="Level">
              <select
                value={newClassification.level}
                onChange={(event) => setNewClassification({ ...newClassification, level: event.target.value })}
                disabled={!selectedScheme}
              >
                <option value="">Choose level</option>
                {(selectedScheme?.levels || []).map((level) => (
                  <option key={level} value={level}>
                    {level}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Categories (comma separated)">
              <input
                value={newClassification.categories}
                onChange={(event) => setNewClassification({ ...newClassification, categories: event.target.value })}
              />
            </Field>
            <div className="button-row">
              <button
                disabled={!newClassification.scheme_id || !newClassification.level}
                onClick={() =>
                  run(async () => {
                    await createClassification({
                      scheme_id: newClassification.scheme_id,
                      kind: newClassification.kind,
                      level: newClassification.level,
                      categories: csv(newClassification.categories)
                    });
                    setNewClassification({ scheme_id: "", kind: "data", level: "", categories: "" });
                    onChange();
                  })
                }
              >
                Apply classification
              </button>
            </div>
          </div>
        </Panel>
      </div>
      <div className="two-col">
        <Panel title="Grant Clearance">
          <div className="metadata-edit-grid">
            <Field label="Principal id">
              <input
                value={newClearance.principal_id}
                onChange={(event) => setNewClearance({ ...newClearance, principal_id: event.target.value })}
              />
            </Field>
            <Field label="Scheme">
              <select
                value={newClearance.scheme_id}
                onChange={(event) => setNewClearance({ ...newClearance, scheme_id: event.target.value, max_level: "" })}
              >
                <option value="">Choose scheme</option>
                {schemeOptions.map((scheme) => (
                  <option key={scheme.id} value={scheme.id}>
                    {scheme.display_name} ({scheme.id})
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Max level">
              <select
                value={newClearance.max_level}
                onChange={(event) => setNewClearance({ ...newClearance, max_level: event.target.value })}
                disabled={!newClearance.scheme_id}
              >
                <option value="">Choose level</option>
                {(schemeOptions.find((scheme) => scheme.id === newClearance.scheme_id)?.levels || []).map((level) => (
                  <option key={level} value={level}>
                    {level}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Categories (comma separated)">
              <input
                value={newClearance.categories}
                onChange={(event) => setNewClearance({ ...newClearance, categories: event.target.value })}
              />
            </Field>
            <div className="button-row">
              <button
                disabled={!newClearance.principal_id || !newClearance.scheme_id || !newClearance.max_level}
                onClick={() =>
                  run(async () => {
                    setClearanceResult(
                      await createClearance({
                        principal_id: newClearance.principal_id,
                        scheme_id: newClearance.scheme_id,
                        max_level: newClearance.max_level,
                        categories: csv(newClearance.categories)
                      })
                    );
                    onChange();
                  })
                }
              >
                Grant clearance
              </button>
            </div>
          </div>
          {clearanceResult ? <KeyValueGrid data={{ id: clearanceResult.id, principal_id: clearanceResult.principal_id, max_level: clearanceResult.max_level }} /> : null}
        </Panel>
        <Panel title="Check Access (CBAC)">
          <div className="metadata-edit-grid">
            <Field label="Principal id">
              <input value={check.principal_id} onChange={(event) => setCheck({ ...check, principal_id: event.target.value })} />
            </Field>
            <Field label="Classification">
              <select value={check.classification_id} onChange={(event) => setCheck({ ...check, classification_id: event.target.value })}>
                <option value="">Choose classification</option>
                {classificationOptions.map((cls) => (
                  <option key={cls.id} value={cls.id}>
                    {cls.kind}:{cls.level} ({cls.id})
                  </option>
                ))}
              </select>
            </Field>
            <div className="button-row">
              <button
                disabled={!check.principal_id || !check.classification_id}
                onClick={() =>
                  run(async () => {
                    setCheckResult(
                      await checkClassificationAccess({ principal_id: check.principal_id, classification_id: check.classification_id })
                    );
                  })
                }
              >
                Check access
              </button>
            </div>
          </div>
          {checkResult ? (
            <>
              <DecisionBanner allowed={checkResult.allowed} detail={checkResult.reason} />
              <KeyValueGrid
                data={{
                  reason: checkResult.reason,
                  level_ok: checkResult.level_ok,
                  required_level: checkResult.required_level ?? "n/a",
                  clearance_level: checkResult.clearance_level ?? "n/a",
                  category_failures: checkResult.category_failures.join("; ") || "none"
                }}
              />
            </>
          ) : null}
        </Panel>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Projects & Roles
// ---------------------------------------------------------------------------

function ProjectsSection({ refreshKey, onChange }: SectionProps) {
  const projects = useAsyncState(listProjects, [refreshKey]);
  const roles = useAsyncState(listRoles, [refreshKey]);
  const [error, setError] = useState("");

  const [selectedProject, setSelectedProject] = useState("");
  const grants = useAsyncState(
    () => (selectedProject ? listProjectGrants(selectedProject) : Promise.resolve([])),
    [selectedProject, refreshKey]
  );

  const [newProject, setNewProject] = useState({ display_name: "", description: "", organization: "default" });
  const [newRole, setNewRole] = useState({ display_name: "", permissions: "viewer, editor, owner" });
  const [newGrant, setNewGrant] = useState({ principal: "", role_id: "" });
  const [accessCheck, setAccessCheck] = useState({ project_id: "", principal: "", permission: "" });
  const [accessResult, setAccessResult] = useState<ProjectAccessCheckResult | null>(null);

  const projectOptions = projects.value || [];
  const roleOptions = roles.value || [];

  async function run(fn: () => Promise<void>) {
    setError("");
    try {
      await fn();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <>
      <ErrorBanner message={error || projects.error || roles.error || grants.error} />
      {(projects.loading || roles.loading) && <LoadingState label="Loading projects and roles..." />}
      <div className="grid metrics">
        <Metric label="Projects" value={projectOptions.length} />
        <Metric label="Roles" value={roleOptions.length} />
      </div>
      <div className="two-col">
        <Panel title="Projects">
          <DataTable rows={projectOptions} empty="No projects yet." />
        </Panel>
        <Panel title="Create Project">
          <div className="metadata-edit-grid">
            <Field label="Display name">
              <input value={newProject.display_name} onChange={(event) => setNewProject({ ...newProject, display_name: event.target.value })} />
            </Field>
            <Field label="Description">
              <input value={newProject.description} onChange={(event) => setNewProject({ ...newProject, description: event.target.value })} />
            </Field>
            <Field label="Organization">
              <input value={newProject.organization} onChange={(event) => setNewProject({ ...newProject, organization: event.target.value })} />
            </Field>
            <div className="button-row">
              <button
                disabled={!newProject.display_name}
                onClick={() =>
                  run(async () => {
                    await createProject({
                      display_name: newProject.display_name,
                      description: newProject.description || undefined,
                      organization: newProject.organization || undefined
                    });
                    setNewProject({ display_name: "", description: "", organization: "default" });
                    onChange();
                  })
                }
              >
                Create project
              </button>
            </div>
          </div>
        </Panel>
      </div>
      <div className="two-col">
        <Panel title="Roles">
          <DataTable rows={roleOptions} empty="No roles yet." />
        </Panel>
        <Panel title="Create Role">
          <div className="metadata-edit-grid">
            <Field label="Display name">
              <input value={newRole.display_name} onChange={(event) => setNewRole({ ...newRole, display_name: event.target.value })} />
            </Field>
            <Field label="Permissions (comma separated)">
              <input value={newRole.permissions} onChange={(event) => setNewRole({ ...newRole, permissions: event.target.value })} />
            </Field>
            <div className="button-row">
              <button
                disabled={!newRole.display_name}
                onClick={() =>
                  run(async () => {
                    await createRole({ display_name: newRole.display_name, permissions: csv(newRole.permissions) });
                    setNewRole({ display_name: "", permissions: "" });
                    onChange();
                  })
                }
              >
                Create role
              </button>
            </div>
          </div>
        </Panel>
      </div>
      <div className="two-col">
        <Panel
          title="Project Role Grants"
          action={
            <select value={selectedProject} onChange={(event) => setSelectedProject(event.target.value)}>
              <option value="">Choose project</option>
              {projectOptions.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.display_name} ({project.id})
                </option>
              ))}
            </select>
          }
        >
          {selectedProject ? (
            <>
              <DataTable rows={grants.value || []} empty="No grants on this project yet." />
              <div className="metadata-edit-grid">
                <Field label="Principal">
                  <input value={newGrant.principal} onChange={(event) => setNewGrant({ ...newGrant, principal: event.target.value })} />
                </Field>
                <Field label="Role">
                  <select value={newGrant.role_id} onChange={(event) => setNewGrant({ ...newGrant, role_id: event.target.value })}>
                    <option value="">Choose role</option>
                    {roleOptions.map((role) => (
                      <option key={role.id} value={role.id}>
                        {role.display_name} ({role.id})
                      </option>
                    ))}
                  </select>
                </Field>
                <div className="button-row">
                  <button
                    disabled={!newGrant.principal || !newGrant.role_id}
                    onClick={() =>
                      run(async () => {
                        await createProjectGrant(selectedProject, { principal: newGrant.principal, role_id: newGrant.role_id });
                        setNewGrant({ principal: "", role_id: "" });
                        onChange();
                      })
                    }
                  >
                    Grant role
                  </button>
                </div>
              </div>
            </>
          ) : (
            <div className="empty">Choose a project to view and manage its role grants.</div>
          )}
        </Panel>
        <Panel title="Access Check (project permission)">
          <div className="metadata-edit-grid">
            <Field label="Project">
              <select value={accessCheck.project_id} onChange={(event) => setAccessCheck({ ...accessCheck, project_id: event.target.value })}>
                <option value="">Choose project</option>
                {projectOptions.map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.display_name} ({project.id})
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Principal">
              <input value={accessCheck.principal} onChange={(event) => setAccessCheck({ ...accessCheck, principal: event.target.value })} />
            </Field>
            <Field label="Permission">
              <input
                value={accessCheck.permission}
                onChange={(event) => setAccessCheck({ ...accessCheck, permission: event.target.value })}
                placeholder="viewer / editor / owner"
              />
            </Field>
            <div className="button-row">
              <button
                disabled={!accessCheck.project_id || !accessCheck.principal || !accessCheck.permission}
                onClick={() =>
                  run(async () => {
                    setAccessResult(
                      await checkProjectAccess({
                        project_id: accessCheck.project_id,
                        principal: accessCheck.principal,
                        permission: accessCheck.permission
                      })
                    );
                  })
                }
              >
                Check access
              </button>
            </div>
          </div>
          {accessResult ? (
            <>
              <DecisionBanner
                allowed={accessResult.allowed}
                detail={
                  accessResult.matched_roles.length
                    ? `matched roles: ${accessResult.matched_roles.join(", ")}`
                    : "no role grants matched this permission"
                }
              />
              <KeyValueGrid
                data={{
                  project_id: accessResult.project_id,
                  principal: accessResult.principal,
                  permission: accessResult.permission,
                  matched_roles: accessResult.matched_roles.join(", ") || "none"
                }}
              />
            </>
          ) : null}
        </Panel>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Cipher
// ---------------------------------------------------------------------------

function CipherSection({ refreshKey, onChange }: SectionProps) {
  const channels = useAsyncState(listCipherChannels, [refreshKey]);
  const [error, setError] = useState("");

  const [newChannel, setNewChannel] = useState({
    display_name: "",
    mode: "encrypt",
    key_ref: "",
    algorithm: "AES-GCM",
    require_justification: true
  });
  const [encrypt, setEncrypt] = useState({ channel_id: "", value: "", principal: "" });
  const [encryptResult, setEncryptResult] = useState<EncryptResult | null>(null);
  const [decrypt, setDecrypt] = useState({ channel_id: "", ciphertext: "", principal: "", justification: "" });
  const [decryptResult, setDecryptResult] = useState<DecryptResult | null>(null);
  const [hash, setHash] = useState({ channel_id: "", value: "", algorithm: "sha256", principal: "" });
  const [hashResult, setHashResult] = useState<HashResult | null>(null);

  const channelOptions = channels.value || [];
  const encryptChannels = channelOptions.filter((channel) => channel.mode === "encrypt");

  async function run(fn: () => Promise<void>) {
    setError("");
    try {
      await fn();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <>
      <ErrorBanner message={error || channels.error} />
      {channels.loading && <LoadingState label="Loading cipher channels..." />}
      <div className="grid metrics">
        <Metric label="Channels" value={channelOptions.length} />
      </div>
      <div className="two-col">
        <Panel title="Cipher Channels">
          <DataTable rows={channelOptions} empty="No channels yet." />
        </Panel>
        <Panel title="Create Channel">
          <div className="metadata-edit-grid">
            <Field label="Display name">
              <input value={newChannel.display_name} onChange={(event) => setNewChannel({ ...newChannel, display_name: event.target.value })} />
            </Field>
            <Field label="Mode">
              <select value={newChannel.mode} onChange={(event) => setNewChannel({ ...newChannel, mode: event.target.value })}>
                <option value="encrypt">encrypt</option>
                <option value="tokenize">tokenize</option>
              </select>
            </Field>
            <Field label="Key ref">
              <input
                value={newChannel.key_ref}
                onChange={(event) => setNewChannel({ ...newChannel, key_ref: event.target.value })}
                placeholder="kms:key/pii"
              />
            </Field>
            <Field label="Algorithm">
              <input value={newChannel.algorithm} onChange={(event) => setNewChannel({ ...newChannel, algorithm: event.target.value })} />
            </Field>
            <label className="button-row" style={{ alignItems: "center", gap: 8 }}>
              <input
                type="checkbox"
                checked={newChannel.require_justification}
                onChange={(event) => setNewChannel({ ...newChannel, require_justification: event.target.checked })}
              />
              <span>Require justification on decrypt</span>
            </label>
            <div className="button-row">
              <button
                disabled={!newChannel.display_name || !newChannel.key_ref}
                onClick={() =>
                  run(async () => {
                    await createCipherChannel({
                      display_name: newChannel.display_name,
                      mode: newChannel.mode,
                      key_ref: newChannel.key_ref,
                      algorithm: newChannel.algorithm || undefined,
                      require_justification: newChannel.require_justification
                    });
                    setNewChannel({ display_name: "", mode: "encrypt", key_ref: "", algorithm: "AES-GCM", require_justification: true });
                    onChange();
                  })
                }
              >
                Create channel
              </button>
            </div>
          </div>
        </Panel>
      </div>
      <div className="two-col">
        <Panel title="Encrypt">
          <div className="metadata-edit-grid">
            <Field label="Channel (encrypt mode)">
              <select value={encrypt.channel_id} onChange={(event) => setEncrypt({ ...encrypt, channel_id: event.target.value })}>
                <option value="">Choose channel</option>
                {encryptChannels.map((channel) => (
                  <option key={channel.id} value={channel.id}>
                    {channel.display_name} ({channel.id})
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Plaintext value">
              <input value={encrypt.value} onChange={(event) => setEncrypt({ ...encrypt, value: event.target.value })} />
            </Field>
            <Field label="Principal (optional, enforces license)">
              <input value={encrypt.principal} onChange={(event) => setEncrypt({ ...encrypt, principal: event.target.value })} />
            </Field>
            <div className="button-row">
              <button
                disabled={!encrypt.channel_id || !encrypt.value}
                onClick={() =>
                  run(async () => {
                    setEncryptResult(
                      await cipherEncrypt({
                        channel_id: encrypt.channel_id,
                        value: encrypt.value,
                        principal: encrypt.principal || undefined
                      })
                    );
                  })
                }
              >
                Encrypt
              </button>
              {encryptResult ? (
                <button onClick={() => setDecrypt({ ...decrypt, channel_id: encrypt.channel_id, ciphertext: encryptResult.ciphertext })}>
                  Send to decrypt
                </button>
              ) : null}
            </div>
          </div>
          {encryptResult ? <KeyValueGrid data={{ ciphertext: encryptResult.ciphertext }} /> : null}
        </Panel>
        <Panel title="Decrypt (justification audited)">
          <div className="metadata-edit-grid">
            <Field label="Channel (encrypt mode)">
              <select value={decrypt.channel_id} onChange={(event) => setDecrypt({ ...decrypt, channel_id: event.target.value })}>
                <option value="">Choose channel</option>
                {encryptChannels.map((channel) => (
                  <option key={channel.id} value={channel.id}>
                    {channel.display_name} ({channel.id})
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Ciphertext">
              <input value={decrypt.ciphertext} onChange={(event) => setDecrypt({ ...decrypt, ciphertext: event.target.value })} />
            </Field>
            <Field label="Principal (needs decrypt license)">
              <input value={decrypt.principal} onChange={(event) => setDecrypt({ ...decrypt, principal: event.target.value })} />
            </Field>
            <Field label="Justification">
              <input value={decrypt.justification} onChange={(event) => setDecrypt({ ...decrypt, justification: event.target.value })} />
            </Field>
            <div className="button-row">
              <button
                disabled={!decrypt.channel_id || !decrypt.ciphertext || !decrypt.principal}
                onClick={() =>
                  run(async () => {
                    setDecryptResult(
                      await cipherDecrypt({
                        channel_id: decrypt.channel_id,
                        ciphertext: decrypt.ciphertext,
                        principal: decrypt.principal,
                        justification: decrypt.justification || undefined
                      })
                    );
                  })
                }
              >
                Decrypt
              </button>
            </div>
          </div>
          {decryptResult ? <KeyValueGrid data={{ plaintext: decryptResult.value }} /> : null}
        </Panel>
      </div>
      <Panel title="Hash">
        <div className="metadata-edit-grid">
          <Field label="Channel">
            <select value={hash.channel_id} onChange={(event) => setHash({ ...hash, channel_id: event.target.value })}>
              <option value="">Choose channel</option>
              {channelOptions.map((channel) => (
                <option key={channel.id} value={channel.id}>
                  {channel.display_name} ({channel.id})
                </option>
              ))}
            </select>
          </Field>
          <Field label="Value">
            <input value={hash.value} onChange={(event) => setHash({ ...hash, value: event.target.value })} />
          </Field>
          <Field label="Algorithm">
            <select value={hash.algorithm} onChange={(event) => setHash({ ...hash, algorithm: event.target.value })}>
              <option value="sha256">sha256</option>
              <option value="sha512">sha512</option>
            </select>
          </Field>
          <Field label="Principal (optional, enforces license)">
            <input value={hash.principal} onChange={(event) => setHash({ ...hash, principal: event.target.value })} />
          </Field>
          <div className="button-row">
            <button
              disabled={!hash.channel_id || !hash.value}
              onClick={() =>
                run(async () => {
                  setHashResult(
                    await cipherHash({
                      channel_id: hash.channel_id,
                      value: hash.value,
                      algorithm: hash.algorithm,
                      principal: hash.principal || undefined
                    })
                  );
                })
              }
            >
              Hash
            </button>
          </div>
        </div>
        {hashResult ? <KeyValueGrid data={{ algorithm: hashResult.algorithm, digest: hashResult.digest }} /> : null}
      </Panel>
      <DeveloperEvidence title="Developer evidence: Cipher governance">
        <KeyValueGrid
          data={{
            note: "encrypt requires data_manager/admin license; decrypt requires a can_decrypt license and (when the channel demands it) a justification; hashing accepts any license type.",
            license_endpoint: "POST /cipher/channels/{id}/licenses"
          }}
        />
      </DeveloperEvidence>
    </>
  );
}
