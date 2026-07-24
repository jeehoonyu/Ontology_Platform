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

interface OntologyPackagePanelProps {
  objectTypeId: string;
  objectTypeName: string;
}

export function OntologyPackagePanel({ objectTypeId, objectTypeName }: OntologyPackagePanelProps) {
  const [projects, setProjects] = useState<TenancyProject[]>([]);
  const [packages, setPackages] = useState<OntologyPackageSummary[]>([]);
  const [selectedPackageId, setSelectedPackageId] = useState("");
  const [detail, setDetail] = useState<OntologyPackageSummary | null>(null);
  const [projectId, setProjectId] = useState("");
  const [targetProjectId, setTargetProjectId] = useState("");
  const [version, setVersion] = useState("1.0.0");
  const [namespace, setNamespace] = useState("operations");
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);

  async function reload() {
    const nextProjects = await listTenancyProjects();
    const nextPackages = await listOntologyPackages();
    setProjects(nextProjects);
    setPackages(nextPackages);
    setProjectId((current) => current || nextProjects[0]?.id || "");
    setTargetProjectId((current) => current || nextProjects[0]?.id || "");
    setSelectedPackageId((current) => current || nextPackages[0]?.id || "");
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
            <label>Package<select value={selectedPackageId} onChange={(event) => setSelectedPackageId(event.target.value)}><option value="">Create a package</option>{packages.map((item) => <option value={item.id} key={item.id}>{item.display_name}</option>)}</select></label>
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
