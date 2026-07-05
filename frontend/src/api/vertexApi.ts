import { api, postJson } from "../api";
import type { JsonObject, JsonValue, TableRow } from "../types";

// ---------------------------------------------------------------------------
// Enumerated request vocabularies (mirror app/vertex_ops.py)
// ---------------------------------------------------------------------------

export type VertexDirection = "out" | "in" | "both";
export type VertexLayout = "auto" | "grid" | "circular" | "radial" | "hierarchy" | "cluster";
export type VertexAggregation = "count" | "sum_weight";
export type VertexFilterOp = "eq" | "neq" | "gt" | "gte" | "lt" | "lte" | "contains" | "exists";

export const VERTEX_LAYOUTS: VertexLayout[] = ["auto", "grid", "circular", "radial", "hierarchy", "cluster"];
export const VERTEX_DIRECTIONS: VertexDirection[] = ["out", "in", "both"];
export const VERTEX_AGGREGATIONS: VertexAggregation[] = ["count", "sum_weight"];
export const VERTEX_FILTER_OPS: VertexFilterOp[] = ["eq", "neq", "gt", "gte", "lt", "lte", "contains", "exists"];

// ---------------------------------------------------------------------------
// Response shapes
// ---------------------------------------------------------------------------

export interface VertexNode extends TableRow {
  id: string;
  object_type_id?: string;
  properties?: JsonObject;
  faded?: boolean;
  is_seed?: boolean;
  x?: number;
  y?: number;
}

export interface VertexEdge extends TableRow {
  id?: string;
  link_type_id?: string | null;
  source_object_id?: string;
  target_object_id?: string;
  merged?: boolean;
  merged_count?: number;
  merged_weight?: number;
  label?: string;
}

export interface VertexGraph {
  id: string;
  display_name: string;
  description?: string | null;
  seed_object_ids: string[];
  nodes: VertexNode[];
  edges: VertexEdge[];
  layout_type: string;
  styles: JsonObject;
  owner?: string | null;
  created_at: number;
  updated_at: number;
}

export interface VertexExploreResponse {
  graph: VertexGraph;
  added_nodes: number;
  added_edges: number;
}

export interface VertexFilterResponse {
  graph: VertexGraph;
  matched: number;
  faded: number;
}

export interface VertexMergeResponse {
  graph: VertexGraph;
  before_edge_count: number;
  after_edge_count: number;
  merged_edge_count: number;
  merged_edges: VertexEdge[];
}

// Seeding helpers pull from the shared ontology endpoints.
export interface VertexObjectType extends TableRow {
  id: string;
  display_name?: string;
  description?: string | null;
  properties?: JsonObject;
}

export interface VertexObjectInstance extends TableRow {
  id: string;
  object_type_id?: string;
  properties?: JsonObject;
}

export interface VertexLinkType extends TableRow {
  id: string;
  display_name?: string;
  source_object_type_id?: string;
  target_object_type_id?: string;
  cardinality?: string;
}

// ---------------------------------------------------------------------------
// Request bodies
// ---------------------------------------------------------------------------

export interface CreateGraphBody {
  display_name: string;
  seed_object_ids: string[];
  layout_type: VertexLayout;
  description?: string;
}

export interface ExploreBody {
  link_type_id?: string;
  direction: VertexDirection;
  depth: number;
}

export interface FilterBody {
  property: string;
  op: VertexFilterOp;
  value: JsonValue;
}

export interface MergeBody {
  link_type_id?: string;
  aggregation: VertexAggregation;
}

// ---------------------------------------------------------------------------
// Seeding / catalog fetchers
// ---------------------------------------------------------------------------

export function listObjectTypes(): Promise<VertexObjectType[]> {
  return api<VertexObjectType[]>("/object-types");
}

export function listObjects(objectTypeId: string, limit = 50): Promise<VertexObjectInstance[]> {
  return api<VertexObjectInstance[]>(`/objects/${encodeURIComponent(objectTypeId)}?limit=${limit}`);
}

export function listLinkTypes(): Promise<VertexLinkType[]> {
  return api<VertexLinkType[]>("/link-types");
}

// ---------------------------------------------------------------------------
// Vertex graph operations
// ---------------------------------------------------------------------------

export function listVertexGraphs(): Promise<VertexGraph[]> {
  return api<VertexGraph[]>("/vertex/graphs");
}

export function getVertexGraph(graphId: string): Promise<VertexGraph> {
  return api<VertexGraph>(`/vertex/graphs/${encodeURIComponent(graphId)}`);
}

export function createVertexGraph(body: CreateGraphBody): Promise<VertexGraph> {
  return postJson<VertexGraph>("/vertex/graphs", body);
}

export function exploreVertexGraph(graphId: string, body: ExploreBody): Promise<VertexExploreResponse> {
  return postJson<VertexExploreResponse>(`/vertex/graphs/${encodeURIComponent(graphId)}/explore`, body);
}

export function layoutVertexGraph(graphId: string, layoutType: VertexLayout): Promise<VertexGraph> {
  return postJson<VertexGraph>(`/vertex/graphs/${encodeURIComponent(graphId)}/layout`, { layout_type: layoutType });
}

export function filterVertexGraph(graphId: string, body: FilterBody): Promise<VertexFilterResponse> {
  return postJson<VertexFilterResponse>(`/vertex/graphs/${encodeURIComponent(graphId)}/filter`, body);
}

export function mergeVertexLinks(graphId: string, body: MergeBody): Promise<VertexMergeResponse> {
  return postJson<VertexMergeResponse>(`/vertex/graphs/${encodeURIComponent(graphId)}/links/merge`, body);
}
