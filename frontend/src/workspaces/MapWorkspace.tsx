import { useEffect, useMemo, useRef, useState } from "react";
import { CircleMarker, GeoJSON, MapContainer, TileLayer, useMap, useMapEvents } from "react-leaflet";
import type { FeatureCollection as LeafletFeatureCollection, Feature as LeafletFeature, Geometry } from "geojson";
import L, { type GeoJSONOptions, type LatLngExpression, type Map as LeafletMap } from "leaflet";
import "leaflet/dist/leaflet.css";
import { Crosshair, Layers, LocateFixed, MapPin, Plus, Radar, RefreshCw, Search, ShieldAlert } from "lucide-react";
import { EmptyState, ErrorBanner, KeyValueGrid, LoadingState, Panel, StatusBadge } from "../components/data/DataDisplay";
import { Page } from "../components/workbench/Workbench";
import {
  createBuffer,
  createMapLayer,
  decodeMgrs,
  encodeMgrs,
  evaluateGeofence,
  listGisObjectTypes,
  listMapLayers,
  loadLayerFeatures,
  loadTypeFeatures,
  type FeatureCollection,
  type GeoFeature,
  type GeoGeometry,
  type GeofenceResult,
  type MapLayer,
  type MgrsCoordinate
} from "../api/gisApi";
import type { ObjectTypeSummary } from "../api/objectExplorerApi";
import { propertySpecs } from "../utils/semanticRender";

const DEFAULT_CENTER: LatLngExpression = [37.7915, -122.4012];

function riskColor(properties: Record<string, unknown>): string {
  const score = Number(properties.risk_score ?? properties.risk ?? 0);
  const text = String(properties.risk_band ?? properties.criticality ?? properties.status ?? "").toLowerCase();
  if (score >= 80 || text.includes("critical") || text.includes("high") || text.includes("degraded")) return "#d14935";
  if (score >= 50 || text.includes("medium") || text.includes("warn")) return "#d89300";
  if (score > 0 || text.includes("low")) return "#16876d";
  return "#2677a8";
}

function featurePoint(feature: GeoFeature | null): [number, number] | null {
  if (!feature?.geometry || feature.geometry.type !== "Point" || !Array.isArray(feature.geometry.coordinates)) return null;
  const values = feature.geometry.coordinates as number[];
  return values.length >= 2 ? [Number(values[0]), Number(values[1])] : null;
}

function featureLabel(feature: GeoFeature): string {
  return String(feature.properties.name || feature.properties.title || feature.properties.label || feature.id || feature.properties.id || "Operational feature");
}

function MapViewport({ collection, focus }: { collection: FeatureCollection | null; focus: [number, number] | null }) {
  const map = useMap();
  useEffect(() => {
    if (focus) map.flyTo([focus[1], focus[0]], Math.max(map.getZoom(), 15), { duration: 0.5 });
  }, [focus, map]);
  useEffect(() => {
    if (!collection?.features.length) return;
    const layer = L.geoJSON(collection as unknown as LeafletFeatureCollection);
    const bounds = layer.getBounds();
    if (bounds.isValid()) map.fitBounds(bounds.pad(0.18), { maxZoom: 16 });
  }, [collection, map]);
  return null;
}

function MapClick({ onPick }: { onPick: (point: [number, number]) => void }) {
  useMapEvents({ click: (event) => onPick([event.latlng.lng, event.latlng.lat]) });
  return null;
}

export function MapWorkspace() {
  const mapRef = useRef<LeafletMap | null>(null);
  const [types, setTypes] = useState<ObjectTypeSummary[]>([]);
  const [layers, setLayers] = useState<MapLayer[]>([]);
  const [activeLayerId, setActiveLayerId] = useState("");
  const [objectTypeId, setObjectTypeId] = useState("");
  const [geometryField, setGeometryField] = useState("geometry");
  const [collection, setCollection] = useState<FeatureCollection | null>(null);
  const [selected, setSelected] = useState<GeoFeature | null>(null);
  const [pickedPoint, setPickedPoint] = useState<[number, number] | null>(null);
  const [mgrsInput, setMgrsInput] = useState("");
  const [mgrs, setMgrs] = useState<MgrsCoordinate | null>(null);
  const [radius, setRadius] = useState(300);
  const [geofence, setGeofence] = useState<GeoGeometry | null>(null);
  const [geofenceResult, setGeofenceResult] = useState<GeofenceResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const loadLayer = async (layerId: string) => {
    setLoading(true);
    setError("");
    try {
      const layer = layers.find((item) => item.id === layerId);
      const features = await loadLayerFeatures(layerId);
      setActiveLayerId(layerId);
      setObjectTypeId(layer?.object_type_id || "");
      setGeometryField(layer?.geometry_field || "geometry");
      setCollection(features);
      setSelected(null);
      setGeofence(null);
      setGeofenceResult(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Map layer failed to load");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    Promise.all([listGisObjectTypes(), listMapLayers()]).then(async ([nextTypes, nextLayers]) => {
      setTypes(nextTypes);
      setLayers(nextLayers);
      const firstLayer = nextLayers.find((layer) => layer.visible) || nextLayers[0];
      if (firstLayer) {
        setObjectTypeId(firstLayer.object_type_id);
        setGeometryField(firstLayer.geometry_field);
        setActiveLayerId(firstLayer.id);
        setCollection(await loadLayerFeatures(firstLayer.id));
      } else if (nextTypes[0]) {
        setObjectTypeId(nextTypes[0].id);
        try { setCollection(await loadTypeFeatures(nextTypes[0].id)); } catch { setCollection(null); }
      }
    }).catch((cause) => setError(cause instanceof Error ? cause.message : "GIS workspace failed to load")).finally(() => setLoading(false));
  }, []);

  const renderType = async () => {
    if (!objectTypeId) return;
    setLoading(true);
    setError("");
    try {
      setCollection(await loadTypeFeatures(objectTypeId, geometryField));
      setActiveLayerId("");
      setSelected(null);
      setNotice(`Rendered ${types.find((type) => type.id === objectTypeId)?.display_name || objectTypeId}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Object type has no renderable geometry");
    } finally {
      setLoading(false);
    }
  };

  const addLayer = async () => {
    if (!objectTypeId) return;
    const displayName = window.prompt("Layer name", `${types.find((type) => type.id === objectTypeId)?.display_name || objectTypeId} Operations`);
    if (!displayName) return;
    try {
      const layer = await createMapLayer({
        id: `layer_${objectTypeId}_${Date.now()}`,
        project_id: types.find((type) => type.id === objectTypeId)?.project_id || "default",
        display_name: displayName,
        description: "Operational layer created from the React GIS workspace",
        object_type_id: objectTypeId,
        geometry_field: geometryField,
        filters: {},
        style: { color_by: "risk", palette: "operational" },
        visible: true,
        owner: "map-ui"
      });
      setLayers((items) => [layer, ...items]);
      setNotice(`Created layer ${layer.display_name}`);
      await loadLayer(layer.id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Layer could not be created");
    }
  };

  const encodeCurrentPoint = async () => {
    const point = featurePoint(selected) || pickedPoint || (mapRef.current ? [mapRef.current.getCenter().lng, mapRef.current.getCenter().lat] as [number, number] : null);
    if (!point) return;
    try {
      const value = await encodeMgrs(point[1], point[0]);
      setMgrs(value);
      setMgrsInput(value.mgrs);
      setPickedPoint([value.longitude, value.latitude]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "MGRS encoding failed");
    }
  };

  const decodeCoordinate = async () => {
    if (!mgrsInput.trim()) return;
    try {
      const value = await decodeMgrs(mgrsInput.trim());
      setMgrs(value);
      setPickedPoint([value.longitude, value.latitude]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "MGRS coordinate is invalid");
    }
  };

  const runGeofence = async () => {
    const point = featurePoint(selected) || pickedPoint;
    if (!point || !objectTypeId) {
      setError("Select a point feature or click the map before evaluating a geofence.");
      return;
    }
    try {
      const polygon = await createBuffer(point[0], point[1], radius);
      setGeofence(polygon);
      const result = await evaluateGeofence(objectTypeId, geometryField, polygon);
      setGeofenceResult(result);
      setNotice(`${result.summary.inside} objects inside the ${radius} m geofence`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Geofence evaluation failed");
    }
  };

  const displayCollection = useMemo<LeafletFeatureCollection>(() => ({
    type: "FeatureCollection",
    features: (collection?.features || []).filter((feature) => feature.geometry) as unknown as LeafletFeature<Geometry>[]
  }), [collection]);
  const geofenceCollection = useMemo<LeafletFeatureCollection>(() => ({ type: "FeatureCollection", features: geofence ? [{ type: "Feature", properties: {}, geometry: geofence as unknown as Geometry }] : [] }), [geofence]);
  const layer = layers.find((item) => item.id === activeLayerId);
  const focus = featurePoint(selected) || pickedPoint;
  // Feature properties are ontology object properties, so the inspector draws
  // them by their declared base type like every other object surface. This is
  // the panel where it matters most: without it a polygon arrives as GeoJSON
  // text on the one screen whose subject is geometry.
  const specs = useMemo(
    () => propertySpecs(types.find((type) => type.id === objectTypeId)?.properties as Record<string, unknown> | undefined),
    [types, objectTypeId]
  );
  const geoJsonOptions: GeoJSONOptions = {
    style: (feature) => ({ color: riskColor((feature?.properties || {}) as Record<string, unknown>), weight: 2, fillOpacity: 0.28 }),
    pointToLayer: (feature, latlng) => L.circleMarker(latlng, { radius: 8, color: riskColor((feature.properties || {}) as Record<string, unknown>), fillOpacity: 0.85, weight: 2 }),
    onEachFeature: (feature, leafletLayer) => {
      leafletLayer.on("click", () => setSelected(feature as unknown as GeoFeature));
      const properties = (feature.properties || {}) as Record<string, unknown>;
      leafletLayer.bindTooltip(String(properties.name || properties.title || feature.id || "Operational feature"));
    }
  };

  return (
    <Page title="Operational Map" subtitle="Explore ontology objects spatially with persistent layers, MGRS coordinates, risk styling, and governed geofences.">
      <div className="map-command-bar">
        <label><span>Object type</span><select aria-label="Map object type" value={objectTypeId} onChange={(event) => setObjectTypeId(event.target.value)}>{types.map((type) => <option key={type.id} value={type.id}>{type.display_name}</option>)}</select></label>
        <label><span>Geometry field</span><input aria-label="Geometry field" value={geometryField} onChange={(event) => setGeometryField(event.target.value)} /></label>
        <button className="primary" onClick={() => void renderType()}><RefreshCw size={15} />Render</button>
        <button onClick={() => void addLayer()}><Plus size={15} />Save layer</button>
        <button onClick={() => mapRef.current?.setView(DEFAULT_CENTER, 14)}><LocateFixed size={15} />Reset view</button>
      </div>
      <ErrorBanner message={error} />
      {notice ? <div className="inline-success" role="status">{notice}</div> : null}
      <div className="map-workbench">
        <aside className="map-layer-rail">
          <Panel title="Layers" action={<Layers size={15} />}>
            <div className="map-layer-list">{layers.map((item) => <button key={item.id} className={item.id === activeLayerId ? "selected" : ""} onClick={() => void loadLayer(item.id)}><span className="layer-swatch" style={{ background: riskColor(item.style) }} /><span><strong>{item.display_name}</strong><small>{item.object_type_id} · {item.geometry_field}</small></span><StatusBadge value={item.visible ? "visible" : "hidden"} /></button>)}</div>
            {!layers.length ? <div className="empty">Render an object type, then save it as a reusable operational layer.</div> : null}
            {collection?.features.length ? <><h3 className="map-subheading">Features</h3><div className="map-feature-list">{collection.features.slice(0, 12).map((feature, index) => <button key={String(feature.id || index)} className={selected === feature ? "selected" : ""} onClick={() => setSelected(feature)}><i style={{ background: riskColor(feature.properties) }} /><span>{featureLabel(feature)}</span><small>{String(feature.id || feature.properties.id || "object")}</small></button>)}</div></> : null}
          </Panel>
          <Panel title="MGRS" action={<Crosshair size={15} />}>
            <label className="stacked-field"><span>Coordinate</span><input aria-label="MGRS coordinate" value={mgrsInput} onChange={(event) => setMgrsInput(event.target.value.toUpperCase())} placeholder="10SEG..." /></label>
            <div className="button-row"><button onClick={() => void decodeCoordinate()}><Search size={14} />Focus</button><button onClick={() => void encodeCurrentPoint()}><MapPin size={14} />Encode point</button></div>
            {mgrs ? <dl className="map-coordinate-summary"><div><dt>MGRS</dt><dd>{mgrs.mgrs}</dd></div><div><dt>Lat / Lon</dt><dd>{mgrs.latitude.toFixed(5)}, {mgrs.longitude.toFixed(5)}</dd></div><div><dt>Grid</dt><dd>Zone {mgrs.zone}{mgrs.band}</dd></div></dl> : null}
          </Panel>
          <Panel title="Radius / Geofence" action={<Radar size={15} />}>
            <label className="stacked-field"><span>Radius: {radius} m</span><input aria-label="Geofence radius" type="range" min="50" max="5000" step="50" value={radius} onChange={(event) => setRadius(Number(event.target.value))} /></label>
            <button className="wide-button" onClick={() => void runGeofence()}><ShieldAlert size={15} />Evaluate geofence</button>
            {geofenceResult ? <div className="geofence-summary"><span><strong>{geofenceResult.summary.inside}</strong> inside</span><span><strong>{geofenceResult.summary.outside}</strong> outside</span></div> : null}
          </Panel>
        </aside>

        <main className="operational-map" aria-label="Operational GIS map">
          {loading ? <div className="map-loading"><LoadingState label="Loading spatial features..." /></div> : null}
          <MapContainer ref={mapRef} center={DEFAULT_CENTER} zoom={14} zoomControl={true} className="leaflet-operational-map">
            <TileLayer attribution="&copy; OpenStreetMap contributors" url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
            <MapClick onPick={setPickedPoint} />
            <MapViewport collection={collection} focus={focus} />
            {displayCollection.features.length ? <GeoJSON key={`${activeLayerId}-${collection?.features.length}-${selected?.id || ""}`} data={displayCollection} {...geoJsonOptions} /> : null}
            {geofence ? <GeoJSON key={`geofence-${radius}`} data={geofenceCollection} style={{ color: "#c46a13", fillColor: "#efb263", fillOpacity: 0.14, dashArray: "6 5", weight: 2 }} /> : null}
            {pickedPoint ? <CircleMarker center={[pickedPoint[1], pickedPoint[0]]} radius={7} pathOptions={{ color: "#172f3d", fillColor: "#fff", fillOpacity: 1, weight: 3 }} /> : null}
          </MapContainer>
          <div className="map-status-strip"><span><i className="map-dot critical" />critical</span><span><i className="map-dot warning" />warning</span><span><i className="map-dot normal" />normal</span><strong>{collection?.features.length || 0} features</strong></div>
        </main>

        <aside className="map-inspector">
          <Panel title="Selection" action={<MapPin size={15} />}>
            {!selected ? <EmptyState title="Select a feature" description="Click an object on the map to inspect ontology properties and spatial state." /> : <><header className="map-selection-heading"><div><strong>{String(selected.properties.name || selected.properties.title || selected.id || "Selected feature")}</strong><small>{String(selected.id || selected.properties.id || "ontology object")}</small></div><StatusBadge value={String(selected.properties.risk_band || selected.properties.criticality || selected.properties.status || "active")} /></header><KeyValueGrid data={selected.properties} specs={specs} /></>}
          </Panel>
          <Panel title="Layer Evidence">
            <dl className="map-coordinate-summary"><div><dt>Layer</dt><dd>{layer?.display_name || "Ad hoc object view"}</dd></div><div><dt>Object type</dt><dd>{objectTypeId || "none"}</dd></div><div><dt>Geometry</dt><dd>{geometryField}</dd></div><div><dt>Geofence</dt><dd>{geofenceResult ? `${geofenceResult.summary.inside} matches` : "not evaluated"}</dd></div></dl>
          </Panel>
        </aside>
      </div>
    </Page>
  );
}
