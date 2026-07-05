import { useEffect, useState } from "react";
import { Page } from "../components/workbench/Workbench";
import {
  DataTable,
  DeveloperEvidence,
  EmptyState,
  ErrorBanner,
  KeyValueGrid,
  LoadingState,
  Metric,
  Panel,
  StatusBadge
} from "../components/data/DataDisplay";
import { useAsyncState } from "../hooks/useAsyncState";
import { asString, classNames, formatValue } from "../utils/format";
import type { JsonObject, TableRow } from "../types";
import {
  createDataAsset,
  createMediaSet,
  dataAssetDownloadUrl,
  getDataAsset,
  getDatasetSchema,
  listDataAssets,
  listMediaItems,
  listMediaSets,
  mediaItemContentUrl,
  uploadDataAssetFile,
  uploadMediaItem,
  type DataAsset,
  type DatasetSchema,
  type MediaItem,
  type MediaSet,
  type MediaUploadResult,
  type UploadResult
} from "../api/dataMediaApi";

const MEDIA_TYPES = ["image", "pdf", "audio", "video", "document", "multimodal"];

function slugify(value: string): string {
  return value.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
}

export function DataMedia() {
  const [refreshKey, setRefreshKey] = useState(0);
  const reload = () => setRefreshKey((key) => key + 1);

  return (
    <Page title="Data & Media" subtitle="Ingest real files into datasets and media sets, then inspect the parsed records and stored content.">
      <DatasetSection refreshKey={refreshKey} reload={reload} />
      <MediaSection refreshKey={refreshKey} reload={reload} />
    </Page>
  );
}

// ---------------------------------------------------------------------------
// Datasets
// ---------------------------------------------------------------------------

function DatasetSection({ refreshKey, reload }: { refreshKey: number; reload: () => void }) {
  const [selectedId, setSelectedId] = useState("");
  const [newName, setNewName] = useState("");
  const [newDescription, setNewDescription] = useState("");
  const [uploadMode, setUploadMode] = useState<"replace" | "append">("replace");
  const [lastUpload, setLastUpload] = useState<UploadResult | null>(null);
  const [actionError, setActionError] = useState("");
  const [busy, setBusy] = useState(false);
  const [declaredSchema, setDeclaredSchema] = useState<DatasetSchema | null>(null);

  const assets = useAsyncState<DataAsset[]>(listDataAssets, [refreshKey]);
  const detail = useAsyncState<DataAsset | null>(
    () => (selectedId ? getDataAsset(selectedId) : Promise.resolve(null)),
    [selectedId, refreshKey]
  );

  useEffect(() => {
    if (!selectedId && assets.value && assets.value.length && !detail.value) {
      setSelectedId(assets.value[0].id);
    }
  }, [assets.value, selectedId, detail.value]);

  // Declared (name/type) schema is best-effort: /datasets/{id}/schema 404s until declared.
  useEffect(() => {
    if (!selectedId) {
      setDeclaredSchema(null);
      return;
    }
    let cancelled = false;
    getDatasetSchema(selectedId)
      .then((schema) => !cancelled && setDeclaredSchema(schema))
      .catch(() => !cancelled && setDeclaredSchema(null));
    return () => {
      cancelled = true;
    };
  }, [selectedId, refreshKey]);

  async function createDataset() {
    const name = newName.trim();
    if (!name) return;
    setActionError("");
    setBusy(true);
    try {
      const id = slugify(name) || `dataset_${Date.now()}`;
      const created = await createDataAsset({ id, display_name: name, description: newDescription.trim() || undefined });
      setNewName("");
      setNewDescription("");
      setSelectedId(created.id);
      setLastUpload(null);
      reload();
    } catch (error) {
      setActionError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function onUpload(event: React.ChangeEvent<HTMLInputElement>) {
    const input = event.target;
    const file = input.files?.[0];
    if (!file || !selectedId) return;
    setActionError("");
    setBusy(true);
    try {
      const result = await uploadDataAssetFile(selectedId, file, uploadMode);
      setLastUpload(result);
      reload();
    } catch (error) {
      setActionError((error as Error).message);
    } finally {
      setBusy(false);
      input.value = ""; // allow re-selecting the same file
    }
  }

  const selectedAsset = detail.value;
  const inferredSchema: JsonObject = selectedAsset?.asset_schema || {};
  const records: TableRow[] = selectedAsset?.records || [];
  const schemaRows: TableRow[] = declaredSchema?.columns?.length
    ? declaredSchema.columns.map((column) => ({ column: column.name, type: column.type, source: "declared" }))
    : Object.entries(inferredSchema).map(([column, type]) => ({ column, type: formatValue(type), source: "inferred" }));

  return (
    <>
      <div className="workspace-summary-row">
        <Metric label="Datasets" value={assets.value?.length ?? 0} />
        <Metric label="Selected records" value={selectedAsset?.records?.length ?? 0} />
        <Metric label="Schema columns" value={schemaRows.length} />
        <Metric label="Last format" value={lastUpload?.source_format || selectedAsset?.kind || "-"} />
      </div>
      <ErrorBanner message={actionError || assets.error || detail.error} />
      {(assets.loading || detail.loading) && <LoadingState label="Loading datasets..." />}
      <div className="two-col">
        <Panel title={`Datasets ${assets.value?.length ?? 0}`}>
          <div className="button-row" style={{ flexWrap: "wrap" }}>
            <input className="compact-input" placeholder="New dataset name" value={newName} onChange={(event) => setNewName(event.target.value)} />
            <input className="compact-input" placeholder="Description (optional)" value={newDescription} onChange={(event) => setNewDescription(event.target.value)} />
            <button onClick={createDataset} disabled={busy || !newName.trim()}>Create dataset</button>
          </div>
          {(assets.value || []).length ? (
            (assets.value || []).map((asset) => (
              <button
                key={asset.id}
                className={classNames("resource-row", selectedId === asset.id && "selected")}
                onClick={() => {
                  setSelectedId(asset.id);
                  setLastUpload(null);
                }}
              >
                <strong>{asset.display_name || asset.id}</strong>
                <span>{asString(asset.kind, "dataset")} · {asset.records?.length ?? 0} records</span>
              </button>
            ))
          ) : (
            <EmptyState title="No datasets yet" description="Create a dataset, then upload a CSV/JSON/JSONL file into it." />
          )}
        </Panel>
        <Panel
          title="Upload File"
          action={selectedId ? <a className="legacy-button compact" href={dataAssetDownloadUrl(selectedId)}>Download raw file</a> : undefined}
        >
          {selectedId ? (
            <div className="summary-list">
              <div className="button-row" style={{ flexWrap: "wrap", alignItems: "center" }}>
                <label>
                  <span style={{ marginRight: 6 }}>Mode</span>
                  <select value={uploadMode} onChange={(event) => setUploadMode(event.target.value as "replace" | "append")}>
                    <option value="replace">replace</option>
                    <option value="append">append</option>
                  </select>
                </label>
                <input type="file" accept=".csv,.json,.jsonl,.ndjson,.parquet,.pq" disabled={busy} onChange={onUpload} />
              </div>
              <p className="empty" style={{ margin: 0 }}>
                Uploads to <code>/data-assets/{selectedId}/upload</code> as multipart form data. CSV, JSON, JSONL, and Parquet are parsed into records.
              </p>
              {lastUpload ? (
                <KeyValueGrid data={{
                  source_format: lastUpload.source_format,
                  added: lastUpload.added,
                  record_count: lastUpload.record_count,
                  columns: lastUpload.columns.join(", "),
                  bytes: lastUpload.bytes,
                  file_ref: lastUpload.file_ref
                }} />
              ) : (
                <div className="empty">Choose a file to ingest records into the selected dataset.</div>
              )}
            </div>
          ) : (
            <EmptyState title="Select a dataset" description="Pick a dataset on the left to upload a file into it." />
          )}
        </Panel>
      </div>
      <div className="two-col">
        <Panel title={selectedAsset ? `Records — ${selectedAsset.display_name || selectedAsset.id}` : "Records"}>
          {selectedAsset ? (
            <DataTable rows={records} empty="No records yet. Upload a file to populate this dataset." />
          ) : (
            <EmptyState title="No dataset selected" />
          )}
        </Panel>
        <Panel title={`Schema ${schemaRows.length}`}>
          {schemaRows.length ? (
            <>
              <StatusBadge value={declaredSchema?.columns?.length ? "declared" : "inferred"} />
              <DataTable rows={schemaRows} empty="No schema columns." />
            </>
          ) : (
            <div className="empty">Schema is inferred once a file is uploaded, or declared via the datasets schema endpoint.</div>
          )}
        </Panel>
      </div>
      {selectedAsset ? (
        <DeveloperEvidence title="Developer evidence: selected dataset detail">
          <KeyValueGrid data={{
            id: selectedAsset.id,
            display_name: selectedAsset.display_name,
            kind: selectedAsset.kind,
            record_count: selectedAsset.records?.length ?? 0,
            column_count: Object.keys(inferredSchema).length,
            updated_at: selectedAsset.updated_at ?? "-"
          }} />
        </DeveloperEvidence>
      ) : null}
    </>
  );
}

// ---------------------------------------------------------------------------
// Media
// ---------------------------------------------------------------------------

function MediaSection({ refreshKey, reload }: { refreshKey: number; reload: () => void }) {
  const [selectedId, setSelectedId] = useState("");
  const [newName, setNewName] = useState("");
  const [newType, setNewType] = useState("document");
  const [actionError, setActionError] = useState("");
  const [busy, setBusy] = useState(false);
  const [lastUpload, setLastUpload] = useState<MediaUploadResult | null>(null);

  const sets = useAsyncState<MediaSet[]>(listMediaSets, [refreshKey]);
  const items = useAsyncState<MediaItem[]>(
    () => (selectedId ? listMediaItems(selectedId) : Promise.resolve([])),
    [selectedId, refreshKey]
  );

  useEffect(() => {
    if (!selectedId && sets.value && sets.value.length) {
      setSelectedId(sets.value[0].id);
    }
  }, [sets.value, selectedId]);

  async function createSet() {
    const name = newName.trim();
    if (!name) return;
    setActionError("");
    setBusy(true);
    try {
      const created = await createMediaSet({ id: slugify(name) || undefined, display_name: name, media_type: newType });
      setNewName("");
      setSelectedId(created.id);
      setLastUpload(null);
      reload();
    } catch (error) {
      setActionError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function onUpload(event: React.ChangeEvent<HTMLInputElement>) {
    const input = event.target;
    const file = input.files?.[0];
    if (!file || !selectedId) return;
    setActionError("");
    setBusy(true);
    try {
      const result = await uploadMediaItem(selectedId, file);
      setLastUpload(result);
      reload();
    } catch (error) {
      setActionError((error as Error).message);
    } finally {
      setBusy(false);
      input.value = "";
    }
  }

  const mediaItems = items.value || [];

  return (
    <>
      <ErrorBanner message={actionError || sets.error || items.error} />
      {(sets.loading || items.loading) && <LoadingState label="Loading media sets..." />}
      <div className="two-col">
        <Panel title={`Media Sets ${sets.value?.length ?? 0}`}>
          <div className="button-row" style={{ flexWrap: "wrap" }}>
            <input className="compact-input" placeholder="New media set name" value={newName} onChange={(event) => setNewName(event.target.value)} />
            <select value={newType} onChange={(event) => setNewType(event.target.value)}>
              {MEDIA_TYPES.map((type) => <option key={type} value={type}>{type}</option>)}
            </select>
            <button onClick={createSet} disabled={busy || !newName.trim()}>Create media set</button>
          </div>
          {(sets.value || []).length ? (
            (sets.value || []).map((set) => (
              <button
                key={set.id}
                className={classNames("resource-row", selectedId === set.id && "selected")}
                onClick={() => {
                  setSelectedId(set.id);
                  setLastUpload(null);
                }}
              >
                <strong>{set.display_name || set.id}</strong>
                <span>{set.media_type}</span>
              </button>
            ))
          ) : (
            <EmptyState title="No media sets yet" description="Create a media set, then upload a binary item into it." />
          )}
        </Panel>
        <Panel title="Upload Media Item">
          {selectedId ? (
            <div className="summary-list">
              <input type="file" disabled={busy} onChange={onUpload} />
              <p className="empty" style={{ margin: 0 }}>
                Uploads binary content to <code>/media-sets/{selectedId}/items/upload</code>. Text-like files also populate extractable text.
              </p>
              {lastUpload ? (
                <KeyValueGrid data={{
                  id: lastUpload.id,
                  filename: lastUpload.filename,
                  mime_type: lastUpload.mime_type,
                  size_bytes: lastUpload.size_bytes,
                  has_text: lastUpload.has_text
                }} />
              ) : (
                <div className="empty">Choose a file to store a media item in this set.</div>
              )}
            </div>
          ) : (
            <EmptyState title="Select a media set" description="Pick a media set on the left to upload an item into it." />
          )}
        </Panel>
      </div>
      <Panel title={`Media Items ${mediaItems.length}`}>
        {mediaItems.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>filename</th>
                  <th>mime_type</th>
                  <th>size_bytes</th>
                  <th>has_text</th>
                  <th>content</th>
                </tr>
              </thead>
              <tbody>
                {mediaItems.map((item) => (
                  <tr key={item.id}>
                    <td title={item.filename}>{item.filename}</td>
                    <td title={item.mime_type}>{item.mime_type}</td>
                    <td>{item.size_bytes}</td>
                    <td>{item.text_content ? "yes" : "no"}</td>
                    <td>
                      <a href={mediaItemContentUrl(item.id)} target="_blank" rel="noreferrer">open</a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="empty">No media items yet. Upload a file into the selected media set.</div>
        )}
      </Panel>
    </>
  );
}
