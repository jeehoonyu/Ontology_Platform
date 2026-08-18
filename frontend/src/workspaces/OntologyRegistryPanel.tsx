import { useEffect, useMemo, useState } from "react";
import {
  checkRegistryCompatibility,
  downloadRegistryPackage,
  getOntologyRegistryState,
  getPublishedOntologyRevisions,
  getRegistryPackages,
  getRegistrySchema,
  getRegistrySdk,
  publishOntologyRegistry,
  type OntologyRegistryEntry,
  type OntologySdkPackage,
  type OntologyRegistryState,
  type OntologyRevisionSummary,
  type RegistryCompatibility
} from "../api/ontologyRegistryApi";
import { DataTable, EmptyState, KeyValueGrid, Panel, StatusBadge } from "../components/data/DataDisplay";

export function OntologyRegistryPanel({ onBack }: { onBack: () => void }) {
  const [state, setState] = useState<OntologyRegistryState | null>(null);
  const [revisions, setRevisions] = useState<OntologyRevisionSummary[]>([]);
  const [revisionId, setRevisionId] = useState("");
  const [version, setVersion] = useState("1.0.0");
  const [channel, setChannel] = useState("production");
  const [allowBreaking, setAllowBreaking] = useState(false);
  const [compatibility, setCompatibility] = useState<RegistryCompatibility | null>(null);
  const [selected, setSelected] = useState<OntologyRegistryEntry | null>(null);
  const [packages, setPackages] = useState<OntologySdkPackage[]>([]);
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("Select a published ontology revision to check compatibility.");

  async function refresh() {
    const [nextState, nextRevisions] = await Promise.all([
      getOntologyRegistryState("default", channel),
      getPublishedOntologyRevisions("default")
    ]);
    const published = nextRevisions.filter((revision) => ["PUBLISHED", "SUPERSEDED"].includes(revision.status));
    setState(nextState);
    setRevisions(published);
    setSelected((current) => nextState.sections.entries.find((entry) => entry.id === current?.id) || nextState.sections.current || null);
    setRevisionId((current) => current || published[0]?.id || "");
  }

  useEffect(() => {
    void refresh().catch((error: Error) => setMessage(`Could not load schema registry: ${error.message}`));
  }, [channel]);

  useEffect(() => {
    if (!selected) {
      setPackages([]);
      return;
    }
    void getRegistryPackages(selected.id)
      .then((manifest) => setPackages(manifest.packages))
      .catch((error: Error) => setMessage(`Could not load installable packages: ${error.message}`));
  }, [selected?.id]);

  const compatibilityRows = useMemo(() => (compatibility?.entries || selected?.compatibility.entries || []).map((entry) => ({
    change: entry.kind.replace(/_/g, " "),
    resource: entry.resource_id,
    property: entry.property_name || "-",
    classification: entry.breaking ? "BREAKING" : "NON_BREAKING"
  })), [compatibility, selected]);

  async function runCompatibility() {
    if (!revisionId) return;
    setBusy("compatibility");
    try {
      const result = await checkRegistryCompatibility(revisionId, "default", channel);
      setCompatibility(result);
      setMessage(`Compatibility result: ${result.classification}. ${result.summary.changes} semantic changes found.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy("");
    }
  }

  async function publish() {
    if (!revisionId || !version) return;
    setBusy("publish");
    try {
      const result = await publishOntologyRegistry(revisionId, version, channel, allowBreaking);
      setMessage(`Published ${result.channel} registry version ${result.version}.`);
      setCompatibility(null);
      setSelected(result);
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy("");
    }
  }

  function download(name: string, content: string, type: string) {
    const url = URL.createObjectURL(new Blob([content], { type }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = name;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  async function downloadSchema() {
    if (!selected) return;
    setBusy("schema");
    try {
      const result = await getRegistrySchema(selected.id);
      download(`ontology-${selected.version}.schema.json`, JSON.stringify(result.schema, null, 2), "application/schema+json");
      setMessage(`Downloaded JSON Schema for ${selected.version}.`);
    } finally {
      setBusy("");
    }
  }

  async function downloadSdk(language: "typescript" | "python") {
    if (!selected) return;
    setBusy(language);
    try {
      const result = await getRegistrySdk(selected.id, language);
      const [name, content] = Object.entries(result.files)[0] || [];
      if (name && content) download(name, content, "text/plain");
      setMessage(`Downloaded the ${language} client for ${selected.version}.`);
    } finally {
      setBusy("");
    }
  }

  async function downloadPackage(packageInfo: OntologySdkPackage) {
    setBusy(`package-${packageInfo.ecosystem}`);
    try {
      await downloadRegistryPackage(packageInfo);
      setMessage(`Downloaded installable ${packageInfo.package_name} ${selected?.version || ""}.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy("");
    }
  }

  return (
    <section className="ontology-registry" aria-label="Ontology schema registry">
      <header className="ontology-release-header">
        <div><span className="eyebrow">Developer contract</span><h1>Schema Registry</h1><p>Publish approved ontology revisions as immutable schemas and typed clients.</p></div>
        <div className="button-row"><StatusBadge value={state?.summary.status || "LOADING"} /><button onClick={onBack}>Back to object type</button></div>
      </header>
      <div className="registry-status" role="status">{message}</div>
      <div className="registry-summary-grid">
        <Panel title="Current Channel">
          <KeyValueGrid data={{ channel, version: state?.summary.current_version || "Not published", entries: state?.summary.entries || 0, checksum: selected?.checksum?.slice(0, 12) || "-" }} />
        </Panel>
        <Panel title="Publish Approved Revision">
          <div className="registry-publish-form">
            <label>Published revision<select value={revisionId} onChange={(event) => { setRevisionId(event.target.value); setCompatibility(null); }}><option value="">Choose revision</option>{revisions.map((revision) => <option key={revision.id} value={revision.id}>Revision {revision.revision} - {revision.status}</option>)}</select></label>
            <label>Semantic version<input value={version} onChange={(event) => setVersion(event.target.value)} pattern="[0-9]+\.[0-9]+\.[0-9]+.*" /></label>
            <label>Channel<input value={channel} onChange={(event) => setChannel(event.target.value)} /></label>
            <label className="release-checkbox"><input type="checkbox" checked={allowBreaking} onChange={(event) => setAllowBreaking(event.target.checked)} />Acknowledge breaking changes</label>
            <div className="button-row"><button onClick={runCompatibility} disabled={!revisionId || Boolean(busy)}>{busy === "compatibility" ? "Checking..." : "Check compatibility"}</button><button className="primary-action" onClick={publish} disabled={!revisionId || !version || Boolean(busy)}>{busy === "publish" ? "Publishing..." : "Publish registry"}</button></div>
          </div>
        </Panel>
      </div>
      <div className="registry-main-grid">
        <Panel title="Published Versions">
          <div className="ontology-contract-list">
            {(state?.sections.entries || []).map((entry) => <button key={entry.id} className="ontology-contract-row" onClick={() => { setSelected(entry); setCompatibility(null); }}><span><strong>{entry.version}</strong><small>{entry.channel} · revision {entry.revision_number}</small></span><StatusBadge value={entry.compatibility.classification} /></button>)}
            {!state?.sections.entries.length ? <EmptyState inline>No registry versions have been published.</EmptyState> : null}
          </div>
        </Panel>
        <Panel title="Contract Evidence" action={selected ? <StatusBadge value={selected.compatibility.classification} /> : undefined}>
          {selected ? <>
            <KeyValueGrid data={{ version: selected.version, revision: selected.revision_number, publisher: selected.published_by, checksum: selected.checksum, prior_registry: selected.compatibility.against_registry_id || "Initial contract" }} />
            <div className="button-row registry-downloads"><button onClick={downloadSchema} disabled={Boolean(busy)}>Download schema</button><button onClick={() => downloadSdk("typescript")} disabled={Boolean(busy)}>TypeScript source</button><button onClick={() => downloadSdk("python")} disabled={Boolean(busy)}>Python source</button></div>
            <div className="ontology-package-list" aria-label="Installable SDK packages">
              {packages.map((packageInfo) => <div className="ontology-package-row" key={packageInfo.ecosystem}>
                <span><strong>{packageInfo.ecosystem === "npm" ? "npm package" : "Python wheel"}</strong><small>{packageInfo.package_name} · {(packageInfo.byte_size / 1024).toFixed(1)} KB · SHA-256 {packageInfo.sha256.slice(0, 12)}</small></span>
                <button onClick={() => downloadPackage(packageInfo)} disabled={Boolean(busy)}>{busy === `package-${packageInfo.ecosystem}` ? "Preparing..." : `Download ${packageInfo.filename.endsWith(".whl") ? ".whl" : ".tgz"}`}</button>
              </div>)}
            </div>
          </> : <EmptyState inline>Select a published version to inspect its contract.</EmptyState>}
        </Panel>
      </div>
      <Panel title="Semantic Compatibility">
        <DataTable rows={compatibilityRows} empty="No semantic changes for the selected comparison." />
      </Panel>
    </section>
  );
}
