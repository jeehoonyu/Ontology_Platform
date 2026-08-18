import { useCallback, useEffect, useMemo, useState } from "react";
import {
  captureOntologyRevision,
  createOntologyChangeSet,
  decideOntologyChangeSet,
  getOntologyContractHealth,
  listOntologyChangeSets,
  listOntologyEnvironments,
  listOntologyRevisions,
  publishOntologyChangeSet,
  rollbackOntologyEnvironment,
  validateOntologyChangeSet,
  type OntologyChangeSet,
  type OntologyContractHealth,
  type OntologyEnvironmentState,
  type OntologyRevisionSummary
} from "../api/ontologyLifecycleApi";
import { EmptyState, Panel, StatusBadge } from "../components/data/DataDisplay";

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
  const [contractHealth, setContractHealth] = useState<OntologyContractHealth | null>(null);
  const [breakingAcknowledged, setBreakingAcknowledged] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [nextRevisions, nextChangeSets, nextEnvironments, nextContractHealth] = await Promise.all([
        listOntologyRevisions(projectId),
        listOntologyChangeSets(projectId),
        listOntologyEnvironments(projectId),
        getOntologyContractHealth(projectId)
      ]);
      setRevisions(nextRevisions);
      setChangeSets(nextChangeSets);
      setEnvironments(nextEnvironments);
      setContractHealth(nextContractHealth);
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

  useEffect(() => {
    setBreakingAcknowledged(false);
  }, [selectedChangeSetId]);

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

      <ContractHealthPanel health={contractHealth} />

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
          )) : <EmptyState inline>Capture the current ontology and propose the first reviewed change.</EmptyState>}
        </Panel>
      </div>

      {selected ? <ChangeSetReview
        changeSet={selected}
        busy={busy}
        onValidate={() => run(() => validateOntologyChangeSet(selected.id), "Change set validation completed.")}
        onDecision={(approve) => run(() => decideOntologyChangeSet(selected.id, approve), approve ? "Change set approved." : "Change set rejected.")}
        breakingAcknowledged={breakingAcknowledged}
        onBreakingAcknowledged={setBreakingAcknowledged}
        onPublish={async () => {
          const result = await run(
            () => publishOntologyChangeSet(
              selected.id,
              selected.checksum,
              breakingAcknowledged,
              breakingAcknowledged
                ? (selected.impact.affected_consumers || []).filter((consumer) => consumer.breaking).map((consumer) => consumer.binding_id)
                : []
            ),
            "Ontology revision published to production. Downstream compatibility has been refreshed."
          );
          if (result) setBaseRevisionId(result.revision.id);
        }}
      /> : null}

      <Panel title="Revision History" className="ontology-revision-history">
        <div className="release-table" role="table" aria-label="Ontology revision history">
          {revisions.map((revision) => (
            <div className="release-table-row" role="row" key={revision.id}>
              <strong role="cell">Revision {revision.revision}</strong>
              <StatusBadge value={revision.status} />
              <span role="cell">{revision.validation.status || "NOT_VALIDATED"}</span>
              <span role="cell">{new Date(revision.created_at * 1000).toLocaleString()}</span>
              <button disabled={busy || !["PUBLISHED", "SUPERSEDED"].includes(revision.status) || production?.current_revision_id === revision.id} onClick={async () => {
                const result = await run(() => rollbackOntologyEnvironment(projectId, revision.id), `Production restored from revision ${revision.revision}. Downstream compatibility has been refreshed.`);
                if (result) setBaseRevisionId(result.revision.id);
              }}>Restore</button>
            </div>
          ))}
        </div>
      </Panel>
    </section>
  );
}

function ContractHealthPanel({ health }: { health: OntologyContractHealth | null }) {
  const statuses = ["CURRENT", "COMPATIBLE_STALE", "BROKEN", "UNVERSIONED", "NO_ACTIVE_REVISION"] as const;
  return (
    <Panel title="Downstream Contract Health" ariaLabel="Downstream Contract Health" className="ontology-contract-health" action={<StatusBadge value={health?.status || "NOT_AVAILABLE"} />}>
      <div className="contract-health-summary" aria-label="Downstream ontology contract status counts">
        {statuses.map((status) => <div key={status}><span>{status.replace(/_/g, " ")}</span><strong>{health?.counts[status] || 0}</strong></div>)}
      </div>
      {health?.bindings.length ? (
        <div className="contract-consumer-list">
          {health.bindings.map((binding) => (
            <article key={binding.id}>
              <StatusBadge value={binding.health.status} />
              <div>
                <strong>{binding.definition.consumer_kind} · {binding.definition.consumer_id}</strong>
                <span>Version {binding.definition.consumer_version} · {binding.definition.target_id}</span>
                {binding.definition.properties?.length ? <small>{binding.definition.properties.join(", ")}</small> : <small>Whole object contract</small>}
              </div>
              {binding.health.reason ? <span className="contract-health-reason">{binding.health.reason.replace(/_/g, " ")}</span> : null}
            </article>
          ))}
        </div>
      ) : <EmptyState inline>No published downstream consumer is bound to this ontology yet.</EmptyState>}
    </Panel>
  );
}

function ChangeSetReview({ changeSet, busy, breakingAcknowledged, onBreakingAcknowledged, onValidate, onDecision, onPublish }: {
  changeSet: OntologyChangeSet;
  busy: boolean;
  breakingAcknowledged: boolean;
  onBreakingAcknowledged: (value: boolean) => void;
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
        <div><span>Consumers</span><strong>{changeSet.impact.affected_consumer_count || 0}</strong></div>
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
        <div>
          <h3>Affected consumers</h3>
          {(changeSet.impact.affected_consumers || []).length ? <ul>{(changeSet.impact.affected_consumers || []).map((consumer) => <li key={consumer.binding_id}><StatusBadge value={consumer.breaking ? "BREAKING" : "REVIEW"} /><span>{consumer.consumer_kind} · {consumer.consumer_id} · v{consumer.consumer_version}</span></li>)}</ul> : <p className="release-no-consumers">No version-bound consumer references this change.</p>}
        </div>
      </div>
      {changeSet.diff.classification === "BREAKING" ? (
        <label className="breaking-acknowledgement">
          <input type="checkbox" checked={breakingAcknowledged} onChange={(event) => onBreakingAcknowledged(event.target.checked)} />
          <span>I reviewed the migration plan and affected consumers. Publish this recoverable breaking revision.</span>
        </label>
      ) : null}
      <div className="button-row release-actions">
        <button onClick={onValidate} disabled={busy || !["DRAFT", "VALIDATED"].includes(changeSet.status)}>Validate</button>
        <button onClick={() => onDecision(true)} disabled={busy || changeSet.status !== "VALIDATED"}>Approve</button>
        <button onClick={() => onDecision(false)} disabled={busy || changeSet.status !== "VALIDATED"}>Reject</button>
        <button className="primary" onClick={onPublish} disabled={busy || changeSet.status !== "APPROVED" || (changeSet.diff.classification === "BREAKING" && !breakingAcknowledged)}>Publish</button>
      </div>
    </Panel>
  );
}
