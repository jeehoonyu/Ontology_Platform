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
  StatusBadge,
  UnknownResource
} from "../components/data/DataDisplay";
import { DataGrid } from "../components/data/DataGrid";
import { useAsyncState } from "../hooks/useAsyncState";
import { isNotFound } from "../api";
import { openResource, useRouteParams } from "../utils/navigation";
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

/** A fetch's answer, with the id it answers, so nothing shown belongs to a dataset no longer open. */
type Answer<T> = { id: string; value?: T; error?: string; notFound?: boolean };

function DatasetSection({ refreshKey, reload }: { refreshKey: number; reload: () => void }) {
  // The dataset is the URL's (GOAL_FOUNDATIONS A6); with none named, the first, adopted and
  // never written.
  const route = useRouteParams("data-media");
  const [defaultId, setDefaultId] = useState("");
  const selectedId = route.dataset || defaultId;
  const [newName, setNewName] = useState("");
  const [newDescription, setNewDescription] = useState("");
  const [uploadMode, setUploadMode] = useState<"replace" | "append">("replace");
  const [lastUpload, setLastUpload] = useState<Answer<UploadResult> | null>(null);
  const [actionError, setActionError] = useState("");
  const [busy, setBusy] = useState(false);
  const [declared, setDeclared] = useState<Answer<DatasetSchema> | null>(null);
  const [detail, setDetail] = useState<Answer<DataAsset> | null>(null);

  const assets = useAsyncState<DataAsset[]>(listDataAssets, [refreshKey]);

  // The open dataset's detail. Back, Forward and a chosen row change the id with no handler of
  // this screen's running, so every answer carries its id, and one that arrives after the id
  // moved on is dropped. A reload keeps the answer on screen until the next one lands.
  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return undefined;
    }
    let cancelled = false;
    getDataAsset(selectedId).then(
      (asset) => { if (!cancelled) setDetail({ id: selectedId, value: asset }); },
      (error: unknown) => {
        if (!cancelled) setDetail({ id: selectedId, error: error instanceof Error ? error.message : String(error), notFound: isNotFound(error) });
      });
    return () => {
      cancelled = true;
    };
  }, [selectedId, refreshKey]);

  useEffect(() => {
    if (!selectedId && assets.value && assets.value.length) setDefaultId(assets.value[0].id);
  }, [assets.value, selectedId]);

  // A failed create or upload is about the dataset that was open; another one clears it. This
  // writes nothing to the URL.
  useEffect(() => setActionError(""), [selectedId]);

  // Declared (name/type) schema is best-effort: /datasets/{id}/schema 404s until declared.
  useEffect(() => {
    if (!selectedId) {
      setDeclared(null);
      return;
    }
    let cancelled = false;
    getDatasetSchema(selectedId)
      .then((schema) => !cancelled && setDeclared({ id: selectedId, value: schema }))
      .catch(() => !cancelled && setDeclared({ id: selectedId }));
    return () => {
      cancelled = true;
    };
  }, [selectedId, refreshKey]);

  async function createDataset() {
    const name = newName.trim();
    if (!name) return;
    setActionError("");
    setBusy(true);
    // Where the user was when they asked: if they have chosen another dataset or left by the
    // time it exists, it is not opened over their choice.
    const askedAt = window.location.pathname + window.location.search;
    try {
      const id = slugify(name) || `dataset_${Date.now()}`;
      const created = await createDataAsset({ id, display_name: name, description: newDescription.trim() || undefined });
      // One synchronous block, so the new URL and these updates render together (React 19
      // renders the popstate's and the continuation's updates in one pass). The new dataset
      // is found through its own detail fetch, never through the reloading list.
      if (window.location.pathname + window.location.search === askedAt) openResource("dataset", created.id);
      setNewName("");
      setNewDescription("");
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
    const id = selectedId;
    setActionError("");
    setBusy(true);
    try {
      const result = await uploadDataAssetFile(id, file, uploadMode);
      setLastUpload({ id, value: result });
      reload();
    } catch (error) {
      setActionError((error as Error).message);
    } finally {
      setBusy(false);
      input.value = ""; // allow re-selecting the same file
    }
  }

  // Only what answers the open id is shown: the records, the receipt, the schema and the error.
  const answered = detail?.id === selectedId ? detail : null;
  const selectedAsset = answered?.value ?? null;
  const datasetMissing = route.dataset !== "" && Boolean(answered?.notFound);
  const detailError = answered && !answered.notFound ? answered.error ?? "" : "";
  const pending = Boolean(selectedId) && !answered;
  const receipt = lastUpload?.id === selectedId ? lastUpload.value ?? null : null;
  const declaredSchema = declared?.id === selectedId ? declared.value ?? null : null;
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
        <Metric label="Last format" value={receipt?.source_format || selectedAsset?.kind || "-"} />
      </div>
      <ErrorBanner message={actionError || assets.error || detailError} />
      {(assets.loading || pending) && <LoadingState label="Loading datasets..." />}
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
                onClick={() => openResource("dataset", asset.id)}
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
          action={selectedAsset ? <a className="legacy-button compact" href={dataAssetDownloadUrl(selectedAsset.id)}>Download raw file</a> : undefined}
        >
          {datasetMissing ? <UnknownResource noun="dataset" id={route.dataset} /> : selectedAsset ? (
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
                Uploads to <code>/data-assets/{selectedAsset.id}/upload</code> as multipart form data. CSV, JSON, JSONL, and Parquet are parsed into records.
              </p>
              {receipt ? (
                <KeyValueGrid data={{
                  source_format: receipt.source_format,
                  added: receipt.added,
                  record_count: receipt.record_count,
                  columns: receipt.columns.join(", "),
                  bytes: receipt.bytes,
                  file_ref: receipt.file_ref
                }} />
              ) : (
                <EmptyState inline>Choose a file to ingest records into the selected dataset.</EmptyState>
              )}
            </div>
          ) : pending ? (
            <LoadingState label="Loading dataset..." />
          ) : (
            <EmptyState title="Select a dataset" description="Pick a dataset on the left to upload a file into it." />
          )}
        </Panel>
      </div>
      {datasetMissing ? null : <div className="two-col">
        <Panel title={selectedAsset ? `Records — ${selectedAsset.display_name || selectedAsset.id}` : "Records"}>
          {selectedAsset ? (
            // Keyed by dataset, so a column arrangement made on one does not reorder the next.
            <DataGrid key={selectedAsset.id} rows={records} label="Dataset records" empty="No records yet. Upload a file to populate this dataset." />
          ) : (
            <EmptyState title="No dataset selected" />
          )}
        </Panel>
        <Panel title={`Schema ${schemaRows.length}`}>
          {schemaRows.length ? (
            <>
              <StatusBadge value={declaredSchema?.columns?.length ? "declared" : "inferred"} intent="neutral" />
              <DataTable rows={schemaRows} empty="No schema columns." />
            </>
          ) : (
            <EmptyState inline>Schema is inferred once a file is uploaded, or declared via the datasets schema endpoint.</EmptyState>
          )}
        </Panel>
      </div>}
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
                <EmptyState inline>Choose a file to store a media item in this set.</EmptyState>
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
          <EmptyState inline>No media items yet. Upload a file into the selected media set.</EmptyState>
        )}
      </Panel>
    </>
  );
}
