import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  applyNodeChanges,
  type Connection,
  type Edge,
  type Node,
  type NodeChange
} from "@xyflow/react";
import { api, postJson } from "../api";
import {
  addOntologyProperty,
  analyzeOntologyImpact,
  archiveOntologyProperty,
  getOntologyObjectType,
  getOntologySection,
  getOntologyState,
  getOntologyWalkthrough,
  indexObjectType,
  previewOntologyMapping,
  reorderOntologyProperties,
  saveOntologyDatasourceMapping,
  updateOntologyProperty,
  updateOntologyMetadata
} from "../api/workspaceState";
import { DataTable, KeyValueGrid, Panel, RelationshipStrip, StatusBadge } from "../components/data/DataDisplay";
import { useAsyncState } from "../hooks/useAsyncState";
import { asString, classNames, formatValue } from "../utils/format";
import { navigate } from "../utils/navigation";
import { OntologyPackagePanel } from "./OntologyPackagePanel";
import { OntologyReleasePanel } from "./OntologyReleasePanel";
import { OntologyHealthPanel } from "./OntologyHealthPanel";
import { OntologyRegistryPanel } from "./OntologyRegistryPanel";
import type {
  JsonObject,
  OntologyFieldMapping,
  OntologyManagerState,
  OntologyMappingPreview,
  OntologyObjectSummary,
  OntologySectionState,
  OntologyUiState,
  OntologyWalkthrough,
  TableRow
} from "../types";

interface DataAssetsResponseItem extends TableRow {
  id: string;
  display_name?: string;
}

const BASE_TYPE_OPTIONS = ["string", "integer", "number", "boolean", "date", "timestamp", "json", "geometry", "geoshape", "array"];
const STATUS_OPTIONS = ["active", "experimental", "deprecated"];

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
    if (["releases", "health_center", "schema_registry"].includes(selectedSection)) {
      setSectionState(null);
      return;
    }
    let cancelled = false;
    getOntologySection(selectedId, selectedSection)
      .then((nextSection) => !cancelled && setSectionState(nextSection))
      .catch(() => !cancelled && setSectionState(null));
    return () => {
      cancelled = true;
    };
  }, [selectedId, selectedSection, refreshKey]);

  useEffect(() => {
    const workspace = document.querySelector<HTMLElement>(".workspace");
    workspace?.scrollTo({ top: 0, behavior: "auto" });
  }, [selectedId, selectedSection]);

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

  async function saveMetadata(patch: JsonObject) {
    if (!selectedId) return;
    setManager(await updateOntologyMetadata(selectedId, patch));
    setRefreshKey((key) => key + 1);
  }

  async function addProperty(payload: JsonObject) {
    if (!selectedId) return;
    setManager(await addOntologyProperty(selectedId, payload));
    setRefreshKey((key) => key + 1);
  }

  async function updateProperty(propertyName: string, payload: JsonObject) {
    if (!selectedId) return;
    setManager(await updateOntologyProperty(selectedId, propertyName, payload));
    setRefreshKey((key) => key + 1);
  }

  async function archiveProperty(propertyName: string) {
    if (!selectedId) return;
    setManager(await archiveOntologyProperty(selectedId, propertyName));
    setRefreshKey((key) => key + 1);
  }

  async function reorderProperties(order: string[]) {
    if (!selectedId) return;
    setManager(await reorderOntologyProperties(selectedId, order));
    setRefreshKey((key) => key + 1);
  }

  return (
    <section className={classNames("workbench-page ontology-workbench-page", ["releases", "health_center", "schema_registry"].includes(selectedSection) && "release-mode")}>
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
            {Array.from(new Set([...(manager?.navigation || []), "health_center", "releases", "schema_registry"])).map((item) => (
              <button key={item} className={classNames("resource-row", selectedSection === item && "selected")} onClick={() => setSelectedSection(item)}>
                <strong>{item.replace(/_/g, " ")}</strong>
              </button>
            ))}
          </Panel>
          <Panel title="Generate From Dataset" action={<button onClick={createDraft} disabled={!assetId}>Generate</button>}>
            <select aria-label="Dataset for ontology generation" value={assetId} onChange={(event) => setAssetId(event.target.value)}>
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
          <OntologyPackagePanel objectTypeId={selectedId} objectTypeName={manager?.object_type.display_name || selectedId || "Ontology"} />
        </aside>
        <section className="manager-surface">
          {manager && selectedSection === "releases" ? (
            <OntologyReleasePanel objectTypeId={manager.object_type.id} onBack={() => setSelectedSection("overview")} />
          ) : manager && selectedSection === "health_center" ? (
            <OntologyHealthPanel objectTypeId={manager.object_type.id} onBack={() => setSelectedSection("overview")} />
          ) : manager && selectedSection === "schema_registry" ? (
            <OntologyRegistryPanel onBack={() => setSelectedSection("overview")} />
          ) : manager ? (
            <ManagerSurface
              manager={manager}
              objectTypes={state.value?.object_types || []}
              assets={assets.value || []}
              sectionState={sectionState}
              onIndex={markIndexed}
              onSaveMetadata={saveMetadata}
              onAddProperty={addProperty}
              onUpdateProperty={updateProperty}
              onArchiveProperty={archiveProperty}
              onReorderProperties={reorderProperties}
              onResourceMutation={() => setRefreshKey((key) => key + 1)}
            />
          ) : (
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
  objectTypes,
  assets,
  sectionState,
  onIndex,
  onSaveMetadata,
  onAddProperty,
  onUpdateProperty,
  onArchiveProperty,
  onReorderProperties,
  onResourceMutation
}: {
  manager: OntologyManagerState;
  objectTypes: OntologyObjectSummary[];
  assets: DataAssetsResponseItem[];
  sectionState: OntologySectionState | null;
  onIndex: () => void;
  onSaveMetadata: (patch: JsonObject) => Promise<void>;
  onAddProperty: (payload: JsonObject) => Promise<void>;
  onUpdateProperty: (propertyName: string, payload: JsonObject) => Promise<void>;
  onArchiveProperty: (propertyName: string) => Promise<void>;
  onReorderProperties: (order: string[]) => Promise<void>;
  onResourceMutation: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [pluralName, setPluralName] = useState(manager.object_type.plural_name);
  const [description, setDescription] = useState(manager.object_type.description || "");

  useEffect(() => {
    setPluralName(manager.object_type.plural_name);
    setDescription(manager.object_type.description || "");
  }, [manager.object_type.id, manager.object_type.plural_name, manager.object_type.description]);

  async function save() {
    await onSaveMetadata({ plural_name: pluralName, description });
    setEditing(false);
  }

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
          <button onClick={() => setEditing((value) => !value)}>{editing ? "Cancel edit" : "Edit metadata"}</button>
          <button onClick={onIndex}>Index</button>
        </div>
      </div>
      {editing ? (
        <Panel title="Edit Object Type Metadata">
          <div className="metadata-edit-grid">
            <label>
              <span>Plural name</span>
              <input value={pluralName} onChange={(event) => setPluralName(event.target.value)} />
            </label>
            <label>
              <span>Description</span>
              <textarea value={description} onChange={(event) => setDescription(event.target.value)} />
            </label>
            <div className="button-row">
              <button onClick={save}>Save metadata</button>
              <button onClick={() => setEditing(false)}>Cancel</button>
            </div>
          </div>
        </Panel>
      ) : null}
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
      <OntologyRelationshipDesigner objectTypes={objectTypes} selectedObjectTypeId={manager.object_type.id} />
      <DatasetMappingPanel objectTypeId={manager.object_type.id} assets={assets} onSaved={onResourceMutation} />
      <div className="manager-grid">
        <PropertyEditor
          manager={manager}
          onAddProperty={onAddProperty}
          onUpdateProperty={onUpdateProperty}
          onArchiveProperty={onArchiveProperty}
          onReorderProperties={onReorderProperties}
          onAnalyzeImpact={(propertyName) => analyzeOntologyImpact(manager.object_type.id, [{ operation: "archive", property_name: propertyName }])}
        />
        <ActionTypeEditor objectTypeId={manager.object_type.id} rows={manager.cards.action_types.rows} onMutation={onResourceMutation} />
        <LinkTypeEditor rows={manager.cards.link_types.rows} fallback={manager.object_type.display_name} onMutation={onResourceMutation} />
        <Panel title={`Downstream Contracts ${manager.cards.contract_health.count}`} action={<StatusBadge value={manager.cards.contract_health.status} />}>
          <div className="manager-contract-counts">
            {Object.entries(manager.cards.contract_health.counts).map(([status, count]) => (
              <span key={status}><strong>{count}</strong>{status.replace(/_/g, " ")}</span>
            ))}
          </div>
          <DataTable rows={manager.cards.contract_health.rows} empty="No published consumer contracts reference this object type." />
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

function ActionTypeEditor({ objectTypeId, rows, onMutation }: { objectTypeId: string; rows: TableRow[]; onMutation: () => void }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [message, setMessage] = useState("");

  async function createAction() {
    const displayName = name.trim();
    if (!displayName) return;
    const id = `${objectTypeId}_${displayName}`.toLowerCase().replace(/[^a-z0-9_]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 96);
    try {
      await postJson("/action-types", {
        id,
        display_name: displayName,
        description: description.trim() || `Governed action for ${objectTypeId}.`,
        parameters: {},
        rules: { object_type_id: objectTypeId, operations: [] }
      });
      setName("");
      setDescription("");
      setMessage("Action type created and audited.");
      onMutation();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not create action type.");
    }
  }

  return (
    <Panel title={`Action Types ${rows.length}`} className="ontology-resource-editor">
      <div className="resource-create-row">
        <input aria-label="New action name" value={name} onChange={(event) => setName(event.target.value)} placeholder="Action name" />
        <input aria-label="New action description" value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Description" />
        <button onClick={createAction} disabled={!name.trim()}>Add action</button>
      </div>
      {message ? <div className="operation-message" role="status">{message}</div> : null}
      {rows.length ? rows.map((row) => <EditableOntologyResource key={asString(row.id)} kind="action" row={row} onMutation={onMutation} />) : <div className="empty">No action types use this object type.</div>}
    </Panel>
  );
}

function LinkTypeEditor({ rows, fallback, onMutation }: { rows: TableRow[]; fallback: string; onMutation: () => void }) {
  if (!rows.length) return <Panel title="Link Types 0"><RelationshipStrip rows={rows} fallback={fallback} /></Panel>;
  return (
    <Panel title={`Link Types ${rows.length}`} className="ontology-resource-editor">
      {rows.map((row) => <EditableOntologyResource key={asString(row.id)} kind="link" row={row} onMutation={onMutation} />)}
    </Panel>
  );
}

function EditableOntologyResource({ kind, row, onMutation }: { kind: "action" | "link"; row: TableRow; onMutation: () => void }) {
  const [displayName, setDisplayName] = useState(asString(row.display_name || row.id));
  const [description, setDescription] = useState(asString(row.description));
  const [cardinality, setCardinality] = useState(asString(row.cardinality, "MANY_TO_MANY"));
  const [message, setMessage] = useState("");

  async function save() {
    const body: JsonObject = { display_name: displayName, description };
    if (kind === "link") body.cardinality = cardinality;
    try {
      await api(`/${kind}-types/${encodeURIComponent(asString(row.id))}`, { method: "PATCH", body: JSON.stringify(body) });
      setMessage("Saved and audited.");
      onMutation();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not save resource.");
    }
  }

  return (
    <article className="ontology-resource-row">
      <div>
        <strong>{asString(row.id)}</strong>
        {kind === "link" ? <small>{asString(row.source_object_type_id)} to {asString(row.target_object_type_id)}</small> : null}
      </div>
      <input aria-label={`${kind} display name`} value={displayName} onChange={(event) => setDisplayName(event.target.value)} />
      <input aria-label={`${kind} description`} value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Description" />
      {kind === "link" ? (
        <select aria-label="Link cardinality" value={cardinality} onChange={(event) => setCardinality(event.target.value)}>
          <option value="ONE_TO_ONE">One to one</option>
          <option value="ONE_TO_MANY">One to many</option>
          <option value="MANY_TO_MANY">Many to many</option>
        </select>
      ) : null}
      <button onClick={save}>Save</button>
      {message ? <span className="resource-save-state" role="status">{message}</span> : null}
    </article>
  );
}

function DatasetMappingPanel({ objectTypeId, assets, onSaved }: { objectTypeId: string; assets: DataAssetsResponseItem[]; onSaved: () => void }) {
  const [assetId, setAssetId] = useState("");
  const [preview, setPreview] = useState<OntologyMappingPreview | null>(null);
  const [mappings, setMappings] = useState<OntologyFieldMapping[]>([]);
  const [draggedField, setDraggedField] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  async function loadSuggestions(nextAssetId = assetId) {
    if (!nextAssetId) return;
    setBusy(true);
    setMessage("Generating field mapping suggestions...");
    try {
      const result = await previewOntologyMapping(nextAssetId, objectTypeId);
      setPreview(result);
      setMappings(result.mappings);
      setMessage(`Suggested ${result.mappings.length} compatible field mappings.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not preview mapping.");
    } finally {
      setBusy(false);
    }
  }

  async function refreshPreview(nextMappings = mappings) {
    if (!assetId) return;
    setBusy(true);
    try {
      const result = await previewOntologyMapping(assetId, objectTypeId, nextMappings);
      setPreview(result);
      setMappings(result.mappings);
      setMessage(`Mapping validation: ${result.status}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not validate mapping.");
    } finally {
      setBusy(false);
    }
  }

  function mapField(targetProperty: string, sourceField = draggedField) {
    if (!sourceField) return;
    const next = [...mappings.filter((item) => item.target_property !== targetProperty && item.source_field !== sourceField), { source_field: sourceField, target_property: targetProperty }];
    setMappings(next);
    setDraggedField("");
    void refreshPreview(next);
  }

  async function save() {
    if (!assetId || !preview || preview.errors.length) return;
    setBusy(true);
    try {
      await saveOntologyDatasourceMapping(objectTypeId, assetId, mappings);
      setMessage("Datasource mapping saved and audited. It is ready for an ontology output node.");
      onSaved();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not save mapping.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel title="Dataset to Ontology Mapping" className="ontology-mapping-panel" action={<StatusBadge value={preview?.status || "NOT_CONFIGURED"} />}>
      <div className="mapping-toolbar">
        <label>Source dataset<select value={assetId} onChange={(event) => { setAssetId(event.target.value); setPreview(null); setMappings([]); }}><option value="">Choose dataset</option>{assets.map((asset) => <option value={asset.id} key={asset.id}>{asset.display_name || asset.id}</option>)}</select></label>
        <button onClick={() => loadSuggestions()} disabled={!assetId || busy}>Suggest mappings</button>
        <button onClick={() => refreshPreview()} disabled={!assetId || busy}>Preview objects</button>
        <button className="primary-action" onClick={save} disabled={!preview || Boolean(preview.errors.length) || busy}>Save mapping</button>
      </div>
      {message ? <div className="workbench-status-strip" role="status">{message}</div> : null}
      {preview ? (
        <>
          <div className="ontology-mapping-grid">
            <section><h3>Dataset fields</h3><p>Drag a source field onto a target property.</p><div className="mapping-source-list">{preview.source_fields.map((field) => <button key={field.name} draggable onDragStart={() => setDraggedField(field.name)} className={classNames(field.mapped && "mapped")}><strong>{field.name}</strong><small>{field.inferred_type}</small></button>)}</div></section>
            <section><h3>Object properties</h3><p>Required properties must be mapped before saving.</p><div className="mapping-target-list">{preview.target_properties.map((property) => {
              const source = mappings.find((item) => item.target_property === property.name)?.source_field;
              const compatibility = preview.compatibility.find((item) => item.target_property === property.name);
              return <div key={property.name} onDragOver={(event) => event.preventDefault()} onDrop={() => mapField(property.name)} className={classNames("mapping-target", source && "mapped", compatibility && !compatibility.compatible && "incompatible")}><span><strong>{property.name}</strong><small>{property.base_type || property.type}{property.required ? " · required" : ""}</small></span><select aria-label={`Map ${property.name}`} value={source || ""} onChange={(event) => mapField(property.name, event.target.value)}><option value="">Not mapped</option>{preview.source_fields.map((field) => <option value={field.name} key={field.name}>{field.name}</option>)}</select></div>;
            })}</div></section>
          </div>
          {preview.errors.length || preview.warnings.length ? <DataTable rows={[...preview.errors, ...preview.warnings]} empty="Mapping is valid." /> : null}
          <details className="mapping-preview-drawer" open><summary>Hydrated object preview · {preview.hydrated_preview.length} rows</summary><DataTable rows={preview.hydrated_preview} empty="No objects can be previewed." /></details>
        </>
      ) : <div className="empty">Choose a dataset to map fields and preview object hydration.</div>}
    </Panel>
  );
}

interface OntologyLinkType extends TableRow {
  id: string;
  display_name: string;
  source_object_type_id: string;
  target_object_type_id: string;
  cardinality: string;
}

function OntologyRelationshipDesigner({ objectTypes, selectedObjectTypeId }: { objectTypes: OntologyObjectSummary[]; selectedObjectTypeId: string }) {
  const [refreshKey, setRefreshKey] = useState(0);
  const [cardinality, setCardinality] = useState("MANY_TO_MANY");
  const [message, setMessage] = useState("");
  const links = useAsyncState<OntologyLinkType[]>(() => api<OntologyLinkType[]>("/link-types"), [refreshKey]);
  const [nodes, setNodes] = useState<Node<JsonObject>[]>([]);

  useEffect(() => {
    setNodes(objectTypes.map((objectType, index) => ({
      id: objectType.id,
      position: { x: (index % 4) * 220, y: Math.floor(index / 4) * 130 },
      data: {
        label: objectType.display_name,
        property_count: objectType.property_count,
        selected: objectType.id === selectedObjectTypeId
      },
      className: objectType.id === selectedObjectTypeId ? "ontology-graph-node selected" : "ontology-graph-node",
      style: { borderColor: objectType.id === selectedObjectTypeId ? "#2386a8" : "#7c5aa6" }
    })));
  }, [objectTypes, selectedObjectTypeId]);

  const edges = useMemo<Edge[]>(() => (links.value || []).map((link) => ({
    id: link.id,
    source: link.source_object_type_id,
    target: link.target_object_type_id,
    label: `${link.display_name} · ${link.cardinality.replace(/_/g, " ").toLowerCase()}`,
    type: "smoothstep",
    markerEnd: { type: "arrowclosed" as const }
  })).filter((edge) => objectTypes.some((item) => item.id === edge.source) && objectTypes.some((item) => item.id === edge.target)), [links.value, objectTypes]);

  const onNodesChange = useCallback((changes: NodeChange<Node<JsonObject>>[]) => {
    setNodes((current) => applyNodeChanges(changes, current));
  }, []);

  async function createRelationship(connection: Connection) {
    if (!connection.source || !connection.target) return;
    const normalized = `${connection.source}_${connection.target}_link`.replace(/[^a-zA-Z0-9_]/g, "_").slice(0, 96);
    try {
      await postJson<OntologyLinkType>("/link-types", {
        id: normalized,
        display_name: `${connection.source.replace(/_/g, " ")} to ${connection.target.replace(/_/g, " ")}`,
        description: "Created in the visual ontology relationship designer.",
        source_object_type_id: connection.source,
        target_object_type_id: connection.target,
        cardinality
      });
      setMessage("Relationship created and audited.");
      setRefreshKey((key) => key + 1);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not create relationship.");
    }
  }

  return (
    <Panel
      title="Object and Link Designer"
      className="ontology-relationship-designer"
      action={(
        <label className="inline-field">
          <span>New link cardinality</span>
          <select value={cardinality} onChange={(event) => setCardinality(event.target.value)}>
            <option value="ONE_TO_ONE">One to one</option>
            <option value="ONE_TO_MANY">One to many</option>
            <option value="MANY_TO_MANY">Many to many</option>
          </select>
        </label>
      )}
    >
      <p className="panel-description">Drag object types to arrange the ontology. Connect node ports to create a governed link type.</p>
      {message ? <div className="workbench-status-strip" role="status">{message}</div> : null}
      <div className="ontology-relationship-canvas" aria-label="Visual ontology relationship designer">
        {nodes.length ? (
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onConnect={createRelationship}
            nodesDraggable
            nodesConnectable
            defaultViewport={{ x: 20, y: 20, zoom: 0.75 }}
            minZoom={0.25}
          >
            <Background gap={22} color="#d6dde1" />
            <MiniMap pannable zoomable nodeColor={(node) => node.id === selectedObjectTypeId ? "#2386a8" : "#7c5aa6"} />
            <Controls showInteractive={false} />
          </ReactFlow>
        ) : <div className="empty">Apply an ontology draft to begin designing relationships.</div>}
      </div>
    </Panel>
  );
}

function rowName(row: TableRow) {
  return asString(row.name || row.api_name);
}

function rowEditState(row: TableRow): JsonObject {
  return {
    name: rowName(row),
    display_name: asString(row.display_name, rowName(row)),
    base_type: asString(row.base_type, "string"),
    status: asString(row.status, "active"),
    required: Boolean(row.required),
    indexed: Boolean(row.indexed),
    sensitive: Boolean(row.sensitive),
    description: asString(row.description, ""),
    minimum: row.minimum ?? "",
    maximum: row.maximum ?? "",
    unit: asString(row.unit, ""),
    pattern: asString(row.pattern, ""),
    enum_text: Array.isArray(row.enum) ? row.enum.join(", ") : ""
  };
}

function propertyPayload(draft: JsonObject): JsonObject {
  const payload = { ...draft };
  const enumText = asString(payload.enum_text).trim();
  payload.enum = enumText ? enumText.split(",").map((value) => value.trim()).filter(Boolean) : [];
  delete payload.enum_text;
  for (const field of ["minimum", "maximum"] as const) {
    if (payload[field] === "" || payload[field] === null || payload[field] === undefined) payload[field] = null;
    else payload[field] = Number(payload[field]);
  }
  return payload;
}

function PropertyEditor({
  manager,
  onAddProperty,
  onUpdateProperty,
  onArchiveProperty,
  onReorderProperties,
  onAnalyzeImpact
}: {
  manager: OntologyManagerState;
  onAddProperty: (payload: JsonObject) => Promise<void>;
  onUpdateProperty: (propertyName: string, payload: JsonObject) => Promise<void>;
  onArchiveProperty: (propertyName: string) => Promise<void>;
  onReorderProperties: (order: string[]) => Promise<void>;
  onAnalyzeImpact: (propertyName: string) => Promise<JsonObject>;
}) {
  const [editing, setEditing] = useState(false);
  const [drafts, setDrafts] = useState<Record<string, JsonObject>>({});
  const [newField, setNewField] = useState<JsonObject>({ name: "", display_name: "", base_type: "string", status: "active", required: false, indexed: false, sensitive: false, description: "", unit: "", minimum: "", maximum: "", enum_text: "" });
  const [confirmArchive, setConfirmArchive] = useState("");
  const [dragName, setDragName] = useState("");
  const [impactMessage, setImpactMessage] = useState("");
  const rows = manager.cards.properties.rows;

  useEffect(() => {
    setDrafts(Object.fromEntries(rows.map((row) => [rowName(row), rowEditState(row)])));
  }, [manager.object_type.id, rows.length]);

  function updateDraft(name: string, patch: JsonObject) {
    setDrafts((current) => ({ ...current, [name]: { ...(current[name] || {}), ...patch } }));
  }

  async function addField() {
    const name = asString(newField.name).trim();
    if (!name) return;
    await onAddProperty(propertyPayload(newField));
    setNewField({ name: "", display_name: "", base_type: "string", status: "active", required: false, indexed: false, sensitive: false, description: "", unit: "", minimum: "", maximum: "", enum_text: "" });
  }

  async function saveRow(originalName: string) {
    await onUpdateProperty(originalName, propertyPayload(drafts[originalName] || {}));
  }

  async function archiveRow(name: string) {
    if (confirmArchive !== name) {
      const impact = await onAnalyzeImpact(name);
      const summary = impact.summary as JsonObject | undefined;
      setImpactMessage(`${asString(impact.severity, "LOW")} impact: ${formatValue(summary?.objects || 0)} objects and ${formatValue(summary?.pipelines || 0)} pipelines may be affected. Confirm to archive; values remain recoverable.`);
      setConfirmArchive(name);
      return;
    }
    await onArchiveProperty(name);
    setConfirmArchive("");
    setImpactMessage("");
  }

  function orderedNames() {
    return rows.map(rowName).filter(Boolean);
  }

  async function moveByButton(name: string, delta: number) {
    const order = orderedNames();
    const index = order.indexOf(name);
    const nextIndex = index + delta;
    if (index < 0 || nextIndex < 0 || nextIndex >= order.length) return;
    const [item] = order.splice(index, 1);
    order.splice(nextIndex, 0, item);
    await onReorderProperties(order);
  }

  async function dropOn(targetName: string) {
    if (!dragName || dragName === targetName) return;
    const order = orderedNames().filter((name) => name !== dragName);
    const targetIndex = order.indexOf(targetName);
    order.splice(targetIndex < 0 ? order.length : targetIndex, 0, dragName);
    setDragName("");
    await onReorderProperties(order);
  }

  return (
    <Panel title={`Properties ${manager.cards.properties.count}`} className="property-panel" action={<button onClick={() => setEditing((value) => !value)}>{editing ? "Done" : "Edit fields"}</button>}>
      {editing ? (
        <div className="property-editor">
          {impactMessage ? <div className="ontology-impact-warning" role="alert">{impactMessage}</div> : null}
          <div className="property-add-row">
            <input value={asString(newField.name)} onChange={(event) => setNewField({ ...newField, name: event.target.value })} placeholder="newFieldName" />
            <select value={asString(newField.base_type, "string")} onChange={(event) => setNewField({ ...newField, base_type: event.target.value })}>
              {BASE_TYPE_OPTIONS.map((type) => <option key={type} value={type}>{type}</option>)}
            </select>
            <label>
              <input type="checkbox" checked={Boolean(newField.required)} onChange={(event) => setNewField({ ...newField, required: event.target.checked })} />
              Required
            </label>
            <input value={asString(newField.description)} onChange={(event) => setNewField({ ...newField, description: event.target.value })} placeholder="Description" />
            <button onClick={addField}>Add field</button>
            <details className="property-advanced">
              <summary>Constraints, indexing, and display</summary>
              <div className="property-advanced-grid">
                <label><span>Display name</span><input value={asString(newField.display_name)} onChange={(event) => setNewField({ ...newField, display_name: event.target.value })} placeholder="Human-readable label" /></label>
                <label><span>Unit</span><input value={asString(newField.unit)} onChange={(event) => setNewField({ ...newField, unit: event.target.value })} placeholder="psi, deg C, km/h" /></label>
                <label><span>Minimum</span><input type="number" value={asString(newField.minimum)} onChange={(event) => setNewField({ ...newField, minimum: event.target.value })} /></label>
                <label><span>Maximum</span><input type="number" value={asString(newField.maximum)} onChange={(event) => setNewField({ ...newField, maximum: event.target.value })} /></label>
                <label><span>Enum values</span><input value={asString(newField.enum_text)} onChange={(event) => setNewField({ ...newField, enum_text: event.target.value })} placeholder="RUNNING, DEGRADED, OFFLINE" /></label>
                <label className="checkbox-field"><input type="checkbox" checked={Boolean(newField.indexed)} onChange={(event) => setNewField({ ...newField, indexed: event.target.checked })} />Indexed</label>
                <label className="checkbox-field"><input type="checkbox" checked={Boolean(newField.sensitive)} onChange={(event) => setNewField({ ...newField, sensitive: event.target.checked })} />Sensitive / masked</label>
              </div>
            </details>
          </div>
          <div className="property-field-list">
            {rows.map((row) => {
              const name = rowName(row);
              const draft = drafts[name] || rowEditState(row);
              return (
                <article
                  key={name}
                  className="property-field-row"
                  draggable
                  onDragStart={() => setDragName(name)}
                  onDragOver={(event) => event.preventDefault()}
                  onDrop={() => dropOn(name)}
                >
                  <span className="drag-handle" title="Drag to reorder">::</span>
                  <input value={asString(draft.name)} onChange={(event) => updateDraft(name, { name: event.target.value })} />
                  <select value={asString(draft.base_type, "string")} onChange={(event) => updateDraft(name, { base_type: event.target.value })}>
                    {BASE_TYPE_OPTIONS.map((type) => <option key={type} value={type}>{type}</option>)}
                  </select>
                  <select value={asString(draft.status, "active")} onChange={(event) => updateDraft(name, { status: event.target.value })}>
                    {STATUS_OPTIONS.map((status) => <option key={status} value={status}>{status}</option>)}
                  </select>
                  <label>
                    <input type="checkbox" checked={Boolean(draft.required)} onChange={(event) => updateDraft(name, { required: event.target.checked })} />
                    Required
                  </label>
                  <input value={asString(draft.description)} onChange={(event) => updateDraft(name, { description: event.target.value })} placeholder="Description" />
                  <button onClick={() => saveRow(name)}>Save</button>
                  <button onClick={() => moveByButton(name, -1)}>Up</button>
                  <button onClick={() => moveByButton(name, 1)}>Down</button>
                  <button disabled={row.can_delete === false} onClick={() => archiveRow(name)}>
                    {confirmArchive === name ? "Confirm archive" : "Archive"}
                  </button>
                  <details className="property-advanced">
                    <summary>Constraints, indexing, and display</summary>
                    <div className="property-advanced-grid">
                      <label><span>Display name</span><input value={asString(draft.display_name)} onChange={(event) => updateDraft(name, { display_name: event.target.value })} /></label>
                      <label><span>Unit</span><input value={asString(draft.unit)} onChange={(event) => updateDraft(name, { unit: event.target.value })} placeholder="Optional unit" /></label>
                      <label><span>Minimum</span><input type="number" value={asString(draft.minimum)} onChange={(event) => updateDraft(name, { minimum: event.target.value })} /></label>
                      <label><span>Maximum</span><input type="number" value={asString(draft.maximum)} onChange={(event) => updateDraft(name, { maximum: event.target.value })} /></label>
                      <label><span>Enum values</span><input value={asString(draft.enum_text)} onChange={(event) => updateDraft(name, { enum_text: event.target.value })} placeholder="Comma-separated" /></label>
                      <label><span>Pattern</span><input value={asString(draft.pattern)} onChange={(event) => updateDraft(name, { pattern: event.target.value })} placeholder="Optional regex" /></label>
                      <label className="checkbox-field"><input type="checkbox" checked={Boolean(draft.indexed)} onChange={(event) => updateDraft(name, { indexed: event.target.checked })} />Indexed</label>
                      <label className="checkbox-field"><input type="checkbox" checked={Boolean(draft.sensitive)} onChange={(event) => updateDraft(name, { sensitive: event.target.checked })} />Sensitive / masked</label>
                    </div>
                  </details>
                </article>
              );
            })}
          </div>
        </div>
      ) : (
        <DataTable rows={rows} />
      )}
    </Panel>
  );
}
