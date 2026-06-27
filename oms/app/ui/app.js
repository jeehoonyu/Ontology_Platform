const WORKSPACE_VIEWS = ["home", "files", "ontology", "applications", "map", "aip", "workshop", "object-explorer", "pipeline"];

function routeViewFromPath(pathname) {
  const last = pathname.split("/").filter(Boolean).pop();
  if (WORKSPACE_VIEWS.includes(last)) return last;
  return "home";
}

const state = {
  view: routeViewFromPath(location.pathname),
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
  tileWarningShown: false,
  catalogs: {
    objectTypes: [],
    actionTypes: [],
    agents: [],
    evalSuites: [],
    logicFunctions: [],
    ontologyFunctions: []
  },
  logicInputs: [
    { name: "prompt", type: "string" },
    { name: "work_order_id", type: "string" },
  ],
  logicBlocks: [
    { type: "llm", mode: "summarize", prompt: "$prompt", output: "recommendation", object_type_id: "asset", action_type_id: "", function_id: "" },
    { type: "object_query", object_type_id: "asset", filters: '{"criticality":"high"}', limit: 10, output: "critical_assets" },
    { type: "propose_action", action_type_id: "escalate_work_order", parameters: '{"work_order_id":"$work_order_id","reason":"$recommendation"}', output: "proposed_action" },
    { type: "set_output", key: "result", value: "recommendation" }
  ],
  activeToolTab: "assist",
  activeRunTab: "run",
  lastLogicId: null,
  activeAppCategory: "all",
  selectedApplication: null,
  lastSearchQuery: "",
  datasets: [],
  workshop: {
    modules: [],
    selectedId: "",
    activePanel: "layout",
    preview: false,
    selectedWidgetIndex: 0,
    draft: null,
    render: null,
    versions: []
  },
  objectExplorer: {
    explorations: [],
    query: null,
    selectedObjectId: "",
    selectedIds: [],
    activeActionId: ""
  },
  pipeline: {
    graphs: [],
    selectedId: "",
    activeNodeId: "",
    activePanel: "build",
    draft: null,
    preview: null,
    validation: null,
    delivery: null
  }
};

const el = (id) => document.getElementById(id);

const LOGIC_INPUT_TYPES = [
  "string",
  "boolean",
  "integer",
  "long",
  "float",
  "double",
  "date",
  "timestamp",
  "object",
  "object_list",
  "object_set",
  "array",
  "struct",
  "media_reference"
];

const LOGIC_BLOCK_TYPES = [
  { type: "llm", label: "Use LLM" },
  { type: "object_query", label: "Query Objects" },
  { type: "object_aggregate", label: "Aggregate Objects" },
  { type: "propose_action", label: "Propose Action" },
  { type: "apply_action", label: "Apply Action" },
  { type: "pipeline_suggest", label: "Pipeline Suggest" },
  { type: "document_extract", label: "Document Extract" },
  { type: "assist", label: "Assist Query" },
  { type: "set_output", label: "Create Variable" },
  { type: "conditional", label: "Conditional" },
  { type: "for_each", label: "For Each" }
];

const LOGIC_COMPARE_OPS = ["eq", "ne", "gt", "gte", "lt", "lte", "contains", "not_null", "truthy"];

const PLATFORM_APPS = [
  { id: "files", name: "Projects & files", category: "data", icon: "F", color: "slate", view: "files", description: "Browse local projects, files, logic definitions, agents, and ontology resources." },
  { id: "object-explorer", name: "Object Explorer", category: "ontology", icon: "O", color: "teal", view: "object-explorer", description: "Explore object types, chart filters, inspect objects, and save explorations." },
  { id: "ontology", name: "Ontology Manager", category: "ontology", icon: "OM", color: "teal", view: "ontology", description: "Search object types, inspect ontology usage, and discover object sets." },
  { id: "aip", name: "AIP Logic", category: "operations", icon: "AI", color: "blue", view: "aip", description: "Build, test, debug, and run LLM-backed ontology logic functions." },
  { id: "map", name: "Map", category: "operations", icon: "M", color: "teal", view: "map", description: "Analyze geospatial and MGRS-enabled operational data." },
  { id: "workshop", name: "Workshop", category: "operations", icon: "W", color: "slate", view: "workshop", description: "Compose operational dashboards from objects, filters, widgets, and actions." },
  { id: "pipeline", name: "Pipeline Builder", category: "data", icon: "P", color: "teal", view: "pipeline", description: "Design DAG pipelines, preview transforms, deliver datasets, and inspect lineage." },
  { id: "notepad", name: "Notepad", category: "operations", icon: "N", color: "blue", view: "home", description: "Create object-aware notes, reports, and narrative artifacts." },
  { id: "contour", name: "Contour", category: "data", icon: "C", color: "slate", view: "files", description: "Analyze large datasets with filters, joins, and visual summaries." },
  { id: "fusion", name: "Fusion", category: "data", icon: "X", color: "teal", view: "files", description: "Interact with live data in a spreadsheet-like interface." },
  { id: "quiver", name: "Quiver", category: "operations", icon: "Q", color: "blue", view: "home", description: "Build interactive object and time-series dashboards." },
  { id: "vertex", name: "Vertex", category: "ontology", icon: "V", color: "teal", view: "ontology", description: "Visualize relationships between objects and systems." },
  { id: "code", name: "Code Repositories", category: "developer", icon: "CR", color: "slate", view: "files", description: "Manage code-backed functions and platform integrations." }
];

const WORKSHOP_WIDGET_TYPES = [
  { type: "object_table", title: "Object Table" },
  { type: "metric", title: "Metric" },
  { type: "chart", title: "Chart" },
  { type: "map", title: "Map" },
  { type: "object_view", title: "Object View" },
  { type: "button_action", title: "Button / Action" },
  { type: "text", title: "Text" },
  { type: "filter_list", title: "Filter List" },
  { type: "aip_assist", title: "AIP Assist" }
];

const PIPELINE_NODE_TYPES = [
  { type: "input_dataset", label: "Input Dataset" },
  { type: "filter", label: "Filter" },
  { type: "project", label: "Project / Select" },
  { type: "rename", label: "Rename" },
  { type: "join", label: "Join" },
  { type: "union", label: "Union" },
  { type: "aggregate", label: "Aggregate" },
  { type: "sort", label: "Sort" },
  { type: "limit", label: "Limit" },
  { type: "unique_id", label: "Unique ID" },
  { type: "llm_assist", label: "LLM Assist" },
  { type: "ontology_output", label: "Ontology Output" },
  { type: "dataset_output", label: "Dataset Output" }
];

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
  if (!WORKSPACE_VIEWS.includes(view)) view = "home";
  state.view = view;
  document.querySelectorAll("main > section[id$='View']").forEach((section) => {
    section.classList.toggle("hidden", section.id !== `${view}View`);
  });
  document.querySelectorAll(".side-nav-item").forEach((button) => {
    button.classList.toggle("active", button.id === `${view}Nav`);
  });
  if (push) history.pushState({}, "", `/workspace/${view}`);
  if (view === "map") {
    initOperationalMap();
    renderMap(false);
  } else if (view === "aip") {
    refreshAipLists();
  } else if (view === "workshop") {
    refreshWorkshop();
  } else if (view === "object-explorer") {
    refreshObjectExplorer();
  } else if (view === "pipeline") {
    refreshPipelineBuilder();
  } else {
    renderPlatformView(view);
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

function parseJsonValue(raw, fallback, label) {
  const text = String(raw ?? "").trim();
  if (!text) return fallback;
  try {
    return JSON.parse(text);
  } catch (error) {
    throw new Error(`${label} is not valid JSON`);
  }
}

function selectedValue(selectId) {
  const node = el(selectId);
  return node ? node.value : "";
}

function optionList(items, selected, placeholder = "") {
  const rows = [];
  if (placeholder) rows.push(`<option value="">${escapeHtml(placeholder)}</option>`);
  for (const item of items) {
    const value = typeof item === "string" ? item : item.value;
    const label = typeof item === "string" ? item : item.label;
    rows.push(`<option value="${escapeHtml(value)}"${value === selected ? " selected" : ""}>${escapeHtml(label)}</option>`);
  }
  return rows.join("");
}

function fillSelect(select, items, selected = "", placeholder = "") {
  if (!select) return;
  const current = selected || select.value;
  select.innerHTML = optionList(items, current, placeholder);
  if (current && Array.from(select.options).some((option) => option.value === current)) {
    select.value = current;
  }
}

function objectTypeOptions(selected = "") {
  const items = state.catalogs.objectTypes.map((obj) => ({
    value: obj.id,
    label: obj.display_name ? `${obj.display_name} (${obj.id})` : obj.id
  }));
  if (!items.length) {
    return optionList(["asset", "work_order", "facility", "sentinel_case"], selected);
  }
  return optionList(items, selected, "Choose object type");
}

function actionTypeOptions(selected = "") {
  const items = state.catalogs.actionTypes.map((action) => ({
    value: action.id,
    label: action.display_name ? `${action.display_name} (${action.id})` : action.id
  }));
  return optionList(items, selected, "Choose action");
}

function ontologyFunctionOptions(selected = "") {
  const items = state.catalogs.ontologyFunctions.map((fn) => ({
    value: fn.id,
    label: fn.display_name ? `${fn.display_name} (${fn.id})` : fn.id
  }));
  return optionList(items, selected, "Choose function");
}

function logicVariables() {
  const variables = state.logicInputs.map((input) => input.name).filter(Boolean);
  for (const block of state.logicBlocks) {
    if (block.output) variables.push(block.output);
    if (block.key) variables.push(block.key);
  }
  return Array.from(new Set(variables));
}

function variableOptions(selected = "", placeholder = "Choose variable") {
  return optionList(logicVariables(), selected, placeholder);
}

function platformResourceRows() {
  const rows = [
    { name: "AIP Logic Workspace", type: "Application", path: "/workspace/aip", role: "Owner", updated: "Current session", view: "aip" },
    { name: "Map Workspace", type: "Application", path: "/workspace/map", role: "Owner", updated: "Current session", view: "map" },
    { name: "Ontology Object Explorer", type: "Application", path: "/workspace/ontology", role: "Owner", updated: "Current session", view: "ontology" }
  ];
  for (const logic of state.catalogs.logicFunctions || []) {
    rows.push({
      name: logic.display_name || logic.id,
      type: "AIP Logic",
      path: `/logic-functions/${logic.id}`,
      role: "Owner",
      updated: "Local catalog",
      view: "aip"
    });
  }
  for (const agent of state.catalogs.agents || []) {
    rows.push({
      name: agent.display_name || agent.id,
      type: "Agent",
      path: `/agents/${agent.id}`,
      role: "Owner",
      updated: "Local catalog",
      view: "aip"
    });
  }
  for (const objectType of state.catalogs.objectTypes || []) {
    rows.push({
      name: objectType.display_name || objectType.id,
      type: "Object type",
      path: `/object-types/${objectType.id}`,
      role: "Ontology",
      updated: "Local catalog",
      view: "ontology"
    });
  }
  for (const suite of state.catalogs.evalSuites || []) {
    rows.push({
      name: suite.display_name || suite.id,
      type: "Eval suite",
      path: `/eval-suites/${suite.id}`,
      role: "Evaluator",
      updated: "Local catalog",
      view: "aip"
    });
  }
  return rows;
}

function renderPlatformView(view = state.view) {
  if (view === "home") renderHomePage();
  if (view === "files") renderFilesPage();
  if (view === "ontology") renderOntologyPage();
  if (view === "applications") renderApplicationsPage();
  renderGlobalSearchResults();
}

function renderHomePage() {
  const appGrid = el("homeAppGrid");
  if (appGrid) {
    appGrid.innerHTML = PLATFORM_APPS.slice(0, 6).map((app) => `
      <button class="app-tile" type="button" data-open-app="${escapeHtml(app.id)}">
        <span class="app-tile-icon ${escapeHtml(app.color)}">${escapeHtml(app.icon)}</span>
        ${escapeHtml(app.name)}
      </button>
    `).join("");
  }
  const recent = el("recentResources");
  if (!recent) return;
  const rows = platformResourceRows().slice(0, 8);
  if (!rows.length) {
    recent.classList.add("resource-empty");
    recent.innerHTML = "No recently viewed resources";
    return;
  }
  recent.classList.remove("resource-empty");
  recent.innerHTML = `
    <table>
      <thead><tr><th>File name</th><th>Type</th><th>Last updated</th></tr></thead>
      <tbody>
        ${rows.map((row) => `
          <tr data-resource-view="${escapeHtml(row.view)}">
            <td><strong>${escapeHtml(row.name)}</strong><br><span>${escapeHtml(row.path)}</span></td>
            <td>${escapeHtml(row.type)}</td>
            <td>${escapeHtml(row.updated)}</td>
          </tr>
        `).join("")}
      </tbody>
    </table>
  `;
}

function renderFilesPage() {
  const table = el("filesTable");
  if (!table) return;
  const query = (el("filesSearchInput")?.value || "").toLowerCase().trim();
  const rows = platformResourceRows().filter((row) => {
    const haystack = `${row.name} ${row.type} ${row.path} ${row.role}`.toLowerCase();
    return !query || haystack.includes(query);
  });
  table.innerHTML = `
    <table>
      <thead>
        <tr><th>File name</th><th>Views</th><th>Your role</th><th>Tags</th><th>Portfolio</th><th>Last modified</th></tr>
      </thead>
      <tbody>
        ${rows.map((row, index) => `
          <tr data-resource-view="${escapeHtml(row.view)}">
            <td><strong>${escapeHtml(row.name)}</strong><br><span>${escapeHtml(row.path)}</span></td>
            <td>${index % 3}</td>
            <td>${escapeHtml(row.role)}</td>
            <td>${escapeHtml(row.type)}</td>
            <td>Local platform</td>
            <td>${escapeHtml(row.updated)}</td>
          </tr>
        `).join("") || '<tr><td colspan="6">No matching resources</td></tr>'}
      </tbody>
    </table>
  `;
}

function renderOntologyPage() {
  const table = el("ontologyCatalogTable");
  if (!table) return;
  const query = (el("objectTypeCatalogFilter")?.value || "").toLowerCase().trim();
  const objectTypes = (state.catalogs.objectTypes || []).filter((objectType) => {
    const haystack = `${objectType.id} ${objectType.display_name || ""} ${objectType.description || ""}`.toLowerCase();
    return !query || haystack.includes(query);
  });
  table.innerHTML = `
    <table>
      <thead>
        <tr><th>Object type name</th><th>Status</th><th>Object count</th><th>Usage</th><th>Type groups</th><th>Description</th></tr>
      </thead>
      <tbody>
        ${objectTypes.map((objectType, index) => `
          <tr>
            <td><strong>${escapeHtml(objectType.display_name || objectType.id)}</strong><br><span>${escapeHtml(objectType.id)}</span></td>
            <td><span class="pill green">Active</span></td>
            <td>${escapeHtml(String(objectType.object_count ?? objectType.count ?? "-"))}</td>
            <td>${index % 2} users</td>
            <td>${escapeHtml((objectType.type_groups || objectType.tags || []).join(", "))}</td>
            <td>${escapeHtml(objectType.description || "Local ontology object type")}</td>
          </tr>
        `).join("") || '<tr><td colspan="6">No object types. Bootstrap the domain to populate the catalog.</td></tr>'}
      </tbody>
    </table>
  `;
}

function renderApplicationsPage() {
  document.querySelectorAll("[data-app-category]").forEach((button) => {
    button.classList.toggle("active", button.dataset.appCategory === state.activeAppCategory);
  });
  const list = el("applicationCatalog");
  if (!list) return;
  const query = (el("appSearchInput")?.value || "").toLowerCase().trim();
  const apps = PLATFORM_APPS.filter((app) => {
    const matchesCategory = state.activeAppCategory === "all" || app.category === state.activeAppCategory;
    const matchesQuery = !query || `${app.name} ${app.description} ${app.category}`.toLowerCase().includes(query);
    return matchesCategory && matchesQuery;
  });
  list.innerHTML = apps.map((app) => `
    <button class="application-row${state.selectedApplication === app.id ? " active" : ""}" type="button" data-open-app="${escapeHtml(app.id)}" data-select-app="${escapeHtml(app.id)}">
      <span class="app-tile-icon ${escapeHtml(app.color)}">${escapeHtml(app.icon)}</span>
      <span><strong>${escapeHtml(app.name)}</strong><span>${escapeHtml(app.description)}</span></span>
    </button>
  `).join("") || '<div class="empty-state dark-empty">No matching applications</div>';
  renderApplicationDetail();
}

function renderApplicationDetail() {
  const detail = el("applicationDetail");
  if (!detail) return;
  const app = PLATFORM_APPS.find((item) => item.id === state.selectedApplication);
  if (!app) {
    detail.innerHTML = '<div class="empty-state dark-empty">Click on an application to see details</div>';
    return;
  }
  detail.innerHTML = `
    <span class="app-tile-icon ${escapeHtml(app.color)}">${escapeHtml(app.icon)}</span>
    <h2>${escapeHtml(app.name)}</h2>
    <p>${escapeHtml(app.description)}</p>
    <button class="btn primary full-width" type="button" data-open-view="${escapeHtml(app.view)}">Open</button>
  `;
}

function searchRows() {
  const resources = platformResourceRows().map((row) => ({
    label: row.name,
    subtitle: row.path,
    type: row.type,
    view: row.view,
    icon: row.type.slice(0, 1).toUpperCase()
  }));
  const apps = PLATFORM_APPS.map((app) => ({
    label: app.name,
    subtitle: app.description,
    type: "App",
    view: app.view,
    icon: app.icon
  }));
  return [...apps, ...resources];
}

function renderGlobalSearchResults() {
  const container = el("globalSearchResults");
  if (!container) return;
  const query = (el("globalSearchInput")?.value || state.lastSearchQuery || "").toLowerCase().trim();
  const rows = searchRows().filter((row) => {
    const haystack = `${row.label} ${row.subtitle} ${row.type}`.toLowerCase();
    return !query || haystack.includes(query);
  }).slice(0, 12);
  const label = el("searchCommandLabel");
  if (label) label.textContent = query ? `All search results for '${query}'` : "Highlighted samples from your results";
  container.innerHTML = rows.map((row) => `
    <button class="search-result-row" type="button" data-open-view="${escapeHtml(row.view)}">
      <span>${escapeHtml(row.icon)}</span>
      <span><strong>${escapeHtml(row.label)}</strong><br><small>${escapeHtml(row.subtitle)}</small></span>
      <span class="search-result-type">${escapeHtml(row.type)}</span>
    </button>
  `).join("") || '<div class="empty-state dark-empty">No matching results</div>';
}

function openGlobalSearch() {
  const overlay = el("globalSearchOverlay");
  overlay.classList.remove("hidden");
  renderGlobalSearchResults();
  window.setTimeout(() => el("globalSearchInput")?.focus(), 0);
}

function closeGlobalSearch() {
  el("globalSearchOverlay").classList.add("hidden");
}

function openApplication(appId) {
  const app = PLATFORM_APPS.find((item) => item.id === appId);
  if (!app) return;
  state.selectedApplication = app.id;
  if (state.view === "applications") {
    renderApplicationsPage();
    return;
  }
  setView(app.view);
}

function defaultWorkshopDraft() {
  const objectTypeId = state.catalogs.objectTypes[0]?.id || "asset";
  const actionTypeId = state.catalogs.actionTypes[0]?.id || "";
  return {
    display_name: "Operations Workshop",
    description: "Local operational app built from ontology objects, variables, widgets, and events.",
    variables: {
      critical_assets: { definition_type: "object_set", object_type_id: objectTypeId, filters: { criticality: "high" }, limit: 50 },
      asset_count: { definition_type: "object_set_aggregation", object_type_id: objectTypeId, filters: {}, op: "count" },
      assist_prompt: { definition_type: "static", value: "Summarize operational risk and recommend next action." }
    },
    widgets: [
      { type: "metric", title: "Asset Count", variable: "asset_count", object_type_id: objectTypeId, config: { format: "integer" } },
      { type: "object_table", title: "Critical Assets", variable: "critical_assets", object_type_id: objectTypeId, config: { columns: ["name", "status", "criticality"] } },
      { type: "chart", title: "Criticality Mix", variable: "critical_assets", object_type_id: objectTypeId, config: { field: "criticality" } },
      { type: "map", title: "Operational Map", object_type_id: objectTypeId, config: { geometry_field: "geometry" } },
      { type: "object_view", title: "Object View", variable: "critical_assets", object_type_id: objectTypeId, config: {} },
      { type: "button", title: "Apply Action", action_type_id: actionTypeId, config: { label: "Run action" } },
      { type: "text", title: "AIP Prompt", variable: "assist_prompt", config: {} },
      { type: "filter_list", title: "Status Filter", variable: "critical_assets", object_type_id: objectTypeId, config: { field: "status" } },
      { type: "aip_assist", title: "AIP Assist", variable: "assist_prompt", config: { mode: "summarize" } }
    ],
    layout: {
      columns: 2,
      events: [
        { type: "set_variable", target: "selected_status", value: "RUNNING" },
        { type: "navigate", page: "detail" }
      ]
    }
  };
}

function normalizeWorkshopDraft(module) {
  if (!module) return defaultWorkshopDraft();
  return {
    id: module.id,
    display_name: module.display_name || "Operations Workshop",
    description: module.description || "",
    variables: module.variables || {},
    widgets: module.widgets || [],
    layout: module.layout || { columns: 2, events: [] }
  };
}

function workshopVariableNames() {
  return Object.keys(state.workshop.draft?.variables || {});
}

async function refreshWorkshop() {
  await Promise.allSettled([refreshLogicCatalogs(), loadDataAssets()]);
  try {
    state.workshop.modules = await api("/apps/workshop");
    if (!state.workshop.selectedId && state.workshop.modules.length) state.workshop.selectedId = state.workshop.modules[0].id;
    const selected = state.workshop.modules.find((module) => module.id === state.workshop.selectedId);
    state.workshop.draft = normalizeWorkshopDraft(selected);
    await loadWorkshopVersions();
    renderWorkshopBuilder();
  } catch (error) {
    state.workshop.draft = state.workshop.draft || defaultWorkshopDraft();
    renderWorkshopBuilder();
    showToast(error.message);
  }
}

async function loadWorkshopVersions() {
  if (!state.workshop.selectedId) {
    state.workshop.versions = [];
    return;
  }
  try {
    state.workshop.versions = await api(`/apps/workshop/${encodeURIComponent(state.workshop.selectedId)}/versions`);
  } catch (_) {
    state.workshop.versions = [];
  }
}

function renderWorkshopBuilder() {
  const draft = state.workshop.draft || defaultWorkshopDraft();
  state.workshop.draft = draft;
  fillSelect(el("workshopModuleSelect"), state.workshop.modules.map((module) => ({ value: module.id, label: module.display_name || module.id })), state.workshop.selectedId, "Unsaved module");
  el("workshopTitle").textContent = draft.display_name || "Workshop Builder";
  el("workshopSummary").textContent = `${Object.keys(draft.variables || {}).length} variables - ${draft.widgets.length} widgets - ${(draft.layout?.events || []).length} events`;
  renderWorkshopPanels();
  renderWorkshopCanvas();
  renderWorkshopConfig();
  renderWorkshopVersions();
}

function renderWorkshopPanels() {
  document.querySelectorAll("[data-workshop-panel]").forEach((button) => {
    button.classList.toggle("active", button.dataset.workshopPanel === state.workshop.activePanel);
  });
  document.querySelectorAll("[data-workshop-panel-body]").forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.workshopPanelBody === state.workshop.activePanel);
  });
  el("workshopWidgetPicker").innerHTML = WORKSHOP_WIDGET_TYPES.map((widget) => `
    <button class="node-library-item" type="button" data-add-workshop-widget="${escapeHtml(widget.type)}">
      <strong>${escapeHtml(widget.title)}</strong>
      <span>${escapeHtml(widget.type)}</span>
    </button>
  `).join("");
  renderWorkshopVariables();
  renderWorkshopEvents();
}

function renderWorkshopVariables() {
  const variables = state.workshop.draft?.variables || {};
  const rows = Object.entries(variables).map(([name, spec]) => `
    <div class="builder-row" data-workshop-variable="${escapeHtml(name)}">
      <input data-variable-field="name" value="${escapeHtml(name)}" />
      <select data-variable-field="definition_type">
        ${optionList(["static", "state", "object_set", "object_set_aggregation", "object_property", "function", "variable_transformation"], spec.definition_type || "static")}
      </select>
      <select data-variable-field="object_type_id">${objectTypeOptions(spec.object_type_id || "")}</select>
      <textarea data-variable-field="json" rows="3">${escapeHtml(compactJson(spec))}</textarea>
      <button class="btn small" data-remove-workshop-variable="${escapeHtml(name)}" type="button">-</button>
    </div>
  `).join("");
  el("workshopVariables").innerHTML = rows || '<div class="empty-state compact-empty">No variables</div>';
}

function renderWorkshopEvents() {
  const events = state.workshop.draft?.layout?.events || [];
  el("workshopEvents").innerHTML = events.map((event, index) => `
    <div class="builder-row" data-workshop-event="${index}">
      <select data-event-field="type">${optionList(["set_variable", "reset_variable", "navigate", "toggle_section", "open_overlay", "close_overlay", "apply_action"], event.type || "set_variable")}</select>
      <textarea data-event-field="json" rows="3">${escapeHtml(compactJson(event))}</textarea>
      <button class="btn small" data-remove-workshop-event="${index}" type="button">-</button>
    </div>
  `).join("") || '<div class="empty-state compact-empty">No events</div>';
}

function renderWorkshopCanvas() {
  const draft = state.workshop.draft || defaultWorkshopDraft();
  const liveWidgets = state.workshop.render?.widgets || [];
  el("workshopCanvas").classList.toggle("preview", state.workshop.preview);
  el("workshopCanvas").innerHTML = draft.widgets.map((widget, index) => {
    const live = liveWidgets[index] || {};
    const selected = state.workshop.selectedWidgetIndex === index ? " selected" : "";
    return `
      <article class="workshop-widget${selected}" data-workshop-widget-index="${index}">
        <div class="widget-head">
          <strong>${escapeHtml(widget.title || widget.type)}</strong>
          <span>${escapeHtml(widget.type)}</span>
        </div>
        ${renderWorkshopWidgetBody(widget, live)}
      </article>
    `;
  }).join("") || '<div class="empty-state">Use the widget picker to build a Workshop module</div>';
  el("workshopLiveData").textContent = state.workshop.render ? compactJson(state.workshop.render) : "No live render yet";
}

function renderWorkshopWidgetBody(widget, live) {
  const type = widget.type;
  if (type === "object_table") {
    const ids = live.sample_ids || [];
    return `<table><thead><tr><th>Object</th><th>Status</th></tr></thead><tbody>${ids.map((id) => `<tr><td>${escapeHtml(id)}</td><td>resolved</td></tr>`).join("") || '<tr><td colspan="2">No resolved rows</td></tr>'}</tbody></table>`;
  }
  if (type === "metric") return `<div class="big-metric">${escapeHtml(live.value ?? "-")}</div>`;
  if (type === "chart" || type === "filter_list") {
    const count = live.row_count || live.value?.count || 0;
    return `<div class="bar-list"><span style="width:${Math.min(100, Number(count) * 12)}%"></span><strong>${escapeHtml(count)} records</strong></div>`;
  }
  if (type === "map") return '<div class="mini-map-surface">Map widget</div>';
  if (type === "button") return `<button class="btn primary" type="button">${escapeHtml(widget.config?.label || widget.title || "Run action")}</button>`;
  if (type === "aip_assist") return `<div class="answer-box">${escapeHtml(live.value || widget.config?.mode || "Assist ready")}</div>`;
  if (type === "object_view") return `<pre class="mini-output">${escapeHtml(compactJson(live.value || live))}</pre>`;
  return `<p>${escapeHtml(live.value ?? widget.config?.text ?? "")}</p>`;
}

function renderWorkshopConfig() {
  const draft = state.workshop.draft || defaultWorkshopDraft();
  const widget = draft.widgets[state.workshop.selectedWidgetIndex];
  if (!widget) {
    el("workshopConfig").innerHTML = '<div class="empty-state compact-empty">Select a widget</div>';
    return;
  }
  el("workshopConfig").innerHTML = `
    <label class="field"><span>Title</span><input data-workshop-widget-field="title" value="${escapeHtml(widget.title || "")}" /></label>
    <label class="field"><span>Type</span><select data-workshop-widget-field="type">${optionList(WORKSHOP_WIDGET_TYPES.map((item) => ({ value: item.type === "button_action" ? "button" : item.type, label: item.title })), widget.type || "")}</select></label>
    <label class="field"><span>Variable</span><select data-workshop-widget-field="variable">${optionList(workshopVariableNames(), widget.variable || "", "No variable")}</select></label>
    <label class="field"><span>Object Type</span><select data-workshop-widget-field="object_type_id">${objectTypeOptions(widget.object_type_id || "")}</select></label>
    <label class="field"><span>Action</span><select data-workshop-widget-field="action_type_id">${actionTypeOptions(widget.action_type_id || "")}</select></label>
    <label class="field"><span>Config JSON</span><textarea data-workshop-widget-field="config" rows="6">${escapeHtml(compactJson(widget.config || {}))}</textarea></label>
    <button class="btn full-width" data-remove-workshop-widget="${state.workshop.selectedWidgetIndex}" type="button">Remove Widget</button>
  `;
}

function renderWorkshopVersions() {
  const rows = state.workshop.versions || [];
  el("workshopVersions").innerHTML = rows.map((version) => `
    <button class="builder-list-button" type="button" data-restore-workshop-version="${escapeHtml(version.id)}">
      <strong>v${escapeHtml(version.version_number)}</strong>
      <span>${escapeHtml(version.note || version.actor || "published")}</span>
    </button>
  `).join("") || '<div class="empty-state compact-empty">No published versions</div>';
}

async function saveWorkshop() {
  const draft = state.workshop.draft || defaultWorkshopDraft();
  const payload = {
    display_name: draft.display_name,
    description: draft.description,
    variables: draft.variables,
    widgets: draft.widgets,
    layout: draft.layout,
    actor: "workspace"
  };
  const saved = state.workshop.selectedId
    ? await api(`/apps/workshop/${encodeURIComponent(state.workshop.selectedId)}`, { method: "PATCH", body: JSON.stringify(payload) })
    : await api("/apps/workshop", { method: "POST", body: JSON.stringify(payload) });
  state.workshop.selectedId = saved.id;
  state.workshop.draft = normalizeWorkshopDraft(saved);
  await refreshWorkshop();
  showToast("Workshop saved");
  return saved;
}

async function renderWorkshopLive() {
  const saved = state.workshop.selectedId ? state.workshop.draft : await saveWorkshop();
  const moduleId = state.workshop.selectedId || saved.id;
  state.workshop.render = await api(`/apps/workshop/${encodeURIComponent(moduleId)}/render-live`, {
    method: "POST",
    body: JSON.stringify({ state: {} })
  });
  renderWorkshopCanvas();
  showToast("Workshop rendered");
}

async function publishWorkshop() {
  if (!state.workshop.selectedId) await saveWorkshop();
  const version = await api(`/apps/workshop/${encodeURIComponent(state.workshop.selectedId)}/publish`, {
    method: "POST",
    body: JSON.stringify({ actor: "workspace", note: "Published from builder" })
  });
  await loadWorkshopVersions();
  renderWorkshopVersions();
  showToast(`Published v${version.version_number}`);
}

async function restoreWorkshopVersion(versionId) {
  if (!state.workshop.selectedId) return;
  await api(`/apps/workshop/${encodeURIComponent(state.workshop.selectedId)}/versions/${encodeURIComponent(versionId)}/restore`, {
    method: "POST",
    body: JSON.stringify({ actor: "workspace" })
  });
  await refreshWorkshop();
  showToast("Workshop version restored");
}

function addWorkshopWidget(type) {
  const mappedType = type === "button_action" ? "button" : type;
  const objectTypeId = state.catalogs.objectTypes[0]?.id || "asset";
  state.workshop.draft.widgets.push({
    type: mappedType,
    title: WORKSHOP_WIDGET_TYPES.find((item) => item.type === type)?.title || mappedType,
    variable: workshopVariableNames()[0] || "",
    object_type_id: objectTypeId,
    action_type_id: mappedType === "button" ? state.catalogs.actionTypes[0]?.id || "" : "",
    config: {}
  });
  state.workshop.selectedWidgetIndex = state.workshop.draft.widgets.length - 1;
  renderWorkshopBuilder();
}

function defaultPipelineDraft() {
  const assetId = state.datasets[0]?.id || "maintenance_events_raw";
  return {
    display_name: "Operations Pipeline",
    description: "Local Pipeline Builder DAG for dataset transforms and delivery.",
    nodes: [
      { id: "input", type: "input_dataset", label: "Input dataset", config: { asset_id: assetId } },
      { id: "filter", type: "filter", label: "Filter", config: { filters: { status: { not_equals: "closed" } } } },
      { id: "project", type: "project", label: "Project", config: { columns: ["id", "name", "status", "criticality"] } },
      { id: "unique_id", type: "unique_id", label: "Unique ID", config: { target_field: "id", source_fields: ["id", "name"] } },
      { id: "output", type: "dataset_output", label: "Dataset output", config: { asset_id: "operations_pipeline_output" } }
    ],
    edges: [
      { source: "input", target: "filter" },
      { source: "filter", target: "project" },
      { source: "project", target: "unique_id" },
      { source: "unique_id", target: "output" }
    ],
    parameters: {},
    status: "DRAFT"
  };
}

async function loadDataAssets() {
  try {
    state.datasets = await api("/data-assets");
  } catch (_) {
    state.datasets = [];
  }
}

async function refreshPipelineBuilder() {
  await loadDataAssets();
  try {
    state.pipeline.graphs = await api("/pipeline-builder/graphs");
    if (!state.pipeline.selectedId && state.pipeline.graphs.length) state.pipeline.selectedId = state.pipeline.graphs[0].id;
    const selected = state.pipeline.graphs.find((graph) => graph.id === state.pipeline.selectedId);
    state.pipeline.draft = selected ? compactGraph(selected) : (state.pipeline.draft || defaultPipelineDraft());
    renderPipelineBuilder();
  } catch (error) {
    state.pipeline.draft = state.pipeline.draft || defaultPipelineDraft();
    renderPipelineBuilder();
    showToast(error.message);
  }
}

function compactGraph(graph) {
  return {
    id: graph.id,
    display_name: graph.display_name,
    description: graph.description || "",
    nodes: graph.nodes || [],
    edges: graph.edges || [],
    parameters: graph.parameters || {},
    status: graph.status || "DRAFT"
  };
}

function datasetOptions(selected = "") {
  const items = state.datasets.map((asset) => ({ value: asset.id, label: asset.display_name ? `${asset.display_name} (${asset.id})` : asset.id }));
  return optionList(items, selected, "Choose dataset");
}

function renderPipelineBuilder() {
  const draft = state.pipeline.draft || defaultPipelineDraft();
  state.pipeline.draft = draft;
  fillSelect(el("pipelineGraphSelect"), state.pipeline.graphs.map((graph) => ({ value: graph.id, label: graph.display_name || graph.id })), state.pipeline.selectedId, "Unsaved graph");
  el("pipelineTitle").textContent = draft.display_name || "DAG Editor";
  el("pipelineSummary").textContent = `${draft.nodes.length} nodes - ${draft.edges.length} edges - ${draft.status || "DRAFT"}`;
  renderPipelineNodeLibrary();
  renderPipelineCanvas();
  renderPipelineConfig();
  renderPipelinePreview();
  renderPipelineSidePanels();
}

function renderPipelineNodeLibrary() {
  el("pipelineNodeLibrary").innerHTML = PIPELINE_NODE_TYPES.map((node) => `
    <button class="node-library-item" type="button" data-add-pipeline-node="${escapeHtml(node.type)}">
      <strong>${escapeHtml(node.label)}</strong>
      <span>${escapeHtml(node.type)}</span>
    </button>
  `).join("");
}

function renderPipelineCanvas() {
  const draft = state.pipeline.draft || defaultPipelineDraft();
  const nodeOutputs = state.pipeline.preview?.node_outputs || {};
  el("pipelineCanvas").innerHTML = draft.nodes.map((node, index) => {
    const output = nodeOutputs[node.id] || {};
    const selected = state.pipeline.activeNodeId === node.id ? " selected" : "";
    const inbound = draft.edges.filter((edge) => edge.target === node.id).map((edge) => edge.source).join(", ");
    return `
      <article class="pipeline-node${selected}" data-pipeline-node-id="${escapeHtml(node.id)}" style="--node-index:${index}">
        <div class="widget-head"><strong>${escapeHtml(node.label || node.type)}</strong><span>${escapeHtml(node.type)}</span></div>
        <span class="node-meta">in: ${escapeHtml(inbound || "start")} - rows: ${escapeHtml(output.row_count ?? "-")}</span>
      </article>
    `;
  }).join("") || '<div class="empty-state">Add nodes to build a pipeline graph</div>';
}

function renderPipelineConfig() {
  document.querySelectorAll("[data-pipeline-panel]").forEach((button) => {
    button.classList.toggle("active", button.dataset.pipelinePanel === state.pipeline.activePanel);
  });
  document.querySelectorAll("[data-pipeline-panel-body]").forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.pipelinePanelBody === state.pipeline.activePanel);
  });
  const draft = state.pipeline.draft || defaultPipelineDraft();
  const node = draft.nodes.find((item) => item.id === state.pipeline.activeNodeId) || draft.nodes[0];
  if (node && !state.pipeline.activeNodeId) state.pipeline.activeNodeId = node.id;
  if (!node) {
    el("pipelineConfig").innerHTML = '<div class="empty-state compact-empty">Select a node</div>';
    return;
  }
  const config = node.config || {};
  const datasetControl = node.type === "input_dataset" || node.type === "dataset_output" || node.type === "output_dataset"
    ? `<label class="field"><span>Dataset</span><select data-pipeline-node-field="asset_id">${datasetOptions(config.asset_id || config.dataset_id || "")}</select></label>`
    : "";
  el("pipelineConfig").innerHTML = `
    <label class="field"><span>Label</span><input data-pipeline-node-field="label" value="${escapeHtml(node.label || "")}" /></label>
    <label class="field"><span>Type</span><select data-pipeline-node-field="type">${optionList(PIPELINE_NODE_TYPES.map((item) => ({ value: item.type, label: item.label })), node.type)}</select></label>
    ${datasetControl}
    <label class="field"><span>Config JSON</span><textarea data-pipeline-node-field="config" rows="8">${escapeHtml(compactJson(config))}</textarea></label>
    <button class="btn full-width" data-remove-pipeline-node="${escapeHtml(node.id)}" type="button">Remove Node</button>
  `;
}

function renderPipelinePreview() {
  const rows = state.pipeline.preview?.rows || [];
  if (!rows.length) {
    el("pipelinePreviewTable").innerHTML = '<div class="empty-state compact-empty">No preview rows</div>';
    return;
  }
  const columns = Object.keys(rows[0]).slice(0, 8);
  el("pipelinePreviewTable").innerHTML = `
    <table><thead><tr>${columns.map((column) => `<th>${escapeHtml(column)}</th>`).join("")}</tr></thead>
    <tbody>${rows.slice(0, 25).map((row) => `<tr>${columns.map((column) => `<td>${escapeHtml(row[column])}</td>`).join("")}</tr>`).join("")}</tbody></table>
  `;
}

function renderPipelineSidePanels() {
  el("pipelineLineagePanel").textContent = compactJson(state.pipeline.preview?.lineage || state.pipeline.delivery?.lineage || state.pipeline.validation || {});
  const validation = state.pipeline.validation;
  el("pipelineHealthPanel").innerHTML = validation
    ? `<div class="list-item"><strong>${escapeHtml(validation.status)}</strong><span>${escapeHtml(validation.errors?.length || 0)} errors, ${escapeHtml(validation.warnings?.length || 0)} warnings</span></div>`
    : '<div class="empty-state compact-empty">Validate to inspect graph health</div>';
  el("pipelineSchedulePanel").innerHTML = `
    <div class="list-item"><strong>Manual delivery</strong><span>Local deterministic runtime</span></div>
    <div class="list-item"><strong>Build status</strong><span>${escapeHtml(state.pipeline.delivery?.status || "No build yet")}</span></div>
  `;
}

async function savePipelineGraph() {
  const draft = state.pipeline.draft || defaultPipelineDraft();
  const payload = {
    display_name: draft.display_name,
    description: draft.description,
    nodes: draft.nodes,
    edges: draft.edges,
    parameters: draft.parameters || {},
    status: draft.status || "DRAFT"
  };
  const saved = state.pipeline.selectedId
    ? await api(`/pipeline-builder/graphs/${encodeURIComponent(state.pipeline.selectedId)}`, { method: "PATCH", body: JSON.stringify(payload) })
    : await api("/pipeline-builder/graphs", { method: "POST", body: JSON.stringify(payload) });
  state.pipeline.selectedId = saved.id;
  state.pipeline.draft = compactGraph(saved);
  await refreshPipelineBuilder();
  showToast("Pipeline graph saved");
  return saved;
}

async function validatePipelineGraph() {
  if (!state.pipeline.selectedId) await savePipelineGraph();
  state.pipeline.validation = await api(`/pipeline-builder/graphs/${encodeURIComponent(state.pipeline.selectedId)}/validate`, { method: "POST" });
  renderPipelineSidePanels();
  showToast(state.pipeline.validation.status);
}

async function previewPipelineGraph() {
  if (!state.pipeline.selectedId) await savePipelineGraph();
  state.pipeline.preview = await api(`/pipeline-builder/graphs/${encodeURIComponent(state.pipeline.selectedId)}/preview`, {
    method: "POST",
    body: JSON.stringify({ limit: 50 })
  });
  renderPipelineBuilder();
  showToast("Pipeline preview ready");
}

async function deliverPipelineGraph() {
  if (!state.pipeline.selectedId) await savePipelineGraph();
  state.pipeline.delivery = await api(`/pipeline-builder/graphs/${encodeURIComponent(state.pipeline.selectedId)}/deliver`, {
    method: "POST",
    body: JSON.stringify({ actor: "workspace" })
  });
  await loadDataAssets();
  renderPipelineSidePanels();
  showToast(`Delivered ${state.pipeline.delivery.records_out} rows`);
}

function addPipelineNode(type) {
  const draft = state.pipeline.draft || defaultPipelineDraft();
  const id = `${type}_${draft.nodes.length + 1}`;
  const config = type === "input_dataset" ? { asset_id: state.datasets[0]?.id || "" }
    : type === "dataset_output" ? { asset_id: `${draft.display_name || "pipeline"}_output`.toLowerCase().replace(/[^a-z0-9_]+/g, "_") }
    : {};
  const previous = draft.nodes[draft.nodes.length - 1];
  draft.nodes.push({ id, type, label: PIPELINE_NODE_TYPES.find((node) => node.type === type)?.label || type, config });
  if (previous) draft.edges.push({ source: previous.id, target: id });
  state.pipeline.activeNodeId = id;
  renderPipelineBuilder();
}

async function refreshObjectExplorer() {
  await refreshLogicCatalogs();
  try {
    state.objectExplorer.explorations = await api("/object-explorer/explorations");
  } catch (_) {
    state.objectExplorer.explorations = [];
  }
  fillSelect(el("explorerObjectTypeSelect"), state.catalogs.objectTypes.map((obj) => ({ value: obj.id, label: obj.display_name ? `${obj.display_name} (${obj.id})` : obj.id })), el("explorerObjectTypeSelect")?.value || state.catalogs.objectTypes[0]?.id || "asset");
  renderSavedExplorations();
  await runObjectExplorerQuery(false);
}

async function runObjectExplorerQuery(notify = true) {
  const objectTypeId = el("explorerObjectTypeSelect")?.value || state.catalogs.objectTypes[0]?.id;
  if (!objectTypeId) {
    renderObjectExplorer();
    return;
  }
  try {
    const filters = parseJsonValue(el("explorerFiltersInput").value, {}, "Explorer filters");
    state.objectExplorer.query = await api("/object-explorer/query", {
      method: "POST",
      body: JSON.stringify({
        object_type_id: objectTypeId,
        query: el("explorerSearchInput").value,
        filters,
        limit: 250,
        selected_ids: state.objectExplorer.selectedObjectId ? [state.objectExplorer.selectedObjectId] : []
      })
    });
    renderObjectExplorer();
    if (notify) showToast(`${state.objectExplorer.query.result_count} objects`);
  } catch (error) {
    showToast(error.message);
  }
}

function renderObjectExplorer() {
  const query = state.objectExplorer.query;
  el("explorerTitle").textContent = query?.object_type?.display_name || "Exploration";
  el("explorerSummary").textContent = query ? `${query.result_count} results - ${query.columns.length} columns - ${query.facets.length} charts` : "Select an object type and run a query";
  renderSavedExplorations();
  renderExplorerFacets();
  renderExplorerResults();
  renderExplorerActions();
}

function renderSavedExplorations() {
  el("savedExplorations").innerHTML = state.objectExplorer.explorations.map((exploration) => `
    <button class="builder-list-button" type="button" data-load-exploration="${escapeHtml(exploration.id)}">
      <strong>${escapeHtml(exploration.display_name)}</strong>
      <span>${escapeHtml(exploration.object_type_id)}</span>
    </button>
  `).join("") || '<div class="empty-state compact-empty">No saved explorations</div>';
}

function renderExplorerFacets() {
  const facets = state.objectExplorer.query?.facets || [];
  const html = facets.map((facet) => `
    <section class="facet-card">
      <strong>${escapeHtml(facet.field)}</strong>
      ${(facet.buckets || []).slice(0, 8).map((bucket) => `
        <button type="button" data-facet-field="${escapeHtml(facet.field)}" data-facet-value="${escapeHtml(bucket.value ?? "")}" data-facet-range="${escapeHtml(bucket.range ? JSON.stringify(bucket.range) : "")}">
          <span>${escapeHtml(bucket.label || bucket.value || bucket.range?.join(" - "))}</span><b>${escapeHtml(bucket.count)}</b>
        </button>
      `).join("")}
    </section>
  `).join("");
  el("explorerFacetRail").innerHTML = html || '<div class="empty-state compact-empty">No charts yet</div>';
  el("explorerCharts").innerHTML = html || '<div class="empty-state compact-empty">Run a query to generate filter charts</div>';
}

function renderExplorerResults() {
  const query = state.objectExplorer.query;
  if (!query?.objects?.length) {
    el("explorerResults").innerHTML = '<div class="empty-state">No objects returned</div>';
    el("explorerObjectPreview").className = "object-profile empty-state";
    el("explorerObjectPreview").textContent = "No object selected";
    return;
  }
  const columns = query.columns.slice(0, 8);
  el("explorerResults").innerHTML = `
    <table><thead><tr><th></th><th>ID</th>${columns.map((column) => `<th>${escapeHtml(column)}</th>`).join("")}</tr></thead>
    <tbody>${query.objects.map((obj) => `
      <tr data-explorer-object-id="${escapeHtml(obj.id)}" class="${state.objectExplorer.selectedObjectId === obj.id ? "selected" : ""}">
        <td><input type="checkbox" data-explorer-select-id="${escapeHtml(obj.id)}"${state.objectExplorer.selectedIds.includes(obj.id) ? " checked" : ""} /></td>
        <td><strong>${escapeHtml(obj.id)}</strong></td>
        ${columns.map((column) => `<td>${escapeHtml(runtimeCellValue(obj, column))}</td>`).join("")}
      </tr>
    `).join("")}</tbody></table>
  `;
}

function runtimeCellValue(obj, field) {
  if (obj[field] !== undefined) return obj[field];
  let value = obj.properties || {};
  for (const part of String(field).split(".")) {
    if (!value || typeof value !== "object") return "";
    value = value[part];
  }
  return value ?? "";
}

function renderExplorerActions() {
  const actions = state.objectExplorer.query?.available_actions || [];
  el("explorerActionList").innerHTML = actions.map((action) => `
    <button class="builder-list-button" type="button" data-open-bulk-action="${escapeHtml(action.id)}">
      <strong>${escapeHtml(action.display_name || action.id)}</strong>
      <span>${escapeHtml(action.description || action.id)}</span>
    </button>
  `).join("") || '<div class="empty-state compact-empty">No actions available</div>';
  fillSelect(el("bulkActionSelect"), actions.map((action) => ({ value: action.id, label: action.display_name || action.id })), state.objectExplorer.activeActionId, "Choose action");
}

async function selectExplorerObject(objectId) {
  state.objectExplorer.selectedObjectId = objectId;
  const objectTypeId = el("explorerObjectTypeSelect").value;
  try {
    const profile = await api(`/objects/${encodeURIComponent(objectTypeId)}/${encodeURIComponent(objectId)}/profile`);
    el("explorerObjectPreview").className = "object-profile";
    renderExplorerProfile(profile);
  } catch (error) {
    showToast(error.message);
  }
  renderExplorerResults();
}

function renderExplorerProfile(profile) {
  const obj = profile.object || {};
  const props = obj.properties || {};
  const entries = [
    ["ID", obj.id],
    ["Type", obj.object_type_id],
    ["Name", props.name || props.title || ""],
    ["Status", props.status || ""],
    ["Criticality", props.criticality || ""],
    ["Links", `${profile.metrics?.inbound_link_count || 0} in / ${profile.metrics?.outbound_link_count || 0} out`]
  ];
  el("explorerObjectPreview").innerHTML = entries.map(([key, value]) => `<div class="kv"><span>${escapeHtml(key)}</span><strong>${escapeHtml(value)}</strong></div>`).join("");
}

async function saveExploration() {
  const objectTypeId = el("explorerObjectTypeSelect").value;
  const filters = parseJsonValue(el("explorerFiltersInput").value, {}, "Explorer filters");
  const existing = state.objectExplorer.explorations.find((item) => item.object_type_id === objectTypeId && JSON.stringify(item.filters) === JSON.stringify(filters));
  const payload = {
    display_name: `${objectTypeId} exploration`,
    object_type_id: objectTypeId,
    filters,
    columns: state.objectExplorer.query?.columns || [],
    charts: state.objectExplorer.query?.facets || [],
    perspective: { selected_object_id: state.objectExplorer.selectedObjectId },
    owner: "workspace"
  };
  const saved = existing
    ? await api(`/object-explorer/explorations/${encodeURIComponent(existing.id)}`, { method: "PATCH", body: JSON.stringify(payload) })
    : await api("/object-explorer/explorations", { method: "POST", body: JSON.stringify(payload) });
  await refreshObjectExplorer();
  showToast(`Saved ${saved.display_name}`);
}

async function loadExploration(explorationId) {
  const exploration = await api(`/object-explorer/explorations/${encodeURIComponent(explorationId)}`);
  el("explorerObjectTypeSelect").value = exploration.object_type_id;
  el("explorerFiltersInput").value = compactJson(exploration.filters || {});
  state.objectExplorer.selectedObjectId = exploration.perspective?.selected_object_id || "";
  await runObjectExplorerQuery();
}

function openBulkAction(actionId = "") {
  state.objectExplorer.activeActionId = actionId || state.objectExplorer.query?.available_actions?.[0]?.id || "";
  renderExplorerActions();
  el("bulkActionParams").value = compactJson({ reason: "Bulk action from Object Explorer" });
  el("objectBulkModal").classList.remove("hidden");
}

async function executeBulkAction() {
  const actionTypeId = el("bulkActionSelect").value;
  const ids = state.objectExplorer.selectedIds.length ? state.objectExplorer.selectedIds : (state.objectExplorer.selectedObjectId ? [state.objectExplorer.selectedObjectId] : []);
  if (!actionTypeId || !ids.length) {
    showToast("Select an action and at least one object");
    return;
  }
  const baseParams = parseJsonValue(el("bulkActionParams").value, {}, "Bulk action parameters");
  const results = [];
  for (const objectId of ids) {
    results.push(await api("/actions/execute", {
      method: "POST",
      body: JSON.stringify({
        action_type_id: actionTypeId,
        parameters: { ...baseParams, object_id: objectId },
        idempotency_key: `object-explorer-${actionTypeId}-${objectId}-${Date.now()}`,
        actor: "object_explorer"
      })
    }));
  }
  el("objectBulkModal").classList.add("hidden");
  showToast(`Executed ${results.length} action requests`);
}

function handleWorkshopWidgetConfig(event) {
  const field = event.target.dataset.workshopWidgetField;
  if (!field) return;
  const widget = state.workshop.draft?.widgets?.[state.workshop.selectedWidgetIndex];
  if (!widget) return;
  try {
    if (field === "config") widget.config = parseJsonValue(event.target.value, {}, "Widget config");
    else widget[field] = event.target.value;
    renderWorkshopCanvas();
  } catch (error) {
    showToast(error.message);
  }
}

function handleWorkshopVariableEvent(event) {
  const row = event.target.closest("[data-workshop-variable]");
  const field = event.target.dataset.variableField;
  if (!row || !field) return;
  const oldName = row.dataset.workshopVariable;
  const variables = state.workshop.draft.variables || {};
  try {
    let spec = variables[oldName] || { definition_type: "static", value: "" };
    if (field === "json") {
      spec = parseJsonValue(event.target.value, spec, "Variable JSON");
    } else if (field === "name") {
      const newName = event.target.value.trim();
      if (newName && newName !== oldName) {
        delete variables[oldName];
        variables[newName] = spec;
        renderWorkshopBuilder();
        return;
      }
    } else {
      spec[field] = event.target.value;
    }
    variables[oldName] = spec;
  } catch (error) {
    showToast(error.message);
  }
}

function handleWorkshopEventChange(event) {
  const row = event.target.closest("[data-workshop-event]");
  const field = event.target.dataset.eventField;
  if (!row || !field) return;
  const index = Number(row.dataset.workshopEvent);
  const events = state.workshop.draft.layout.events || [];
  try {
    if (field === "json") events[index] = parseJsonValue(event.target.value, events[index] || {}, "Event JSON");
    else events[index][field] = event.target.value;
  } catch (error) {
    showToast(error.message);
  }
}

function handleExplorerFacetClick(event) {
  const button = event.target.closest("[data-facet-field]");
  if (!button) return;
  const field = button.dataset.facetField;
  const current = parseJsonValue(el("explorerFiltersInput").value, {}, "Explorer filters");
  if (button.dataset.facetRange) {
    const range = JSON.parse(button.dataset.facetRange);
    current[field] = { gte: range[0], lte: range[1] };
  } else {
    current[field] = button.dataset.facetValue;
  }
  el("explorerFiltersInput").value = compactJson(current);
  runObjectExplorerQuery();
}

function handlePipelineNodeChange(event) {
  const field = event.target.dataset.pipelineNodeField;
  if (!field) return;
  const node = state.pipeline.draft?.nodes?.find((item) => item.id === state.pipeline.activeNodeId);
  if (!node) return;
  try {
    if (field === "config") {
      node.config = parseJsonValue(event.target.value, {}, "Node config");
    } else if (field === "asset_id") {
      node.config = { ...(node.config || {}), asset_id: event.target.value };
    } else {
      node[field] = event.target.value;
    }
    renderPipelineCanvas();
  } catch (error) {
    showToast(error.message);
  }
}

async function refreshHealth() {
  const statusEl = el("systemStatus");
  try {
    const status = await api("/");
    const capabilities = Array.isArray(status.capabilities) ? status.capabilities : [];
    statusEl.textContent = capabilities.length ? `API online - ${capabilities.length} capabilities` : "API online";
    statusEl.title = capabilities.join("\n");
  } catch (error) {
    statusEl.textContent = "API unavailable";
    statusEl.title = error.message;
  }
}

async function refreshLogicCatalogs() {
  const [objectTypes, actionTypes, logicFunctions, ontologyFunctions] = await Promise.allSettled([
    api("/object-types"),
    api("/action-types"),
    api("/logic-functions"),
    api("/ontology-functions")
  ]);
  if (objectTypes.status === "fulfilled") state.catalogs.objectTypes = objectTypes.value;
  if (actionTypes.status === "fulfilled") state.catalogs.actionTypes = actionTypes.value;
  if (logicFunctions.status === "fulfilled") state.catalogs.logicFunctions = logicFunctions.value;
  if (ontologyFunctions.status === "fulfilled") state.catalogs.ontologyFunctions = ontologyFunctions.value;
  renderLogicBuilder();
  if (!["map", "aip"].includes(state.view)) renderPlatformView(state.view);
}

function renderLogicBuilder() {
  renderBlockTypeSelect();
  renderLogicFunctionSelect();
  renderLogicInputs();
  renderLogicRunInputs();
  renderLogicBlocks();
  renderLogicOutputSelect();
  renderLogicHistory();
  renderContextObjectTypeSelect();
}

function renderBlockTypeSelect() {
  fillSelect(
    el("blockTypeSelect"),
    LOGIC_BLOCK_TYPES.map((block) => ({ value: block.type, label: block.label })),
    "llm"
  );
}

function renderLogicFunctionSelect() {
  const items = state.catalogs.logicFunctions.map((logic) => ({
    value: logic.id,
    label: logic.display_name ? `${logic.display_name} (${logic.id})` : logic.id
  }));
  fillSelect(el("logicFunctionSelect"), items, state.lastLogicId || "", "New draft logic");
}

function renderContextObjectTypeSelect() {
  const select = el("objectTypeSelect");
  if (!select) return;
  const selected = select.value || "asset";
  select.innerHTML = objectTypeOptions(selected);
  if (Array.from(select.options).some((option) => option.value === selected)) {
    select.value = selected;
  }
}

function renderLogicInputs() {
  const container = el("logicInputs");
  if (!container) return;
  container.innerHTML = state.logicInputs.map((input, index) => `
    <div class="logic-input-row" data-input-index="${index}">
      <label class="field">
        <span>Name</span>
        <input value="${escapeHtml(input.name)}" data-input-field="name" />
      </label>
      <label class="field">
        <span>Type</span>
        <select data-input-field="type">${optionList(LOGIC_INPUT_TYPES, input.type)}</select>
      </label>
      <button class="btn" type="button" data-remove-input="${index}">-</button>
    </div>
  `).join("");
}

function sampleLogicInputValue(input) {
  const name = String(input.name || "").toLowerCase();
  if (name === "prompt") return "Summarize critical maintenance risk";
  if (name === "work_order_id") return "wo_pump_urgent";
  if (name === "asset_id") return "asset_pump_4";
  if (name.endsWith("_id")) return `sample_${name}`;
  if (["integer", "long", "short", "number"].includes(input.type)) return 1;
  if (["float", "double"].includes(input.type)) return 1.0;
  if (input.type === "boolean") return false;
  if (["json", "object", "struct", "media_reference"].includes(input.type)) return {};
  if (["array", "object_list", "object_set"].includes(input.type)) return [];
  return `sample_${input.name || "value"}`;
}

function renderLogicRunInputs() {
  const textarea = el("logicRunInputs");
  if (!textarea) return;
  let current = {};
  try {
    current = textarea.value.trim() ? JSON.parse(textarea.value) : {};
  } catch {
    return;
  }
  if (!current || Array.isArray(current) || typeof current !== "object") current = {};
  const next = {};
  for (const input of state.logicInputs) {
    if (!input.name) continue;
    next[input.name] = Object.prototype.hasOwnProperty.call(current, input.name)
      ? current[input.name]
      : sampleLogicInputValue(input);
  }
  const nextText = compactJson(next);
  if (textarea.value.trim() !== nextText) textarea.value = nextText;
}

function defaultLogicBlock(type) {
  if (type === "object_query") {
    return { type, object_type_id: firstObjectType(), filters: "{}", limit: 20, output: "objects" };
  }
  if (type === "object_aggregate") {
    return { type, object_type_id: firstObjectType(), filters: "{}", op: "count", field: "", output: "aggregate" };
  }
  if (type === "propose_action" || type === "apply_action") {
    return { type, action_type_id: firstActionType(), parameters: "{}", output: type === "apply_action" ? "applied_action" : "proposed_action" };
  }
  if (type === "pipeline_suggest") {
    return { type, prompt: "$prompt", sample_fields: "id,status,title,description,longitude,latitude", output: "pipeline" };
  }
  if (type === "document_extract") {
    return { type, text: "prompt", schema: '{"summary":"string","entities":"array"}', output: "document" };
  }
  if (type === "assist") {
    return { type, prompt: "$prompt", application_context: "workspace", output: "assist" };
  }
  if (type === "set_output") {
    return { type, key: "result", value: firstVariable() };
  }
  if (type === "conditional") {
    return { type, left: firstVariable(), op: "truthy", right: "", then_key: "branch", then_value: "matched", else_key: "branch", else_value: "fallback" };
  }
  if (type === "for_each") {
    return { type, items: firstVariable(), item_var: "item", output_key: "last_item", value: "item" };
  }
  return { type: "llm", mode: "summarize", prompt: "$prompt", output: "llm_result", object_type_id: firstObjectType(), action_type_id: firstActionType(), function_id: firstOntologyFunction() };
}

function firstObjectType() {
  return state.catalogs.objectTypes[0]?.id || "asset";
}

function firstActionType() {
  return state.catalogs.actionTypes[0]?.id || "";
}

function firstOntologyFunction() {
  return state.catalogs.ontologyFunctions[0]?.id || "";
}

function firstVariable() {
  return logicVariables()[0] || "prompt";
}

function blockLabel(type) {
  return LOGIC_BLOCK_TYPES.find((block) => block.type === type)?.label || type;
}

function renderLogicBlocks() {
  const container = el("logicBlocks");
  if (!container) return;
  container.innerHTML = state.logicBlocks.map((block, index) => renderLogicBlock(block, index)).join("");
  el("logicSummary").textContent = `${state.logicInputs.length} inputs - ${state.logicBlocks.length} blocks - ${logicVariables().length} variables`;
}

function renderLogicBlock(block, index) {
  return `
    <article class="logic-block" data-block-index="${index}">
      <div class="block-header">
        <span class="block-index">${index + 1}</span>
        <div class="block-title">
          <strong>${escapeHtml(blockLabel(block.type))}</strong>
          <span>${escapeHtml(block.output || block.key || "no output variable")}</span>
        </div>
        <div class="button-row">
          <select data-block-field="type">${optionList(LOGIC_BLOCK_TYPES.map((item) => ({ value: item.type, label: item.label })), block.type)}</select>
          <button class="btn small" type="button" data-remove-block="${index}">Remove</button>
        </div>
      </div>
      <div class="block-body">${renderBlockBody(block)}</div>
    </article>
  `;
}

function renderBlockBody(block) {
  if (block.type === "llm") return renderLlmBlock(block);
  if (block.type === "object_query") return renderObjectQueryBlock(block);
  if (block.type === "object_aggregate") return renderObjectAggregateBlock(block);
  if (block.type === "propose_action" || block.type === "apply_action") return renderActionBlock(block);
  if (block.type === "pipeline_suggest") return renderPipelineBlock(block);
  if (block.type === "document_extract") return renderDocumentBlock(block);
  if (block.type === "assist") return renderAssistBlock(block);
  if (block.type === "conditional") return renderConditionalBlock(block);
  if (block.type === "for_each") return renderForEachBlock(block);
  return renderSetOutputBlock(block);
}

function renderLlmBlock(block) {
  return `
    <div class="block-grid three">
      <label class="field"><span>Mode</span><select data-block-field="mode">${optionList(["echo", "template", "summarize", "classify", "extract"], block.mode || "summarize")}</select></label>
      <label class="field"><span>Object Tool</span><select data-block-field="object_type_id">${objectTypeOptions(block.object_type_id)}</select></label>
      <label class="field"><span>Action Tool</span><select data-block-field="action_type_id">${actionTypeOptions(block.action_type_id)}</select></label>
      <label class="field"><span>Function Tool</span><select data-block-field="function_id">${ontologyFunctionOptions(block.function_id)}</select></label>
      <label class="field"><span>Output Variable</span><input data-block-field="output" value="${escapeHtml(block.output || "llm_result")}" /></label>
    </div>
    <label class="field"><span>Prompt</span><textarea rows="4" data-block-field="prompt">${escapeHtml(block.prompt || "$prompt")}</textarea></label>
  `;
}

function renderObjectQueryBlock(block) {
  return `
    <div class="block-grid three">
      <label class="field"><span>Object Type</span><select data-block-field="object_type_id">${objectTypeOptions(block.object_type_id)}</select></label>
      <label class="field"><span>Limit</span><input type="number" min="1" max="1000" data-block-field="limit" value="${escapeHtml(block.limit || 20)}" /></label>
      <label class="field"><span>Output Variable</span><input data-block-field="output" value="${escapeHtml(block.output || "objects")}" /></label>
    </div>
    <label class="field"><span>Filters JSON</span><textarea rows="3" data-block-field="filters">${escapeHtml(block.filters || "{}")}</textarea></label>
  `;
}

function renderObjectAggregateBlock(block) {
  return `
    <div class="block-grid three">
      <label class="field"><span>Object Type</span><select data-block-field="object_type_id">${objectTypeOptions(block.object_type_id)}</select></label>
      <label class="field"><span>Aggregate</span><select data-block-field="op">${optionList(["count", "sum", "avg", "min", "max"], block.op || "count")}</select></label>
      <label class="field"><span>Field</span><input data-block-field="field" value="${escapeHtml(block.field || "")}" placeholder="optional for count" /></label>
      <label class="field"><span>Output Variable</span><input data-block-field="output" value="${escapeHtml(block.output || "aggregate")}" /></label>
    </div>
    <label class="field"><span>Filters JSON</span><textarea rows="3" data-block-field="filters">${escapeHtml(block.filters || "{}")}</textarea></label>
  `;
}

function renderActionBlock(block) {
  return `
    <div class="block-grid">
      <label class="field"><span>Action Type</span><select data-block-field="action_type_id">${actionTypeOptions(block.action_type_id)}</select></label>
      <label class="field"><span>Output Variable</span><input data-block-field="output" value="${escapeHtml(block.output || "action_result")}" /></label>
    </div>
    <label class="field"><span>Parameters JSON</span><textarea rows="4" data-block-field="parameters">${escapeHtml(block.parameters || "{}")}</textarea></label>
  `;
}

function renderPipelineBlock(block) {
  return `
    <label class="field"><span>Prompt</span><textarea rows="4" data-block-field="prompt">${escapeHtml(block.prompt || "$prompt")}</textarea></label>
    <div class="block-grid">
      <label class="field"><span>Sample Fields</span><input data-block-field="sample_fields" value="${escapeHtml(block.sample_fields || "id,status,title,description")}" /></label>
      <label class="field"><span>Output Variable</span><input data-block-field="output" value="${escapeHtml(block.output || "pipeline")}" /></label>
    </div>
  `;
}

function renderDocumentBlock(block) {
  return `
    <div class="block-grid">
      <label class="field"><span>Text Variable</span><select data-block-field="text">${variableOptions(block.text || "prompt")}</select></label>
      <label class="field"><span>Output Variable</span><input data-block-field="output" value="${escapeHtml(block.output || "document")}" /></label>
    </div>
    <label class="field"><span>Extraction Schema JSON</span><textarea rows="4" data-block-field="schema">${escapeHtml(block.schema || "{}")}</textarea></label>
  `;
}

function renderAssistBlock(block) {
  return `
    <div class="block-grid">
      <label class="field"><span>Prompt</span><input data-block-field="prompt" value="${escapeHtml(block.prompt || "$prompt")}" /></label>
      <label class="field"><span>Output Variable</span><input data-block-field="output" value="${escapeHtml(block.output || "assist")}" /></label>
    </div>
    <label class="field"><span>Application Context</span><select data-block-field="application_context">${optionList(["workspace", "logic_builder", "pipeline_builder", "object_explorer"], block.application_context || "workspace")}</select></label>
  `;
}

function renderSetOutputBlock(block) {
  return `
    <div class="block-grid">
      <label class="field"><span>Variable Name</span><input data-block-field="key" value="${escapeHtml(block.key || "result")}" /></label>
      <label class="field"><span>Source Variable</span><select data-block-field="value">${variableOptions(block.value || firstVariable())}</select></label>
    </div>
  `;
}

function renderConditionalBlock(block) {
  return `
    <div class="block-grid three">
      <label class="field"><span>Left Variable</span><select data-block-field="left">${variableOptions(block.left || firstVariable())}</select></label>
      <label class="field"><span>Operator</span><select data-block-field="op">${optionList(LOGIC_COMPARE_OPS, block.op || "truthy")}</select></label>
      <label class="field"><span>Right Value</span><input data-block-field="right" value="${escapeHtml(block.right || "")}" /></label>
      <label class="field"><span>Then Key</span><input data-block-field="then_key" value="${escapeHtml(block.then_key || "branch")}" /></label>
      <label class="field"><span>Then Value</span><input data-block-field="then_value" value="${escapeHtml(block.then_value || "matched")}" /></label>
      <label class="field"><span>Else Value</span><input data-block-field="else_value" value="${escapeHtml(block.else_value || "fallback")}" /></label>
    </div>
  `;
}

function renderForEachBlock(block) {
  return `
    <div class="block-grid">
      <label class="field"><span>Items Variable</span><select data-block-field="items">${variableOptions(block.items || firstVariable())}</select></label>
      <label class="field"><span>Item Variable</span><input data-block-field="item_var" value="${escapeHtml(block.item_var || "item")}" /></label>
      <label class="field"><span>Set Output Key</span><input data-block-field="output_key" value="${escapeHtml(block.output_key || "last_item")}" /></label>
      <label class="field"><span>Value Variable</span><input data-block-field="value" value="${escapeHtml(block.value || "item")}" /></label>
    </div>
  `;
}

function renderLogicOutputSelect() {
  const select = el("logicOutputVariable");
  if (!select) return;
  const selected = select.value || "result";
  select.innerHTML = variableOptions(selected, "Choose output");
  if (Array.from(select.options).some((option) => option.value === selected)) {
    select.value = selected;
  }
}

function renderLogicHistory() {
  const container = el("logicHistory");
  if (!container) return;
  if (!state.catalogs.logicFunctions.length) {
    container.innerHTML = '<div class="empty-state">No saved logic functions</div>';
    return;
  }
  container.innerHTML = state.catalogs.logicFunctions.slice(0, 10).map((logic) => `
    <div class="list-item">
      <strong>${escapeHtml(logic.display_name || logic.id)}</strong>
      <span>${escapeHtml(logic.id)}</span>
      <span>${escapeHtml((logic.blocks || []).length)} blocks</span>
    </div>
  `).join("");
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
  await Promise.allSettled([refreshLogicCatalogs(), loadAgents(), loadApprovals(), loadEvals(), loadContextObjects()]);
}

async function loadAgents() {
  const select = el("agentSelect");
  select.innerHTML = "";
  try {
    const agents = await api("/agents");
    state.catalogs.agents = agents;
    for (const agent of agents) {
      const option = document.createElement("option");
      option.value = agent.id;
      option.textContent = agent.display_name || agent.id;
      select.appendChild(option);
    }
    if (!["map", "aip"].includes(state.view)) renderPlatformView(state.view);
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
    state.catalogs.evalSuites = evals;
    for (const suite of evals) {
      const option = document.createElement("option");
      option.value = suite.id;
      option.textContent = suite.display_name || suite.id;
      select.appendChild(option);
    }
    if (!["map", "aip"].includes(state.view)) renderPlatformView(state.view);
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

function handleLogicInputEvent(event) {
  const row = event.target.closest("[data-input-index]");
  if (!row) return;
  const index = Number(row.dataset.inputIndex);
  const field = event.target.dataset.inputField;
  if (!field || !state.logicInputs[index]) return;
  state.logicInputs[index][field] = event.target.value;
  renderLogicOutputSelect();
}

function handleLogicInputClick(event) {
  const removeIndex = event.target.dataset.removeInput;
  if (removeIndex === undefined) return;
  state.logicInputs.splice(Number(removeIndex), 1);
  if (!state.logicInputs.length) state.logicInputs.push({ name: "prompt", type: "string" });
  renderLogicBuilder();
}

function addLogicInput() {
  const next = state.logicInputs.length + 1;
  state.logicInputs.push({ name: `input_${next}`, type: "string" });
  renderLogicBuilder();
}

function handleLogicBlockEvent(event) {
  const card = event.target.closest("[data-block-index]");
  if (!card) return;
  const index = Number(card.dataset.blockIndex);
  const field = event.target.dataset.blockField;
  if (!field || !state.logicBlocks[index]) return;
  if (field === "type") {
    const previousOutput = state.logicBlocks[index].output || state.logicBlocks[index].key;
    state.logicBlocks[index] = defaultLogicBlock(event.target.value);
    if (previousOutput && state.logicBlocks[index].output) state.logicBlocks[index].output = previousOutput;
    renderLogicBuilder();
    return;
  }
  state.logicBlocks[index][field] = event.target.value;
  if (field === "output" || field === "key") renderLogicOutputSelect();
}

function handleLogicBlockClick(event) {
  const removeIndex = event.target.dataset.removeBlock;
  if (removeIndex === undefined) return;
  state.logicBlocks.splice(Number(removeIndex), 1);
  if (!state.logicBlocks.length) state.logicBlocks.push(defaultLogicBlock("llm"));
  renderLogicBuilder();
}

function addLogicBlock() {
  state.logicBlocks.push(defaultLogicBlock(selectedValue("blockTypeSelect") || "llm"));
  renderLogicBuilder();
}

function setToolTab(tabName) {
  state.activeToolTab = tabName;
  document.querySelectorAll("[data-tool-tab]").forEach((button) => {
    button.classList.toggle("active", button.dataset.toolTab === tabName);
  });
  document.querySelectorAll("[data-tool-panel]").forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.toolPanel === tabName);
  });
}

function setRunTab(tabName) {
  state.activeRunTab = tabName;
  document.querySelectorAll("[data-run-tab]").forEach((button) => {
    button.classList.toggle("active", button.dataset.runTab === tabName);
  });
  document.querySelectorAll("[data-run-panel]").forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.runPanel === tabName);
  });
}

function blockValue(value) {
  if (!value) return "";
  return String(value).startsWith("$") ? String(value) : `$${value}`;
}

function buildLogicBlock(block) {
  if (block.type === "llm") {
    return {
      type: "llm",
      mode: block.mode || "summarize",
      prompt: block.prompt || "$prompt",
      output: block.output || "llm_result",
      tools: {
        object_type_id: block.object_type_id || null,
        action_type_id: block.action_type_id || null,
        function_id: block.function_id || null
      }
    };
  }
  if (block.type === "object_query") {
    return {
      type: "object_query",
      object_type_id: block.object_type_id,
      filters: parseJsonValue(block.filters, {}, "Object query filters"),
      limit: Number(block.limit || 20),
      output: block.output || "objects"
    };
  }
  if (block.type === "object_aggregate") {
    return {
      type: "object_aggregate",
      object_type_id: block.object_type_id,
      filters: parseJsonValue(block.filters, {}, "Aggregate filters"),
      op: block.op || "count",
      field: block.field || null,
      output: block.output || "aggregate"
    };
  }
  if (block.type === "propose_action" || block.type === "apply_action") {
    return {
      type: block.type,
      action_type_id: block.action_type_id,
      parameters: parseJsonValue(block.parameters, {}, "Action parameters"),
      output: block.output || "action_result",
      actor: "workspace"
    };
  }
  if (block.type === "pipeline_suggest") {
    return {
      type: "pipeline_suggest",
      prompt: block.prompt || "$prompt",
      sample_fields: String(block.sample_fields || "").split(",").map((item) => item.trim()).filter(Boolean),
      output: block.output || "pipeline"
    };
  }
  if (block.type === "document_extract") {
    return {
      type: "document_extract",
      text: blockValue(block.text || "prompt"),
      extraction_schema: parseJsonValue(block.schema, {}, "Extraction schema"),
      output: block.output || "document"
    };
  }
  if (block.type === "assist") {
    return {
      type: "assist",
      prompt: block.prompt || "$prompt",
      application_context: block.application_context || "workspace",
      output: block.output || "assist"
    };
  }
  if (block.type === "conditional") {
    return {
      type: "conditional",
      condition: {
        left: blockValue(block.left || firstVariable()),
        op: block.op || "truthy",
        right: block.right || null
      },
      then: [{ type: "set_output", key: block.then_key || "branch", value: block.then_value || "matched" }],
      else: [{ type: "set_output", key: block.then_key || "branch", value: block.else_value || "fallback" }]
    };
  }
  if (block.type === "for_each") {
    return {
      type: "for_each",
      items: blockValue(block.items || firstVariable()),
      item_var: block.item_var || "item",
      blocks: [{ type: "set_output", key: block.output_key || "last_item", value: blockValue(block.value || "item") }]
    };
  }
  return {
    type: "set_output",
    key: block.key || "result",
    value: blockValue(block.value || firstVariable())
  };
}

function buildLogicPayload() {
  const timestamp = Date.now();
  const branch = selectedValue("logicBranchSelect") || "main";
  const inputSchema = {};
  for (const input of state.logicInputs) {
    if (input.name) inputSchema[input.name] = { type: input.type || "string" };
  }
  return {
    id: `workspace_logic_${branch}_${timestamp}`,
    display_name: `Workspace Logic ${new Date(timestamp).toLocaleTimeString()}`,
    description: "Generated from the local AIP Logic Builder workspace.",
    blocks: state.logicBlocks.map(buildLogicBlock),
    input_schema: inputSchema,
    output_schema: {
      type: selectedValue("logicOutputType") || "json",
      variable: selectedValue("logicOutputVariable") || "result"
    },
    approval_required: true
  };
}

async function saveLogicFromBuilder() {
  const payload = buildLogicPayload();
  const saved = await api("/logic-functions", {
    method: "POST",
    body: JSON.stringify(payload)
  });
  state.lastLogicId = saved.id;
  await refreshLogicCatalogs();
  showToast("Logic function saved");
  return saved;
}

async function saveLogicBuilder() {
  try {
    const saved = await saveLogicFromBuilder();
    el("logicRunResult").textContent = compactJson({ saved: saved.id, blocks: saved.blocks.length });
    setRunTab("run");
  } catch (error) {
    showToast(error.message);
  }
}

async function runLogicBuilder() {
  try {
    const saved = await saveLogicFromBuilder();
    const inputs = parseJsonValue(el("logicRunInputs").value, {}, "Run inputs");
    const run = await api(`/logic-functions/${encodeURIComponent(saved.id)}/run`, {
      method: "POST",
      body: JSON.stringify({ inputs, actor: "workspace" })
    });
    el("logicRunResult").textContent = compactJson({
      status: run.status,
      outputs: run.outputs,
      proposed_actions: run.proposed_actions
    });
    el("logicDebugger").textContent = compactJson(run.trace);
    setRunTab("run");
    showToast(`Logic run ${run.status}`);
    await refreshLogicCatalogs();
  } catch (error) {
    showToast(error.message);
    el("logicRunResult").textContent = error.message;
  }
}

function loadSelectedLogicFunction() {
  const logicId = selectedValue("logicFunctionSelect");
  const logic = state.catalogs.logicFunctions.find((item) => item.id === logicId);
  if (!logic) return;
  const inputSchema = logic.input_schema || {};
  state.logicInputs = Object.keys(inputSchema).map((name) => ({ name, type: inputSchema[name]?.type || "string" }));
  if (!state.logicInputs.length) state.logicInputs = [{ name: "prompt", type: "string" }];
  state.logicBlocks = (logic.blocks || []).map((block) => normalizeLogicBlock(block));
  if (!state.logicBlocks.length) state.logicBlocks = [defaultLogicBlock("llm")];
  state.lastLogicId = logic.id;
  renderLogicBuilder();
}

function normalizeLogicBlock(block) {
  if (block.type === "object_query") {
    return { ...defaultLogicBlock("object_query"), ...block, filters: compactJson(block.filters || {}) };
  }
  if (block.type === "object_aggregate") {
    return { ...defaultLogicBlock("object_aggregate"), ...block, filters: compactJson(block.filters || {}) };
  }
  if (block.type === "propose_action" || block.type === "apply_action") {
    return { ...defaultLogicBlock(block.type), ...block, parameters: compactJson(block.parameters || {}) };
  }
  if (block.type === "document_extract") {
    return { ...defaultLogicBlock("document_extract"), ...block, text: String(block.text || "").replace(/^\$/, ""), schema: compactJson(block.extraction_schema || {}) };
  }
  if (block.type === "set_output") {
    return { type: "set_output", key: block.key || "result", value: String(block.value || "").replace(/^\$/, "") || firstVariable() };
  }
  return { ...defaultLogicBlock(block.type || "llm"), ...block };
}

function bindEvents() {
  el("homeNav").addEventListener("click", () => setView("home"));
  el("filesNav").addEventListener("click", () => setView("files"));
  el("ontologyNav").addEventListener("click", () => setView("ontology"));
  el("applicationsNav").addEventListener("click", () => setView("applications"));
  el("searchNav").addEventListener("click", openGlobalSearch);
  el("openSearchBtn").addEventListener("click", openGlobalSearch);
  el("homeSearchBtn").addEventListener("click", openGlobalSearch);
  el("assistLauncherBtn").addEventListener("click", () => setView("aip"));
  el("homeAipBtn").addEventListener("click", () => setView("aip"));
  el("homeAppsBtn").addEventListener("click", () => setView("applications"));
  el("viewAllAppsBtn").addEventListener("click", () => setView("applications"));
  el("homeBootstrapBtn").addEventListener("click", bootstrapDomain);
  el("collapseNavBtn").addEventListener("click", () => document.body.classList.toggle("nav-collapsed"));
  el("filesSearchInput").addEventListener("input", renderFilesPage);
  el("objectTypeCatalogFilter").addEventListener("input", renderOntologyPage);
  el("appSearchInput").addEventListener("input", renderApplicationsPage);
  el("globalSearchInput").addEventListener("input", (event) => {
    state.lastSearchQuery = event.target.value;
    renderGlobalSearchResults();
  });
  el("clearSearchBtn").addEventListener("click", () => {
    el("globalSearchInput").value = "";
    state.lastSearchQuery = "";
    renderGlobalSearchResults();
  });
  el("closeSearchBtn").addEventListener("click", closeGlobalSearch);
  el("globalSearchOverlay").addEventListener("click", (event) => {
    if (event.target.id === "globalSearchOverlay") closeGlobalSearch();
  });
  document.addEventListener("click", (event) => {
    const appButton = event.target.closest("[data-open-app]");
    if (appButton) {
      const appId = appButton.dataset.openApp;
      state.selectedApplication = appId;
      if (appButton.dataset.selectApp !== undefined && state.view === "applications") {
        renderApplicationsPage();
      } else {
        openApplication(appId);
      }
      return;
    }
    const viewButton = event.target.closest("[data-open-view]");
    if (viewButton) {
      closeGlobalSearch();
      setView(viewButton.dataset.openView);
      return;
    }
    const resourceRow = event.target.closest("[data-resource-view]");
    if (resourceRow) setView(resourceRow.dataset.resourceView);
  });
  document.querySelectorAll("[data-app-category]").forEach((button) => {
    button.addEventListener("click", () => {
      state.activeAppCategory = button.dataset.appCategory;
      renderApplicationsPage();
    });
  });
  document.addEventListener("keydown", (event) => {
    const key = event.key.toLowerCase();
    if ((event.ctrlKey || event.metaKey) && key === "j") {
      event.preventDefault();
      openGlobalSearch();
    }
    if (key === "escape") closeGlobalSearch();
  });
  el("mapNav").addEventListener("click", () => setView("map"));
  el("aipNav").addEventListener("click", () => setView("aip"));
  el("workshopNav").addEventListener("click", () => setView("workshop"));
  el("object-explorerNav").addEventListener("click", () => setView("object-explorer"));
  el("pipelineNav").addEventListener("click", () => setView("pipeline"));
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
  el("refreshLogicBtn").addEventListener("click", refreshAipLists);
  el("addInputBtn").addEventListener("click", addLogicInput);
  el("logicInputs").addEventListener("input", handleLogicInputEvent);
  el("logicInputs").addEventListener("change", handleLogicInputEvent);
  el("logicInputs").addEventListener("click", handleLogicInputClick);
  el("logicFunctionSelect").addEventListener("change", loadSelectedLogicFunction);
  el("logicBlocks").addEventListener("input", handleLogicBlockEvent);
  el("logicBlocks").addEventListener("change", handleLogicBlockEvent);
  el("logicBlocks").addEventListener("click", handleLogicBlockClick);
  el("addBlockBtn").addEventListener("click", addLogicBlock);
  el("saveLogicBtn").addEventListener("click", saveLogicBuilder);
  el("runLogicBtn").addEventListener("click", runLogicBuilder);
  el("logicOutputType").addEventListener("change", renderLogicOutputSelect);
  document.querySelectorAll("[data-tool-tab]").forEach((button) => {
    button.addEventListener("click", () => setToolTab(button.dataset.toolTab));
  });
  document.querySelectorAll("[data-run-tab]").forEach((button) => {
    button.addEventListener("click", () => setRunTab(button.dataset.runTab));
  });
  el("loadContextBtn").addEventListener("click", loadContextObjects);
  el("askAssistBtn").addEventListener("click", askAssist);
  el("runAgentBtn").addEventListener("click", runAgent);
  el("generatePipelineBtn").addEventListener("click", generatePipeline);
  el("loadApprovalsBtn").addEventListener("click", loadApprovals);
  el("runEvalBtn").addEventListener("click", runEval);
  el("refreshWorkshopBtn").addEventListener("click", refreshWorkshop);
  el("newWorkshopBtn").addEventListener("click", () => {
    state.workshop.selectedId = "";
    state.workshop.draft = defaultWorkshopDraft();
    state.workshop.selectedWidgetIndex = 0;
    state.workshop.render = null;
    renderWorkshopBuilder();
  });
  el("workshopModuleSelect").addEventListener("change", async (event) => {
    state.workshop.selectedId = event.target.value;
    state.workshop.render = null;
    await refreshWorkshop();
  });
  document.querySelectorAll("[data-workshop-panel]").forEach((button) => {
    button.addEventListener("click", () => {
      state.workshop.activePanel = button.dataset.workshopPanel;
      renderWorkshopPanels();
    });
  });
  el("workshopWidgetPicker").addEventListener("click", (event) => {
    const button = event.target.closest("[data-add-workshop-widget]");
    if (button) addWorkshopWidget(button.dataset.addWorkshopWidget);
  });
  el("workshopCanvas").addEventListener("click", (event) => {
    const card = event.target.closest("[data-workshop-widget-index]");
    if (!card) return;
    state.workshop.selectedWidgetIndex = Number(card.dataset.workshopWidgetIndex);
    renderWorkshopBuilder();
  });
  el("workshopConfig").addEventListener("input", handleWorkshopWidgetConfig);
  el("workshopConfig").addEventListener("change", handleWorkshopWidgetConfig);
  el("workshopConfig").addEventListener("click", (event) => {
    const removeIndex = event.target.dataset.removeWorkshopWidget;
    if (removeIndex === undefined) return;
    state.workshop.draft.widgets.splice(Number(removeIndex), 1);
    state.workshop.selectedWidgetIndex = 0;
    renderWorkshopBuilder();
  });
  el("workshopVariables").addEventListener("input", handleWorkshopVariableEvent);
  el("workshopVariables").addEventListener("change", handleWorkshopVariableEvent);
  el("workshopVariables").addEventListener("click", (event) => {
    const name = event.target.dataset.removeWorkshopVariable;
    if (!name) return;
    delete state.workshop.draft.variables[name];
    renderWorkshopBuilder();
  });
  el("addWorkshopVariableBtn").addEventListener("click", () => {
    const key = `variable_${Object.keys(state.workshop.draft.variables || {}).length + 1}`;
    state.workshop.draft.variables[key] = { definition_type: "static", value: "" };
    renderWorkshopBuilder();
  });
  el("workshopEvents").addEventListener("input", handleWorkshopEventChange);
  el("workshopEvents").addEventListener("change", handleWorkshopEventChange);
  el("workshopEvents").addEventListener("click", (event) => {
    const index = event.target.dataset.removeWorkshopEvent;
    if (index === undefined) return;
    state.workshop.draft.layout.events.splice(Number(index), 1);
    renderWorkshopBuilder();
  });
  el("addWorkshopEventBtn").addEventListener("click", () => {
    state.workshop.draft.layout.events = state.workshop.draft.layout.events || [];
    state.workshop.draft.layout.events.push({ type: "set_variable", target: "selected", value: true });
    renderWorkshopBuilder();
  });
  el("previewWorkshopBtn").addEventListener("click", () => {
    state.workshop.preview = !state.workshop.preview;
    renderWorkshopCanvas();
  });
  el("renderWorkshopBtn").addEventListener("click", () => renderWorkshopLive().catch((error) => showToast(error.message)));
  el("saveWorkshopBtn").addEventListener("click", () => saveWorkshop().catch((error) => showToast(error.message)));
  el("publishWorkshopBtn").addEventListener("click", () => publishWorkshop().catch((error) => showToast(error.message)));
  el("workshopVersions").addEventListener("click", (event) => {
    const versionId = event.target.closest("[data-restore-workshop-version]")?.dataset.restoreWorkshopVersion;
    if (versionId) restoreWorkshopVersion(versionId).catch((error) => showToast(error.message));
  });
  el("refreshObjectExplorerBtn").addEventListener("click", refreshObjectExplorer);
  el("explorerObjectTypeSelect").addEventListener("change", () => {
    state.objectExplorer.selectedObjectId = "";
    state.objectExplorer.selectedIds = [];
    runObjectExplorerQuery();
  });
  el("explorerSearchInput").addEventListener("input", () => runObjectExplorerQuery(false));
  el("runExplorerQueryBtn").addEventListener("click", () => runObjectExplorerQuery());
  el("saveExplorationBtn").addEventListener("click", () => saveExploration().catch((error) => showToast(error.message)));
  el("savedExplorations").addEventListener("click", (event) => {
    const explorationId = event.target.closest("[data-load-exploration]")?.dataset.loadExploration;
    if (explorationId) loadExploration(explorationId).catch((error) => showToast(error.message));
  });
  el("explorerResults").addEventListener("click", (event) => {
    const checkbox = event.target.closest("[data-explorer-select-id]");
    if (checkbox) {
      const id = checkbox.dataset.explorerSelectId;
      state.objectExplorer.selectedIds = checkbox.checked
        ? Array.from(new Set([...state.objectExplorer.selectedIds, id]))
        : state.objectExplorer.selectedIds.filter((item) => item !== id);
      return;
    }
    const row = event.target.closest("[data-explorer-object-id]");
    if (row) selectExplorerObject(row.dataset.explorerObjectId);
  });
  el("explorerFacetRail").addEventListener("click", handleExplorerFacetClick);
  el("explorerCharts").addEventListener("click", handleExplorerFacetClick);
  el("bulkActionBtn").addEventListener("click", () => openBulkAction());
  el("explorerActionList").addEventListener("click", (event) => {
    const actionId = event.target.closest("[data-open-bulk-action]")?.dataset.openBulkAction;
    if (actionId) openBulkAction(actionId);
  });
  el("closeBulkActionBtn").addEventListener("click", () => el("objectBulkModal").classList.add("hidden"));
  el("executeBulkActionBtn").addEventListener("click", () => executeBulkAction().catch((error) => showToast(error.message)));
  el("openExplorerObjectBtn").addEventListener("click", () => {
    if (state.objectExplorer.selectedObjectId) showToast(`Object view loaded for ${state.objectExplorer.selectedObjectId}`);
    else showToast("Select an object first");
  });
  el("refreshPipelineBtn").addEventListener("click", refreshPipelineBuilder);
  el("newPipelineGraphBtn").addEventListener("click", () => {
    state.pipeline.selectedId = "";
    state.pipeline.draft = defaultPipelineDraft();
    state.pipeline.activeNodeId = state.pipeline.draft.nodes[0]?.id || "";
    state.pipeline.preview = null;
    state.pipeline.validation = null;
    renderPipelineBuilder();
  });
  el("pipelineGraphSelect").addEventListener("change", async (event) => {
    state.pipeline.selectedId = event.target.value;
    state.pipeline.preview = null;
    state.pipeline.validation = null;
    await refreshPipelineBuilder();
  });
  el("pipelineNodeLibrary").addEventListener("click", (event) => {
    const type = event.target.closest("[data-add-pipeline-node]")?.dataset.addPipelineNode;
    if (type) addPipelineNode(type);
  });
  el("pipelineCanvas").addEventListener("click", (event) => {
    const nodeId = event.target.closest("[data-pipeline-node-id]")?.dataset.pipelineNodeId;
    if (!nodeId) return;
    state.pipeline.activeNodeId = nodeId;
    renderPipelineBuilder();
  });
  el("pipelineConfig").addEventListener("input", handlePipelineNodeChange);
  el("pipelineConfig").addEventListener("change", handlePipelineNodeChange);
  el("pipelineConfig").addEventListener("click", (event) => {
    const nodeId = event.target.dataset.removePipelineNode;
    if (!nodeId) return;
    state.pipeline.draft.nodes = state.pipeline.draft.nodes.filter((node) => node.id !== nodeId);
    state.pipeline.draft.edges = state.pipeline.draft.edges.filter((edge) => edge.source !== nodeId && edge.target !== nodeId);
    state.pipeline.activeNodeId = state.pipeline.draft.nodes[0]?.id || "";
    renderPipelineBuilder();
  });
  document.querySelectorAll("[data-pipeline-panel]").forEach((button) => {
    button.addEventListener("click", () => {
      state.pipeline.activePanel = button.dataset.pipelinePanel;
      renderPipelineConfig();
    });
  });
  el("savePipelineGraphBtn").addEventListener("click", () => savePipelineGraph().catch((error) => showToast(error.message)));
  el("validatePipelineGraphBtn").addEventListener("click", () => validatePipelineGraph().catch((error) => showToast(error.message)));
  el("previewPipelineGraphBtn").addEventListener("click", () => previewPipelineGraph().catch((error) => showToast(error.message)));
  el("deliverPipelineGraphBtn").addEventListener("click", () => deliverPipelineGraph().catch((error) => showToast(error.message)));
  window.addEventListener("resize", () => {
    if (state.map) {
      state.map.invalidateSize();
      updateViewportMetric();
    } else {
      resizeCanvas();
      drawMap();
    }
  });
  window.addEventListener("popstate", () => setView(routeViewFromPath(location.pathname), false));
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
