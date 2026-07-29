import { useCallback, useEffect, useMemo, useState } from "react";
import {
  captureOntologyRevision,
  createOntologyChangeSet,
  decideOntologyChangeSet,
  listOntologyChangeSets,
  listOntologyEnvironments,
  listOntologyRevisions,
  publishOntologyChangeSet,
  rollbackOntologyEnvironment,
  validateOntologyChangeSet,
  type OntologyChangeSet,
  type OntologyEnvironmentState,
  type OntologyRevisionSummary
} from "../api/ontologyLifecycleApi";
import { Panel, StatusBadge } from "../components/data/DataDisplay";

const PROPERTY_TYPES = ["string", "integer", "double", "boolean", "date", "timestamp", "json", "array", "geometry"];

export function OntologyReleasePanel({ objectTypeId, projectId = "default", onBack }: { objectTypeId: string; projectId?: string; onBack?: () => void }) {
  const [revisions, setRevisions] = useState<OntologyRevisionSummary[]>([]);
  const [changeSets, setChangeSets] = useState<OntologyChangeSet[]>([]);
  const [environments, setEnvironments] = useState<OntologyEnvironmentState[]>([]);
  const [selectedChangeSetId, setSelectedChangeSetId] = useState("");
  const [baseRevisionId, setBaseRevisionId] = useState("");
  const [operation, setOperation] = useState<"add_property" | "archive_property">("add_property");
  const [propertyName, setPropertyName] = useState("");
  const [baseType, setBaseType] = useState("string");
  const [required, setRequired] = useState(false);
  const [description, setDescription] = useState("");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [nextRevisions, nextChangeSets, nextEnvironments] = await Promise.all([
        listOntologyRevisions(projectId),
        listOntologyChangeSets(projectId),
        listOntologyEnvironments(projectId)
      ]);
      setRevisions(nextRevisions);
      setChangeSets(nextChangeSets);
      setEnvironments(nextEnvironments);
      setSelectedChangeSetId((current) => current || nextChangeSets[0]?.id || "");
      const production = nextEnvironments.find((item) => item.name === "production");
      setBaseRevisionId((current) => current || production?.current_revision_id || nextRevisions[0]?.id || "");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not load ontology releases.");
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const selected = useMemo(() => changeSets.find((item) => item.id === selectedChangeSetId) || null, [changeSets, selectedChangeSetId]);
  const production = environments.find((item) => item.name === "production");

  async function run<T>(action: () => Promise<T>, success: string): Promise<T | undefined> {
    setBusy(true);
    setMessage("");
    try {
      const result = await action();
      setMessage(success);
      await refresh();
      return result;
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Ontology release operation failed.");
      return undefined;
    } finally {
      setBusy(false);
    }
  }

  async function capture() {
    await run(async () => {
      const revision = await captureOntologyRevision(projectId);
      setBaseRevisionId(revision.id);
    }, "Current ontology captured as an immutable draft revision.");
  }

  async function createChange() {
    const name = propertyName.trim();
    if (!name || !baseRevisionId) return;
    const change = await run(() => createOntologyChangeSet({
        project_id: projectId,
        title: `${operation === "add_property" ? "Add" : "Archive"} ${name}`,
        description: description.trim() || `Structured schema change for ${objectTypeId}.${name}`,
        base_revision_id: baseRevisionId,
        changes: [{
          operation,
          object_type_id: objectTypeId,
          property_name: name,
          ...(operation === "add_property" ? { spec: { base_type: baseType, required, description: description.trim() || undefined } } : {})
        }]
      }), "Change set created. Validate it before requesting approval.");
    if (change) {
      setSelectedChangeSetId(change.id);
      setPropertyName("");
      setDescription("");
      setRequired(false);
    }
  }

  if (loading && !revisions.length && !changeSets.length) {
    return <div className="ontology-release-loading" role="status">Loading ontology release history...</div>;
  }

  return (
    <section className="ontology-release-studio" aria-labelledby="ontology-release-title">
      <header className="manager-header-card ontology-release-header">
        <div>
          <span className="object-icon">RV</span>
          <h2 id="ontology-release-title">Ontology Releases</h2>
          <p>Review semantic diffs, migration impact, approvals, publication, and rollback.</p>
          <div className="manager-chip-row">
            <StatusBadge value={production ? "PRODUCTION" : "NOT_PUBLISHED"} />
            <span className="release-current">{production?.current_revision_id ? `Revision ${revisions.find((item) => item.id === production.current_revision_id)?.revision || "-"}` : "No production revision"}</span>
          </div>
        </div>
        <div className="button-row">
          {onBack ? <button onClick={onBack}>Back to object</button> : null}
          <button onClick={capture} disabled={busy}>Capture current</button>
          <button onClick={refresh} disabled={busy}>Refresh</button>
        </div>
      </header>

      {message ? <div className="operation-message" role="status">{message}</div> : null}

      <div className="ontology-release-grid">
        <Panel title="Propose Schema Change" className="ontology-change-form">
          <label><span>Base revision</span><select value={baseRevisionId} onChange={(event) => setBaseRevisionId(event.target.value)}>
            <option value="">Capture a revision first</option>
            {revisions.map((revision) => <option key={revision.id} value={revision.id}>Revision {revision.revision} - {revision.status}</option>)}
          </select></label>
          <label><span>Operation</span><select value={operation} onChange={(event) => setOperation(event.target.value as "add_property" | "archive_property")}>
            <option value="add_property">Add property</option>
            <option value="archive_property">Archive property</option>
          </select></label>
          <label><span>Property API name</span><input value={propertyName} onChange={(event) => setPropertyName(event.target.value)} placeholder="riskScore" /></label>
          {operation === "add_property" ? <>
            <label><span>Base type</span><select value={baseType} onChange={(event) => setBaseType(event.target.value)}>{PROPERTY_TYPES.map((type) => <option key={type}>{type}</option>)}</select></label>
            <label className="release-checkbox"><input type="checkbox" checked={required} onChange={(event) => setRequired(event.target.checked)} /><span>Required field</span></label>
          </> : null}
          <label className="release-wide"><span>Reason and description</span><textarea value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Why is this schema change needed?" /></label>
          <div className="button-row release-wide"><button onClick={createChange} disabled={busy || !propertyName.trim() || !baseRevisionId}>Create change set</button></div>
        </Panel>

        <Panel title="Change Sets" className="ontology-change-list">
          {changeSets.length ? changeSets.map((changeSet) => (
            <button key={changeSet.id} className={selectedChangeSetId === changeSet.id ? "release-list-row selected" : "release-list-row"} onClick={() => setSelectedChangeSetId(changeSet.id)}>
              <span><strong>{changeSet.title}</strong><small>{changeSet.diff.classification || "NOT_VALIDATED"} · {changeSet.diff.summary?.changes || 0} changes</small></span>
              <StatusBadge value={changeSet.status} />
            </button>
          )) : <div className="empty">Capture the current ontology and propose the first reviewed change.</div>}
        </Panel>
      </div>

      {selected ? <ChangeSetReview
        changeSet={selected}
        busy={busy}
        onValidate={() => run(() => validateOntologyChangeSet(selected.id), "Change set validation completed.")}
        onDecision={(approve) => run(() => decideOntologyChangeSet(selected.id, approve), approve ? "Change set approved." : "Change set rejected.")}
        onPublish={() => run(() => publishOntologyChangeSet(selected.id, selected.checksum, selected.diff.classification === "BREAKING"), "Ontology revision published to production.")}
      /> : null}

      <Panel title="Revision History" className="ontology-revision-history">
        <div className="release-table" role="table" aria-label="Ontology revision history">
          {revisions.map((revision) => (
            <div className="release-table-row" role="row" key={revision.id}>
              <strong role="cell">Revision {revision.revision}</strong>
              <StatusBadge value={revision.status} />
              <span role="cell">{revision.validation.status || "NOT_VALIDATED"}</span>
              <span role="cell">{new Date(revision.created_at * 1000).toLocaleString()}</span>
              <button disabled={busy || !["PUBLISHED", "SUPERSEDED"].includes(revision.status) || production?.current_revision_id === revision.id} onClick={() => run(() => rollbackOntologyEnvironment(projectId, revision.id), `Production restored from revision ${revision.revision}.`)}>Restore</button>
            </div>
          ))}
        </div>
      </Panel>
    </section>
  );
}

function ChangeSetReview({ changeSet, busy, onValidate, onDecision, onPublish }: {
  changeSet: OntologyChangeSet;
  busy: boolean;
  onValidate: () => void;
  onDecision: (approve: boolean) => void;
  onPublish: () => void;
}) {
  return (
    <Panel title="Review and Migration Evidence" className="ontology-change-review" action={<StatusBadge value={changeSet.diff.classification || changeSet.status} />}>
      <div className="release-summary-cards">
        <div><span>Changes</span><strong>{changeSet.diff.summary?.changes || 0}</strong></div>
        <div><span>Breaking</span><strong>{changeSet.diff.summary?.breaking || 0}</strong></div>
        <div><span>Live objects</span><strong>{changeSet.impact.live_objects || 0}</strong></div>
        <div><span>Migration</span><strong>{changeSet.migration_plan.status || "PENDING"}</strong></div>
      </div>
      <div className="release-evidence-grid">
        <div>
          <h3>Semantic diff</h3>
          <ul>{(changeSet.diff.entries || []).map((entry, index) => <li key={`${entry.resource_id}-${entry.property_name || index}`}><StatusBadge value={entry.breaking ? "BREAKING" : "SAFE"} /><span>{entry.kind.replace(/_/g, " ")} · {entry.resource_id}{entry.property_name ? `.${entry.property_name}` : ""}</span></li>)}</ul>
        </div>
        <div>
          <h3>Migration plan</h3>
          <ol>{(changeSet.migration_plan.steps || []).map((step) => <li key={step.order}><strong>{step.strategy.replace(/_/g, " ")}</strong><span>{step.resource_id}{step.property_name ? `.${step.property_name}` : ""}</span></li>)}</ol>
        </div>
      </div>
      <div className="button-row release-actions">
        <button onClick={onValidate} disabled={busy || !["DRAFT", "VALIDATED"].includes(changeSet.status)}>Validate</button>
        <button onClick={() => onDecision(true)} disabled={busy || changeSet.status !== "VALIDATED"}>Approve</button>
        <button onClick={() => onDecision(false)} disabled={busy || changeSet.status !== "VALIDATED"}>Reject</button>
        <button className="primary" onClick={onPublish} disabled={busy || changeSet.status !== "APPROVED"}>Publish</button>
      </div>
    </Panel>
  );
}
