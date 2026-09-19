import { useEffect, useMemo, useState } from "react";
import {
  bootstrapTenancy,
  captureOntologyPackageVersion,
  createOntologyPackage,
  getOntologyPackage,
  installOntologyPackageVersion,
  listOntologyPackages,
  listTenancyProjects,
  publishOntologyPackageVersion,
  type OntologyPackageSummary,
  type OntologyPackageVersionSummary,
  type TenancyProject
} from "../api/ontologyPackageApi";
import { Panel, StatusBadge } from "../components/data/DataDisplay";

/**
 * What a person has chosen and typed in this panel and not yet sent.
 *
 * Held by the screen and handed back in, because this panel sits in the ontology
 * manager's Resources pane: a pane moved to another slot is a new parent, React
 * remounts what it holds, and all of this went with it -- a typed version back to
 * `1.0.0`, a namespace back to `operations`, each select back to the first entry
 * the reload found. V12 of GOAL_MOVEMENT_2026-09-12; V9 did the same for the
 * pipeline node form.
 *
 * `selectedPackageId` is `null` until something is chosen. `Create a package` is
 * the empty string, a real choice, and a reload must not read it as none.
 */
export interface PackageForm {
  selectedPackageId: string | null;
  projectId: string;
  targetProjectId: string;
  version: string;
  namespace: string;
}

export const NEW_PACKAGE_FORM: PackageForm = {
  selectedPackageId: null,
  projectId: "",
  targetProjectId: "",
  version: "1.0.0",
  namespace: "operations"
};

interface OntologyPackagePanelProps {
  objectTypeId: string;
  objectTypeName: string;
  form: PackageForm;
  onForm: (update: (current: PackageForm) => PackageForm) => void;
}

export function OntologyPackagePanel({ objectTypeId, objectTypeName, form, onForm }: OntologyPackagePanelProps) {
  const [projects, setProjects] = useState<TenancyProject[]>([]);
  const [packages, setPackages] = useState<OntologyPackageSummary[]>([]);
  const [detail, setDetail] = useState<OntologyPackageSummary | null>(null);
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const { selectedPackageId, projectId, targetProjectId, version, namespace } = form;
  const setSelectedPackageId = (value: string) => onForm((current) => ({ ...current, selectedPackageId: value }));
  const setProjectId = (value: string) => onForm((current) => ({ ...current, projectId: value }));
  const setTargetProjectId = (value: string) => onForm((current) => ({ ...current, targetProjectId: value }));
  const setVersion = (value: string) => onForm((current) => ({ ...current, version: value }));
  const setNamespace = (value: string) => onForm((current) => ({ ...current, namespace: value }));

  async function reload() {
    const nextProjects = await listTenancyProjects();
    const nextPackages = await listOntologyPackages();
    setProjects(nextProjects);
    setPackages(nextPackages);
    // A default only for what has not been chosen. A remount reloads as well, and by
    // then the person's choices are already in `form`.
    onForm((current) => ({
      ...current,
      projectId: current.projectId || nextProjects[0]?.id || "",
      targetProjectId: current.targetProjectId || nextProjects[0]?.id || "",
      selectedPackageId: current.selectedPackageId ?? (nextPackages[0]?.id || null)
    }));
  }

  useEffect(() => {
    reload().catch((error) => setStatus(error instanceof Error ? error.message : String(error)));
  }, []);

  useEffect(() => {
    if (!selectedPackageId) {
      setDetail(null);
      return;
    }
    getOntologyPackage(selectedPackageId).then(setDetail).catch((error) => setStatus(error instanceof Error ? error.message : String(error)));
  }, [selectedPackageId]);

  const selectedProject = projects.find((project) => project.id === projectId);
  const latestDraft = useMemo(() => detail?.versions?.find((item) => item.status === "DRAFT"), [detail]);
  const publishedVersion = detail?.current_version;

  async function run(action: () => Promise<unknown>, message: string) {
    setBusy(true);
    setStatus("");
    try {
      await action();
      setStatus(message);
      await reload();
      if (selectedPackageId) setDetail(await getOntologyPackage(selectedPackageId));
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel title="Governed Packages">
      <div className="ontology-package-panel">
        {!projects.length ? (
          <div className="package-empty-state">
            <span>Create the organization and default project needed for governed package publishing.</span>
            <button disabled={busy} onClick={() => run(() => bootstrapTenancy(), "Package workspace initialized")}>Initialize workspace</button>
          </div>
        ) : (
          <>
            <label>Owning project<select value={projectId} onChange={(event) => setProjectId(event.target.value)}>{projects.map((project) => <option value={project.id} key={project.id}>{project.display_name}</option>)}</select></label>
            <label>Package<select value={selectedPackageId ?? ""} onChange={(event) => setSelectedPackageId(event.target.value)}><option value="">Create a package</option>{packages.map((item) => <option value={item.id} key={item.id}>{item.display_name}</option>)}</select></label>
            {!selectedPackageId ? <button disabled={busy || !selectedProject || !objectTypeId} onClick={() => {
              const packageId = `${objectTypeId}_package`.replace(/[^A-Za-z0-9_.-]/g, "_");
              run(async () => {
                const created = await createOntologyPackage(selectedProject!, packageId, `${objectTypeName} Package`);
                setSelectedPackageId(created.id);
              }, "Package created");
            }}>Create from selected type</button> : null}
            {selectedPackageId ? (
              <>
                <div className="package-summary-row"><StatusBadge value={detail?.status || "LOADING"} /><span>{detail?.version_count || 0} versions</span><span>{detail?.active_installations || 0} installs</span></div>
                <label>New version<input value={version} onChange={(event) => setVersion(event.target.value)} placeholder="1.0.0" /></label>
                <button disabled={busy || !objectTypeId} onClick={() => run(() => captureOntologyPackageVersion(selectedPackageId, version, objectTypeId), `Captured ${version}`)}>Capture selected type</button>
                {latestDraft ? <PackageVersionRow version={latestDraft} actionLabel="Publish" disabled={busy} onAction={() => run(() => publishOntologyPackageVersion(selectedPackageId, latestDraft), `Published ${latestDraft.version}`)} /> : null}
                {publishedVersion ? (
                  <div className="package-install-form">
                    <label>Target project<select value={targetProjectId} onChange={(event) => setTargetProjectId(event.target.value)}>{projects.map((project) => <option value={project.id} key={project.id}>{project.display_name}</option>)}</select></label>
                    <label>Namespace<input value={namespace} onChange={(event) => setNamespace(event.target.value.replace(/[^A-Za-z0-9_]/g, ""))} /></label>
                    <button disabled={busy || !targetProjectId || !namespace} onClick={() => run(() => installOntologyPackageVersion(selectedPackageId, publishedVersion, targetProjectId, namespace), `Installed ${publishedVersion}`)}>Install package</button>
                  </div>
                ) : null}
              </>
            ) : null}
          </>
        )}
        {status ? <div className="package-operation-status" role="status">{status}</div> : null}
      </div>
    </Panel>
  );
}

function PackageVersionRow({ version, actionLabel, disabled, onAction }: { version: OntologyPackageVersionSummary; actionLabel: string; disabled: boolean; onAction: () => void }) {
  return <div className="package-version-row"><div><strong>{version.version}</strong><span title={version.checksum}>{version.checksum.slice(0, 10)}...</span></div><StatusBadge value={version.validation?.status || version.status} /><button disabled={disabled} onClick={onAction}>{actionLabel}</button></div>;
}
