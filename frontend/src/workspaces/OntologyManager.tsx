import { useEffect, useState } from "react";
import { api, postJson } from "../api";
import {
  getOntologyObjectType,
  getOntologySection,
  getOntologyState,
  getOntologyWalkthrough,
  indexObjectType
} from "../api/workspaceState";
import { DataTable, KeyValueGrid, Panel, RelationshipStrip, StatusBadge } from "../components/data/DataDisplay";
import { useAsyncState } from "../hooks/useAsyncState";
import { asString, classNames, formatValue } from "../utils/format";
import { navigate } from "../utils/navigation";
import type {
  JsonObject,
  OntologyManagerState,
  OntologySectionState,
  OntologyUiState,
  OntologyWalkthrough,
  TableRow
} from "../types";

interface DataAssetsResponseItem extends TableRow {
  id: string;
  display_name?: string;
}

export function OntologyManager() {
  const [refreshKey, setRefreshKey] = useState(0);
  const [assetId, setAssetId] = useState("");
  const [selectedId, setSelectedId] = useState("");
  const [selectedSection, setSelectedSection] = useState("overview");
  const [manager, setManager] = useState<OntologyManagerState | null>(null);
  const [walkthrough, setWalkthrough] = useState<OntologyWalkthrough | null>(null);
  const [sectionState, setSectionState] = useState<OntologySectionState | null>(null);
  const state = useAsyncState<OntologyUiState>(getOntologyState, [refreshKey]);
  const assets = useAsyncState<DataAssetsResponseItem[]>(() => api<DataAssetsResponseItem[]>("/data-assets"), [refreshKey]);
  const drafts = useAsyncState<TableRow[]>(() => api<TableRow[]>("/ontology-generator/drafts"), [refreshKey]);

  useEffect(() => {
    if (!selectedId && state.value?.selected_object_type?.object_type.id) {
      setSelectedId(state.value.selected_object_type.object_type.id);
    }
  }, [state.value, selectedId]);

  useEffect(() => {
    if (!selectedId) return;
    let cancelled = false;
    Promise.all([getOntologyObjectType(selectedId), getOntologyWalkthrough(selectedId)])
      .then(([nextManager, nextWalkthrough]) => {
        if (!cancelled) {
          setManager(nextManager);
          setWalkthrough(nextWalkthrough);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setManager(null);
          setWalkthrough(null);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [selectedId, refreshKey]);

  useEffect(() => {
    if (!selectedId) return;
    let cancelled = false;
    getOntologySection(selectedId, selectedSection)
      .then((nextSection) => !cancelled && setSectionState(nextSection))
      .catch(() => !cancelled && setSectionState(null));
    return () => {
      cancelled = true;
    };
  }, [selectedId, selectedSection, refreshKey]);

  async function createDraft() {
    if (!assetId) return;
    const id = `${assetId}_react_draft`.replace(/[^a-zA-Z0-9_]/g, "_");
    const draft = await postJson<TableRow>("/ontology-generator/drafts", {
      id,
      asset_id: assetId,
      object_type_id: `${assetId}_object`.replace(/[^a-zA-Z0-9_]/g, "_"),
      include_actions: true,
      create_pipeline_graph: true
    });
    setSelectedId(asString(draft.object_type_id, selectedId));
    setSelectedSection("overview");
    setRefreshKey((key) => key + 1);
  }

  async function applyDraft(id: string) {
    const result = await postJson<TableRow>(`/ontology-generator/drafts/${encodeURIComponent(id)}/apply`, {
      actor: "react",
      create_actions: true,
      create_pipeline_graph: true
    });
    const objectType = result.object_type;
    const appliedObjectTypeId = typeof objectType === "object" && objectType !== null && !Array.isArray(objectType)
      ? (objectType as JsonObject).id
      : undefined;
    setSelectedId(asString(result.object_type_id || appliedObjectTypeId, selectedId));
    setSelectedSection("overview");
    setRefreshKey((key) => key + 1);
  }

  async function markIndexed() {
    if (!selectedId) return;
    setManager(await indexObjectType(selectedId));
    setRefreshKey((key) => key + 1);
  }

  return (
    <section className="workbench-page ontology-workbench-page">
      <header className="manager-topbar">
        <div>
          <strong>Ontology Manager</strong>
          <span>local deterministic ontology</span>
        </div>
        <input className="compact-input" placeholder="Search resources..." />
        <div className="button-row">
          <button onClick={markIndexed} disabled={!selectedId}>Index</button>
          <button onClick={() => navigate("pipeline")}>Open Pipeline</button>
          <a className="legacy-button compact" href="/workspace/ontology?legacy=1">Legacy</a>
        </div>
      </header>
      <div className="ontology-layout">
        <WalkthroughRail walkthrough={walkthrough} />
        <aside className="resource-nav manager-resource-nav">
          <Panel title="Discover">
            {(state.value?.object_types || []).map((objectType) => (
              <button key={objectType.id} className={classNames("resource-row", selectedId === objectType.id && "selected")} onClick={() => {
                setSelectedId(objectType.id);
                setSelectedSection("overview");
              }}>
                <strong>{objectType.display_name}</strong>
                <span>{objectType.property_count} properties</span>
              </button>
            ))}
          </Panel>
          <Panel title="Resource Navigation">
            {(manager?.navigation || []).map((item) => (
              <button key={item} className={classNames("resource-row", selectedSection === item && "selected")} onClick={() => setSelectedSection(item)}>
                <strong>{item.replace(/_/g, " ")}</strong>
              </button>
            ))}
          </Panel>
          <Panel title="Generate From Dataset" action={<button onClick={createDraft} disabled={!assetId}>Generate</button>}>
            <select value={assetId} onChange={(event) => setAssetId(event.target.value)}>
              <option value="">Choose dataset</option>
              {(assets.value || []).map((asset) => <option key={asset.id} value={asset.id}>{asset.display_name || asset.id}</option>)}
            </select>
          </Panel>
          <Panel title="Drafts">
            {(drafts.value || []).slice(0, 6).map((draft) => (
              <button key={asString(draft.id)} className="resource-row" onClick={() => applyDraft(asString(draft.id))}>
                <strong>{formatValue(draft.id)}</strong>
                <span>{formatValue(draft.status)}</span>
              </button>
            ))}
          </Panel>
        </aside>
        <section className="manager-surface">
          {manager ? <ManagerSurface manager={manager} sectionState={sectionState} onIndex={markIndexed} /> : (
            <div className="empty">Generate or select an object type to inspect manager details.</div>
          )}
        </section>
      </div>
      <footer className="ontology-utility-bar">
        <button>SQL console</button>
        <button>Preview</button>
        <button>Object mode</button>
      </footer>
    </section>
  );
}

function WalkthroughRail({ walkthrough }: { walkthrough: OntologyWalkthrough | null }) {
  return (
    <aside className="walkthrough-panel">
      <div className="walkthrough-tabs">
        <button className="active">Guide</button>
        <button>Overview</button>
        <button>Files</button>
      </div>
      <h2>{walkthrough?.title || "Build ontology workflow"}</h2>
      <p>Guided evidence from pipeline output into object type review.</p>
      <div className="walkthrough-actions">
        <button>Previous</button>
        <button>Next</button>
      </div>
      <ol>
        {(walkthrough?.steps || []).map((step, index) => (
          <li key={step.id} className={classNames(step.status === "active" && "active", step.status === "complete" && "complete")}>
            <span>{index + 1}</span>
            <div>
              <strong>{step.title}</strong>
              <small>{step.resource}</small>
            </div>
          </li>
        ))}
      </ol>
      <div className="walkthrough-links">
        {(walkthrough?.links || []).map((link) => <a key={link.path} href={link.path}>{link.label}</a>)}
      </div>
    </aside>
  );
}

function ManagerSurface({
  manager,
  sectionState,
  onIndex
}: {
  manager: OntologyManagerState;
  sectionState: OntologySectionState | null;
  onIndex: () => void;
}) {
  return (
    <>
      <div className="manager-header-card">
        <div>
          <span className="object-icon">OT</span>
          <h2>{manager.object_type.display_name}</h2>
          <p>{manager.object_type.description || "No description"}</p>
          <div className="manager-chip-row">
            <StatusBadge value={manager.object_type.status} />
            <StatusBadge value={manager.object_type.visibility} />
            <StatusBadge value={manager.object_type.index_status} />
          </div>
        </div>
        <div className="button-row">
          <button>Actions</button>
          <button>Open in</button>
          <button onClick={onIndex}>Index</button>
        </div>
      </div>
      <div className="manager-grid manager-meta-layout">
        <Panel title="Overview">
          <KeyValueGrid data={{
            plural_name: manager.object_type.plural_name,
            description: manager.object_type.description || "",
            aliases: manager.object_type.aliases.join(", "),
            point_of_contact: manager.object_type.point_of_contact,
            contributors: manager.object_type.contributors.join(", ") || "None",
            ontology: manager.object_type.ontology,
            api_name: manager.object_type.api_name,
            id: manager.object_type.id,
            rid: manager.object_type.rid
          }} />
        </Panel>
        <Panel title="Status">
          <KeyValueGrid data={{
            status: manager.object_type.status,
            visibility: manager.object_type.visibility,
            index_status: manager.object_type.index_status,
            edits: manager.object_type.edits
          }} />
        </Panel>
      </div>
      <div className="manager-grid">
        <Panel title={`Properties ${manager.cards.properties.count}`}>
          <DataTable rows={manager.cards.properties.rows} />
        </Panel>
        <Panel title={`Action Types ${manager.cards.action_types.count}`}>
          <DataTable rows={manager.cards.action_types.rows} />
        </Panel>
        <Panel title={`Link Types ${manager.cards.link_types.count}`}>
          <RelationshipStrip rows={manager.cards.link_types.rows} fallback={manager.object_type.display_name} />
        </Panel>
        <Panel title={`Dependents ${manager.cards.dependents.count}`}>
          <DataTable rows={manager.cards.dependents.rows} />
        </Panel>
        <Panel title={sectionState ? `${sectionState.title} Detail` : "Selected Section"}>
          <KeyValueGrid data={sectionState?.summary || {}} />
          <DataTable rows={sectionState?.rows || []} empty="No rows for this section." />
        </Panel>
        <Panel title="Datasources and Health">
          <DataTable rows={manager.cards.datasources.rows} />
          <KeyValueGrid data={manager.cards.observability} />
        </Panel>
      </div>
    </>
  );
}
