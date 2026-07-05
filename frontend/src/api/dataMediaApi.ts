import { api, postJson } from "../api";
import type { JsonObject, TableRow } from "../types";

// ---------------------------------------------------------------------------
// Data assets (datasets) — list / create / detail / declared schema / upload
// ---------------------------------------------------------------------------

export interface DataAsset {
  id: string;
  display_name: string;
  description?: string | null;
  kind: string;
  asset_schema: JsonObject;
  records: TableRow[];
  created_at?: number;
  updated_at?: number;
}

export interface DataAssetCreate {
  id: string;
  display_name: string;
  description?: string;
  kind?: string;
}

export interface DatasetSchema {
  dataset_id: string;
  columns: Array<{ name: string; type: string }>;
  created_at: number;
  updated_at: number;
}

/** Response of POST /data-assets/{id}/upload — real CSV/JSON/JSONL/Parquet ingest. */
export interface UploadResult {
  dataset_id: string;
  source_format: string;
  added: number;
  record_count: number;
  columns: string[];
  file_ref: string;
  bytes: number;
}

export function listDataAssets(): Promise<DataAsset[]> {
  return api<DataAsset[]>("/data-assets");
}

export function getDataAsset(id: string): Promise<DataAsset> {
  return api<DataAsset>(`/data-assets/${encodeURIComponent(id)}`);
}

export function createDataAsset(body: DataAssetCreate): Promise<DataAsset> {
  return postJson<DataAsset>("/data-assets", { kind: "dataset", ...body });
}

/** Declared (name/type) schema. 404s until a schema has been declared for the dataset. */
export function getDatasetSchema(id: string): Promise<DatasetSchema> {
  return api<DatasetSchema>(`/datasets/${encodeURIComponent(id)}/schema`);
}

/** Upload a real file into a dataset. Builds multipart FormData; api() omits the JSON
 * content-type for FormData bodies so the browser sets the multipart boundary. */
export function uploadDataAssetFile(id: string, file: File, mode?: "replace" | "append"): Promise<UploadResult> {
  const fd = new FormData();
  fd.append("file", file);
  if (mode) fd.append("mode", mode);
  return api<UploadResult>(`/data-assets/${encodeURIComponent(id)}/upload`, { method: "POST", body: fd });
}

export function dataAssetDownloadUrl(id: string): string {
  return `/data-assets/${encodeURIComponent(id)}/download`;
}

// ---------------------------------------------------------------------------
// Media sets / items — list / create / binary upload / content link
// ---------------------------------------------------------------------------

export interface MediaSet {
  id: string;
  display_name: string;
  media_type: string;
  description?: string | null;
  created_at: number;
}

export interface MediaSetCreate {
  id?: string;
  display_name: string;
  media_type: string;
  description?: string;
}

export interface MediaItem {
  id: string;
  media_set_id: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
  text_content?: string | null;
  metadata?: JsonObject;
  created_at: number;
}

/** Response of POST /media-sets/{id}/items/upload. */
export interface MediaUploadResult {
  id: string;
  media_set_id: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
  storage_uri: string;
  has_text: boolean;
}

export function listMediaSets(): Promise<MediaSet[]> {
  return api<MediaSet[]>("/media-sets");
}

export function createMediaSet(body: MediaSetCreate): Promise<MediaSet> {
  return postJson<MediaSet>("/media-sets", body);
}

export function listMediaItems(id: string): Promise<MediaItem[]> {
  return api<MediaItem[]>(`/media-sets/${encodeURIComponent(id)}/items`);
}

/** Upload a binary media artifact into a media set via multipart FormData. */
export function uploadMediaItem(id: string, file: File): Promise<MediaUploadResult> {
  const fd = new FormData();
  fd.append("file", file);
  return api<MediaUploadResult>(`/media-sets/${encodeURIComponent(id)}/items/upload`, { method: "POST", body: fd });
}

export function mediaItemContentUrl(itemId: string): string {
  return `/media-items/${encodeURIComponent(itemId)}/content`;
}
