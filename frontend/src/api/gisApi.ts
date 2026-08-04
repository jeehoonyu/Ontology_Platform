import { api, postJson } from "../api";
import type { JsonObject } from "../types";
import type { ObjectTypeSummary } from "./objectExplorerApi";

export type GeoGeometry = { type: string; coordinates: unknown };
export type GeoFeature = {
  type: "Feature";
  id?: string | number;
  geometry: GeoGeometry | null;
  properties: JsonObject;
};
export type FeatureCollection = {
  type: "FeatureCollection";
  features: GeoFeature[];
  metadata: JsonObject;
  layer?: JsonObject;
};
export type MapLayer = {
  id: string;
  project_id: string;
  display_name: string;
  description?: string | null;
  object_type_id: string;
  saved_object_set_id?: string | null;
  geometry_field: string;
  filters: JsonObject;
  style: JsonObject;
  visible: boolean;
  owner: string;
  created_at: number;
  updated_at: number;
};
export type MgrsCoordinate = {
  mgrs: string;
  zone: number;
  band: string;
  latitude: number;
  longitude: number;
  precision: number;
  bbox?: number[] | null;
  utm: JsonObject;
};
export type GeofenceResult = {
  object_type_id: string;
  geometry_field: string;
  geofence: GeoGeometry;
  summary: { inside: number; outside: number; total?: number };
  inside: Record<string, unknown>[];
  outside: Record<string, unknown>[];
};

export const listGisObjectTypes = () => api<ObjectTypeSummary[]>("/object-types");
export const listMapLayers = () => api<MapLayer[]>("/gis/map-layers");
export const loadLayerFeatures = (layerId: string) => api<FeatureCollection>(`/gis/map-layers/${encodeURIComponent(layerId)}/features?limit=2000`);
export const loadTypeFeatures = (objectTypeId: string, geometryField = "geometry") => postJson<FeatureCollection>("/gis/feature-collection", {
  object_type_id: objectTypeId,
  geometry_field: geometryField,
  filters: {},
  limit: 2000,
  include_properties: true
});
export const createMapLayer = (body: Omit<MapLayer, "created_at" | "updated_at">) => postJson<MapLayer>("/gis/map-layers", body);
export const encodeMgrs = (latitude: number, longitude: number, precision = 5) => postJson<MgrsCoordinate>("/gis/mgrs/encode", { latitude, longitude, precision });
export const decodeMgrs = (mgrs: string) => postJson<MgrsCoordinate>("/gis/mgrs/decode", { mgrs, center: true });
export const createBuffer = (longitude: number, latitude: number, radiusM: number) => postJson<GeoGeometry>("/gis/ops/buffer", {
  point: [longitude, latitude], radius_m: radiusM, segments: 48
});
export const evaluateGeofence = (objectTypeId: string, geometryField: string, geofence: GeoGeometry) => postJson<GeofenceResult>("/gis/geofence/evaluate", {
  object_type_id: objectTypeId,
  geometry_field: geometryField,
  geofence,
  filters: {},
  limit: 2000
});
