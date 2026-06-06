const state = {
  view: location.pathname.endsWith("/aip") ? "aip" : "map",
  features: [],
  projected: [],
  selectedFeature: null,
  layer: null,
  geofence: null,
  mgrsPoint: null,
  radiusQuery: null,
  map: null,
  basemapLayer: null,
  featureLayer: null,
  overlayLayer: null,
  markerByFeatureId: new Map(),
  basemap: "osm",
  leafletAvailable: false,
  tileWarningShown: false
};

const el = (id) => document.getElementById(id);

const BASEMAPS = {
  osm: {
    url: "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    options: {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    }
  },
  light: {
    url: "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
    options: {
      maxZoom: 20,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'
    }
  },
  dark: {
    url: "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
    options: {
      maxZoom: 20,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'
    }
  },
  imagery: {
    url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    options: {
      maxZoom: 19,
      attribution: "Tiles &copy; Esri"
    }
  }
};

function showToast(message) {
  const toast = el("toast");
  toast.textContent = message;
  toast.classList.add("show");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => toast.classList.remove("show"), 2600);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch (_) {
      detail = await response.text();
    }
    throw new Error(detail || `Request failed: ${response.status}`);
  }
  return response.json();
}

function setView(view, push = true) {
  state.view = view;
  el("mapView").classList.toggle("hidden", view !== "map");
  el("aipView").classList.toggle("hidden", view !== "aip");
  el("mapNav").classList.toggle("active", view === "map");
  el("aipNav").classList.toggle("active", view === "aip");
  if (push) history.pushState({}, "", `/workspace/${view}`);
  if (view === "map") {
    initOperationalMap();
    renderMap(false);
  } else {
    refreshAipLists();
  }
}

function compactJson(value) {
  return JSON.stringify(value, null, 2);
}

function parseFilters(inputId) {
  const raw = el(inputId).value.trim();
  if (!raw) return {};
  return JSON.parse(raw);
}

async function refreshHealth() {
  try {
    const status = await api("/");
    el("systemStatus").textContent = status.capabilities.join(" | ");
  } catch (error) {
    el("systemStatus").textContent = `API unavailable: ${error.message}`;
  }
}

function initOperationalMap() {
  if (state.map) {
    window.setTimeout(() => {
      state.map.invalidateSize();
      updateViewportMetric();
    }, 0);
    return;
  }

  const stage = document.querySelector(".map-stage");
  if (!window.L) {
    state.leafletAvailable = false;
    stage?.classList.add("leaflet-unavailable");
    resizeCanvas();
    drawMap();
    return;
  }

  state.leafletAvailable = true;
  stage?.classList.remove("leaflet-unavailable");
  state.map = L.map("leafletMap", {
    zoomControl: false,
    preferCanvas: true
  }).setView([37.7924, -122.4012], 16);
  L.control.zoom({ position: "bottomright" }).addTo(state.map);
  L.control.scale({ position: "bottomleft", metric: true, imperial: false }).addTo(state.map);
  state.featureLayer = L.layerGroup().addTo(state.map);
  state.overlayLayer = L.layerGroup().addTo(state.map);
  applyBasemap(state.basemap);
  state.map.on("moveend zoomend", updateViewportMetric);
  window.setTimeout(() => {
    state.map.invalidateSize();
    updateViewportMetric();
  }, 0);
}

function applyBasemap(basemapId) {
  state.basemap = BASEMAPS[basemapId] ? basemapId : "osm";
  if (!state.map) return;
  if (state.basemapLayer) state.map.removeLayer(state.basemapLayer);
  const config = BASEMAPS[state.basemap];
  state.basemapLayer = L.tileLayer(config.url, config.options);
  state.basemapLayer.on("tileerror", () => {
    if (!state.tileWarningShown) {
      state.tileWarningShown = true;
      showToast("Basemap tiles failed to load; operational overlays are still available");
    }
  });
  state.basemapLayer.addTo(state.map);
}

function updateViewportMetric() {
  if (!state.map) return;
  const center = state.map.getCenter();
  el("mapViewport").textContent = `${center.lat.toFixed(5)}, ${center.lng.toFixed(5)} | z${state.map.getZoom()}`;
}

function renderMap(fit = false) {
  initOperationalMap();
  if (!state.leafletAvailable || !state.map) {
    resizeCanvas();
    drawMap();
    return;
  }

  state.featureLayer.clearLayers();
  state.overlayLayer.clearLayers();
  state.markerByFeatureId = new Map();
  const latLngs = [];

  if (state.geofence) {
    const ring = state.geofence.coordinates?.[0] || [];
    const polygonLatLngs = ring.map(([longitude, latitude]) => [latitude, longitude]);
    if (polygonLatLngs.length) {
      L.polygon(polygonLatLngs, {
        color: "#ad6b18",
        weight: 2,
        fillColor: "#ad6b18",
        fillOpacity: 0.14
      }).addTo(state.overlayLayer).bindTooltip("Geofence");
      latLngs.push(...polygonLatLngs);
    }
  }

  if (state.radiusQuery) {
    const center = [state.radiusQuery.center.latitude, state.radiusQuery.center.longitude];
    L.circle(center, {
      radius: state.radiusQuery.radius_meters,
      color: "#1d5f8f",
      weight: 2,
      fillColor: "#1d5f8f",
      fillOpacity: 0.08
    }).addTo(state.overlayLayer).bindTooltip(`${state.radiusQuery.radius_meters}m radius`);
    latLngs.push(center);
  }

  if (state.mgrsPoint) {
    const mgrsLatLng = [state.mgrsPoint.latitude, state.mgrsPoint.longitude];
    const icon = L.divIcon({
      className: "mgrs-crosshair",
      html: "",
      iconSize: [24, 24],
      iconAnchor: [12, 12]
    });
    L.marker(mgrsLatLng, { icon, interactive: false }).addTo(state.overlayLayer);
    L.circle(mgrsLatLng, {
      radius: 50,
      color: "#ad6b18",
      weight: 1,
      fillColor: "#ad6b18",
      fillOpacity: 0.08
    }).addTo(state.overlayLayer).bindTooltip(state.mgrsPoint.mgrs || "MGRS reference");
    latLngs.push(mgrsLatLng);
  }

  for (const feature of state.features) {
    const point = featurePoint(feature);
    if (!point) continue;
    const props = feature.properties || {};
    const selected = state.selectedFeature?.id === feature.id;
    const color = featureColor(feature);
    const marker = L.circleMarker([point.latitude, point.longitude], {
      radius: selected ? 11 : Number(state.layer?.style?.marker_size || 8),
      color,
      weight: selected ? 4 : 2,
      fillColor: selected ? "#ffffff" : color,
      fillOpacity: selected ? 1 : 0.9
    }).addTo(state.featureLayer);
    marker.bindTooltip(`${props.name || props.title || props.object_id || feature.id}`);
    marker.on("click", () => selectFeature(feature));
    state.markerByFeatureId.set(feature.id, marker);
    latLngs.push([point.latitude, point.longitude]);
  }

  if (fit) fitMapToLatLngs(latLngs);
  updateViewportMetric();
}

function featureColor(feature) {
  const props = feature.properties || {};
  return state.layer?.style?.marker_color || (props.criticality === "high" ? "#b43b3b" : "#1d5f8f");
}

function fitMapToLatLngs(latLngs) {
  if (!state.map) return;
  if (!latLngs.length) {
    state.map.setView([37.7924, -122.4012], 16);
    return;
  }
  state.map.fitBounds(L.latLngBounds(latLngs).pad(0.25), {
    maxZoom: 17,
    animate: false
  });
}

function fitOperationalMap() {
  renderMap(true);
}

async function bootstrapDomain() {
  el("bootstrapBtn").disabled = true;
  try {
    await api("/domains/maintenance/bootstrap", {
      method: "POST",
      body: JSON.stringify({ actor: "workspace", run_pipelines: true })
    });
    await ensureCriticalLayer();
    await refreshLayers();
    await loadLayerFeatures("critical_asset_layer");
    await refreshAipLists();
    showToast("Maintenance domain bootstrapped");
  } catch (error) {
    showToast(error.message);
  } finally {
    el("bootstrapBtn").disabled = false;
  }
}

async function validateOntology() {
  try {
    const validation = await api("/ontology/validate");
    const label = `${validation.status}: ${validation.summary.errors} errors, ${validation.summary.warnings} warnings`;
    showToast(label);
    el("spatialResult").textContent = compactJson(validation.summary);
  } catch (error) {
    showToast(error.message);
  }
}

async function ensureCriticalLayer() {
  try {
    await api("/object-sets/saved", {
      method: "POST",
      body: JSON.stringify({
        id: "critical_assets",
        display_name: "Critical Assets",
        description: "High criticality asset object set.",
        object_type_id: "asset",
        filters: { criticality: "high" },
        owner: "workspace"
      })
    });
  } catch (_) {
    // Existing resources are acceptable in this local workspace.
  }
  try {
    await api("/gis/map-layers", {
      method: "POST",
      body: JSON.stringify({
        id: "critical_asset_layer",
        display_name: "Critical Asset Layer",
        description: "Assets filtered by criticality.",
        object_type_id: "asset",
        saved_object_set_id: "critical_assets",
        geometry_field: "geometry",
        filters: {},
        style: { marker_color: "#b43b3b", marker_size: 10 },
        visible: true,
        owner: "workspace"
      })
    });
  } catch (_) {
    // Existing resources are acceptable in this local workspace.
  }
}

async function refreshLayers() {
  const select = el("layerSelect");
  select.innerHTML = "";
  try {
    const layers = await api("/gis/map-layers");
    for (const layer of layers) {
      const option = document.createElement("option");
      option.value = layer.id;
      option.textContent = `${layer.display_name} (${layer.object_type_id})`;
      select.appendChild(option);
    }
  } catch (error) {
    showToast(error.message);
  }
}

async function loadAssetFeatures() {
  try {
    const collection = await api("/gis/feature-collection", {
      method: "POST",
      body: JSON.stringify({ object_type_id: "asset", geometry_field: "geometry", limit: 500 })
    });
    state.layer = { display_name: "Asset Feature Collection", style: { marker_color: "#1d5f8f", marker_size: 8 } };
    setFeatures(collection.features || []);
    showToast("Asset features loaded");
  } catch (error) {
    showToast(error.message);
  }
}

async function loadLayerFeatures(layerId = el("layerSelect").value) {
  if (!layerId) {
    await loadAssetFeatures();
    return;
  }
  try {
    const rendered = await api(`/gis/map-layers/${encodeURIComponent(layerId)}/features`);
    state.layer = rendered.layer || null;
    setFeatures(rendered.features || []);
    showToast("Map layer rendered");
  } catch (error) {
    showToast(error.message);
  }
}

function setFeatures(features) {
  state.features = features;
  state.selectedFeature = null;
  el("featureCount").textContent = `${features.length} features`;
  el("mapTitle").textContent = state.layer?.display_name || "Operational Map";
  el("mapSubtitle").textContent = state.layer?.object_type_id || "Feature collection";
  renderFeatureTable(features);
  renderProfile(null);
  renderMap(true);
}

function featurePoint(feature) {
  const geometry = feature.geometry;
  if (!geometry || geometry.type !== "Point") return null;
  const [longitude, latitude] = geometry.coordinates;
  return { longitude, latitude };
}

function featureBounds(features) {
  const points = features.map(featurePoint).filter(Boolean);
  if (state.mgrsPoint) points.push(state.mgrsPoint);
  if (!points.length) {
    return { west: -122.42, south: 37.78, east: -122.39, north: 37.8 };
  }
  const longitudes = points.map((point) => point.longitude);
  const latitudes = points.map((point) => point.latitude);
  let west = Math.min(...longitudes);
  let east = Math.max(...longitudes);
  let south = Math.min(...latitudes);
  let north = Math.max(...latitudes);
  const lonPad = Math.max((east - west) * 0.25, 0.002);
  const latPad = Math.max((north - south) * 0.25, 0.002);
  return { west: west - lonPad, south: south - latPad, east: east + lonPad, north: north + latPad };
}

function project(point, bounds, width, height) {
  const x = ((point.longitude - bounds.west) / (bounds.east - bounds.west || 1)) * width;
  const y = height - ((point.latitude - bounds.south) / (bounds.north - bounds.south || 1)) * height;
  return { x, y };
}

function resizeCanvas() {
  const canvas = el("mapCanvas");
  const rect = canvas.getBoundingClientRect();
  const scale = window.devicePixelRatio || 1;
  const width = Math.max(1, Math.floor(rect.width * scale));
  const height = Math.max(1, Math.floor(rect.height * scale));
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }
}

function drawMap() {
  const canvas = el("mapCanvas");
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  ctx.clearRect(0, 0, width, height);

  const bg = ctx.createLinearGradient(0, 0, width, height);
  bg.addColorStop(0, "#e7efed");
  bg.addColorStop(1, "#d6e1df");
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, width, height);

  ctx.strokeStyle = "rgba(70, 96, 101, 0.18)";
  ctx.lineWidth = 1;
  for (let x = 0; x < width; x += Math.max(48, width / 12)) {
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, height);
    ctx.stroke();
  }
  for (let y = 0; y < height; y += Math.max(48, height / 10)) {
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(width, y);
    ctx.stroke();
  }

  const bounds = featureBounds(state.features);
  state.projected = [];

  if (state.geofence) {
    drawPolygon(ctx, state.geofence, bounds, width, height);
  }

  for (const feature of state.features) {
    const point = featurePoint(feature);
    if (!point) continue;
    const pos = project(point, bounds, width, height);
    const selected = state.selectedFeature?.id === feature.id;
    const color = featureColor(feature);
    const size = Number(state.layer?.style?.marker_size || 8) * (window.devicePixelRatio || 1);
    ctx.beginPath();
    ctx.arc(pos.x, pos.y, selected ? size + 4 : size, 0, Math.PI * 2);
    ctx.fillStyle = selected ? "#ffffff" : color;
    ctx.fill();
    ctx.lineWidth = selected ? 4 : 2;
    ctx.strokeStyle = color;
    ctx.stroke();
    state.projected.push({ feature, x: pos.x, y: pos.y, radius: size + 8 });
  }

  if (state.mgrsPoint) {
    const pos = project(state.mgrsPoint, bounds, width, height);
    ctx.strokeStyle = "#ad6b18";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(pos.x - 12, pos.y);
    ctx.lineTo(pos.x + 12, pos.y);
    ctx.moveTo(pos.x, pos.y - 12);
    ctx.lineTo(pos.x, pos.y + 12);
    ctx.stroke();
  }
}

function drawPolygon(ctx, polygon, bounds, width, height) {
  const ring = polygon.coordinates?.[0] || [];
  if (!ring.length) return;
  ctx.beginPath();
  ring.forEach(([longitude, latitude], index) => {
    const pos = project({ longitude, latitude }, bounds, width, height);
    if (index === 0) ctx.moveTo(pos.x, pos.y);
    else ctx.lineTo(pos.x, pos.y);
  });
  ctx.closePath();
  ctx.fillStyle = "rgba(173, 107, 24, 0.14)";
  ctx.strokeStyle = "rgba(173, 107, 24, 0.9)";
  ctx.lineWidth = 2;
  ctx.fill();
  ctx.stroke();
}

async function handleCanvasClick(event) {
  const canvas = el("mapCanvas");
  const rect = canvas.getBoundingClientRect();
  const scale = window.devicePixelRatio || 1;
  const x = (event.clientX - rect.left) * scale;
  const y = (event.clientY - rect.top) * scale;
  const hit = state.projected.find((item) => Math.hypot(item.x - x, item.y - y) <= item.radius);
  if (!hit) return;
  await selectFeature(hit.feature);
}

async function selectFeature(feature) {
  state.selectedFeature = feature;
  renderFeatureTable(state.features);
  renderMap(false);
  const objectId = feature.properties?.object_id;
  const objectTypeId = feature.properties?.object_type_id;
  el("selectedCoord").textContent = `${objectId || "object"} selected`;
  if (objectId && objectTypeId) {
    try {
      const profile = await api(`/objects/${encodeURIComponent(objectTypeId)}/${encodeURIComponent(objectId)}/profile`);
      renderProfile(profile);
    } catch (error) {
      showToast(error.message);
    }
  }
}

function handleFeatureTableClick(event) {
  const row = event.target.closest("tr[data-feature-id]");
  if (!row) return;
  const feature = state.features.find((item) => item.id === row.dataset.featureId);
  if (feature) selectFeature(feature);
}

function renderFeatureTable(features) {
  if (!features.length) {
    el("featureTable").innerHTML = '<div class="empty-state">No features loaded</div>';
    return;
  }
  const rows = features.slice(0, 8).map((feature) => {
    const props = feature.properties || {};
    const selected = state.selectedFeature?.id === feature.id ? " selected" : "";
    return `<tr class="${selected}" data-feature-id="${escapeHtml(feature.id)}"><td>${escapeHtml(props.object_id || feature.id)}</td><td>${escapeHtml(props.name || props.title || "")}</td><td>${escapeHtml(props.criticality || props.status || "")}</td></tr>`;
  }).join("");
  el("featureTable").innerHTML = `<table><thead><tr><th>ID</th><th>Name</th><th>State</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function renderProfile(profile) {
  if (!profile) {
    el("objectProfile").className = "object-profile empty-state";
    el("objectProfile").textContent = "No object selected";
    return;
  }
  const obj = profile.object || {};
  const props = obj.properties || {};
  const spatial = obj.spatial || {};
  const entries = [
    ["ID", obj.id],
    ["Type", obj.object_type_id],
    ["Name", props.name || props.title || ""],
    ["Status", props.status || ""],
    ["Criticality", props.criticality || ""],
    ["MGRS", props.mgrs || spatial.mgrs || ""],
    ["Links", `${profile.metrics.inbound_link_count} in / ${profile.metrics.outbound_link_count} out`]
  ];
  el("objectProfile").className = "object-profile";
  el("objectProfile").innerHTML = entries.map(([key, value]) => `<div class="kv"><span>${escapeHtml(key)}</span><strong>${escapeHtml(value ?? "")}</strong></div>`).join("");
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;"
  }[char]));
}

async function decodeMgrs() {
  try {
    const decoded = await api("/gis/mgrs/decode", {
      method: "POST",
      body: JSON.stringify({ mgrs: el("mgrsInput").value, center: true })
    });
    state.mgrsPoint = { longitude: decoded.longitude, latitude: decoded.latitude, mgrs: decoded.mgrs };
    el("selectedCoord").textContent = `${decoded.mgrs} decoded`;
    el("spatialResult").textContent = compactJson(decoded);
    renderMap(true);
  } catch (error) {
    showToast(error.message);
  }
}

async function focusMgrsOverlay() {
  await decodeMgrs();
  if (state.map && state.mgrsPoint) {
    state.map.setView([state.mgrsPoint.latitude, state.mgrsPoint.longitude], Math.max(state.map.getZoom(), 17));
  }
}

async function runRadiusQuery() {
  const center = { longitude: -122.4012, latitude: 37.7924 };
  try {
    const result = await api("/gis/spatial-query", {
      method: "POST",
      body: JSON.stringify({
        object_type_id: "asset",
        near: center,
        radius_meters: 300,
        include_lineage: false
      })
    });
    state.radiusQuery = { center, radius_meters: 300, object_ids: result.objects.map((item) => item.id) };
    el("spatialResult").textContent = compactJson(result.objects.map((item) => ({
      id: item.id,
      meters: item.spatial.distance_meters,
      mgrs: item.spatial.mgrs
    })));
    renderMap(true);
    showToast(`${result.count} assets in radius`);
  } catch (error) {
    showToast(error.message);
  }
}

async function runGeofence() {
  state.geofence = {
    type: "Polygon",
    coordinates: [[
      [-122.4030, 37.7910],
      [-122.3990, 37.7910],
      [-122.3990, 37.7940],
      [-122.4030, 37.7940],
      [-122.4030, 37.7910]
    ]]
  };
  try {
    const result = await api("/gis/geofence/evaluate", {
      method: "POST",
      body: JSON.stringify({ object_type_id: "asset", geofence: state.geofence })
    });
    el("spatialResult").textContent = compactJson(result.summary);
    renderMap(true);
  } catch (error) {
    showToast(error.message);
  }
}

async function loadContextObjects() {
  try {
    const objectTypeId = el("objectTypeSelect").value;
    const filters = parseFilters("contextFilters");
    const result = await api("/object-sets/search", {
      method: "POST",
      body: JSON.stringify({ object_type_id: objectTypeId, filters, limit: 20, include_lineage: false })
    });
    renderObjectList(el("contextObjects"), result.objects);
  } catch (error) {
    showToast(error.message);
  }
}

function renderObjectList(container, objects) {
  if (!objects?.length) {
    container.innerHTML = '<div class="empty-state">No objects</div>';
    return;
  }
  container.innerHTML = objects.map((obj) => {
    const props = obj.properties || {};
    return `<div class="list-item"><strong>${escapeHtml(obj.id)}</strong><span>${escapeHtml(props.name || props.title || obj.object_type_id)}</span><span>${escapeHtml(props.status || props.criticality || "")}</span></div>`;
  }).join("");
}

async function askAssist() {
  try {
    const result = await api("/aip/assist/query", {
      method: "POST",
      body: JSON.stringify({ prompt: el("assistPrompt").value, application_context: "workspace", include_mcp_context: true })
    });
    el("assistAnswer").innerHTML = `<div>${escapeHtml(result.answer)}</div><div class="pill green">${escapeHtml(result.referenced_tools.join(", "))}</div>`;
  } catch (error) {
    showToast(error.message);
  }
}

async function refreshAipLists() {
  await Promise.allSettled([loadAgents(), loadApprovals(), loadEvals(), loadContextObjects()]);
}

async function loadAgents() {
  const select = el("agentSelect");
  select.innerHTML = "";
  try {
    const agents = await api("/agents");
    for (const agent of agents) {
      const option = document.createElement("option");
      option.value = agent.id;
      option.textContent = agent.display_name || agent.id;
      select.appendChild(option);
    }
  } catch (_) {
    // Agents are unavailable until the domain has been bootstrapped.
  }
}

async function runAgent() {
  const agentId = el("agentSelect").value;
  if (!agentId) {
    showToast("No agent selected");
    return;
  }
  try {
    const result = await api(`/agents/${encodeURIComponent(agentId)}/sessions`, {
      method: "POST",
      body: JSON.stringify({ user_prompt: el("agentPrompt").value, max_context_objects: 6 })
    });
    el("agentResult").textContent = compactJson({
      status: result.status,
      proposed_actions: result.proposed_actions,
      plan: result.plan
    });
  } catch (error) {
    showToast(error.message);
  }
}

async function generatePipeline() {
  try {
    const result = await api("/aip/pipeline-builder/generate", {
      method: "POST",
      body: JSON.stringify({
        prompt: el("pipelinePrompt").value,
        sample_fields: ["id", "status", "title", "description", "longitude", "latitude"]
      })
    });
    el("pipelineResult").textContent = compactJson(result);
  } catch (error) {
    showToast(error.message);
  }
}

async function loadApprovals() {
  try {
    const approvals = await api("/approvals");
    const container = el("approvalList");
    if (!approvals.length) {
      container.innerHTML = '<div class="empty-state">No approvals</div>';
      return;
    }
    container.innerHTML = approvals.slice(0, 8).map((approval) => `<div class="list-item"><strong>${escapeHtml(approval.action_type_id)}</strong><span>${escapeHtml(approval.status)}</span><span>${escapeHtml(approval.id)}</span></div>`).join("");
  } catch (error) {
    showToast(error.message);
  }
}

async function loadEvals() {
  const select = el("evalSelect");
  select.innerHTML = "";
  try {
    const evals = await api("/eval-suites");
    for (const suite of evals) {
      const option = document.createElement("option");
      option.value = suite.id;
      option.textContent = suite.display_name || suite.id;
      select.appendChild(option);
    }
  } catch (_) {
    // Evals are unavailable until a domain has been bootstrapped.
  }
}

async function runEval() {
  const suiteId = el("evalSelect").value;
  if (!suiteId) {
    showToast("No eval selected");
    return;
  }
  try {
    const result = await api(`/eval-suites/${encodeURIComponent(suiteId)}/run`, { method: "POST" });
    el("evalResult").textContent = compactJson({
      status: result.status,
      score: result.score,
      results: result.results
    });
  } catch (error) {
    showToast(error.message);
  }
}

function bindEvents() {
  el("mapNav").addEventListener("click", () => setView("map"));
  el("aipNav").addEventListener("click", () => setView("aip"));
  el("bootstrapBtn").addEventListener("click", bootstrapDomain);
  el("validateBtn").addEventListener("click", validateOntology);
  el("refreshLayersBtn").addEventListener("click", refreshLayers);
  el("assetLayerBtn").addEventListener("click", loadAssetFeatures);
  el("criticalLayerBtn").addEventListener("click", async () => {
    await ensureCriticalLayer();
    await refreshLayers();
    await loadLayerFeatures("critical_asset_layer");
  });
  el("basemapSelect").addEventListener("change", (event) => applyBasemap(event.target.value));
  el("fitMapBtn").addEventListener("click", fitOperationalMap);
  el("mgrsOverlayBtn").addEventListener("click", focusMgrsOverlay);
  el("renderLayerBtn").addEventListener("click", () => loadLayerFeatures());
  el("decodeMgrsBtn").addEventListener("click", decodeMgrs);
  el("radiusBtn").addEventListener("click", runRadiusQuery);
  el("geofenceBtn").addEventListener("click", runGeofence);
  el("mapCanvas").addEventListener("click", handleCanvasClick);
  el("featureTable").addEventListener("click", handleFeatureTableClick);
  el("loadContextBtn").addEventListener("click", loadContextObjects);
  el("askAssistBtn").addEventListener("click", askAssist);
  el("runAgentBtn").addEventListener("click", runAgent);
  el("generatePipelineBtn").addEventListener("click", generatePipeline);
  el("loadApprovalsBtn").addEventListener("click", loadApprovals);
  el("runEvalBtn").addEventListener("click", runEval);
  window.addEventListener("resize", () => {
    if (state.map) {
      state.map.invalidateSize();
      updateViewportMetric();
    } else {
      resizeCanvas();
      drawMap();
    }
  });
  window.addEventListener("popstate", () => setView(location.pathname.endsWith("/aip") ? "aip" : "map", false));
}

async function init() {
  bindEvents();
  setView(state.view, false);
  await refreshHealth();
  await refreshLayers();
  await loadAssetFeatures().catch(() => {});
  await refreshAipLists();
}

init();
