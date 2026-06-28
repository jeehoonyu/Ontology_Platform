const WORKSPACE_VIEWS = ["home", "files", "ontology", "applications", "search", "graph", "command-center", "map", "aip", "workshop", "object-explorer", "pipeline", "decision", "models", "ops", "investigations"];

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
  featureRiskById: {},
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
  classicPipelines: [],
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
    activeActionId: "",
    riskById: {}
  },
  pipeline: {
    graphs: [],
    selectedId: "",
    activeNodeId: "",
    activeEdgeId: "",
    activePanel: "build",
    canvasMode: "select",
    connectingFrom: "",
    nodeTypes: [],
    draft: null,
    preview: null,
    validation: null,
    delivery: null
  },
  ontologyGenerator: {
    drafts: [],
    selectedDraftId: "",
    selectedAssetId: "",
    includeActions: false,
    createPipelineGraph: true,
    result: null
  },
  modelops: {
    activeTab: "objectives",
    summary: null,
    objectives: [],
    submissions: [],
    checks: [],
    checkResults: [],
    eligibility: null,
    releases: [],
    deployments: [],
    monitors: [],
    monitorRuns: [],
    predictionLogs: [],
    selectedObjectiveId: "",
    selectedSubmissionId: "",
    selectedDeploymentId: "",
    selectedMonitorId: "",
    inferenceResult: null
  },
  decision: {
    activeTab: "risk",
    rules: [],
    scorecards: [],
    evaluation: null,
    explanation: null,
    timeline: null,
    entityJob: null,
    candidates: [],
    scenario: null,
    agentRun: null
  },
  ops: {
    activeTab: "command",
    summary: null,
    events: [],
    alertRules: [],
    alerts: [],
    incidents: [],
    runbooks: [],
    inbox: [],
    approvals: [],
    reliability: null,
    dataContracts: [],
    backfills: [],
    selectedIncidentId: "",
    selectedRunbookId: "",
    selectedContractId: "",
    output: null
  },
  investigations: {
    activeTab: "board",
    list: [],
    selectedId: "",
    detail: null,
    graph: null,
    timeline: null,
    output: null
  },
  platformSearch: {
    query: "",
    kind: "",
    results: [],
    commands: []
  },
  platformGraph: {
    overview: null
  },
  commandCenter: {
    selectedAssetId: "asset_pump_4",
    summary: null,
    triage: null,
    validation: null,
    actionResult: null
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
  { type: "explain_object", label: "Explain Object" },
  { type: "score_risk", label: "Score Risk" },
  { type: "run_scenario", label: "Run Scenario" },
  { type: "create_incident", label: "Create Incident" },
  { type: "evaluate_alert_rules", label: "Evaluate Alert Rules" },
  { type: "run_runbook", label: "Run Runbook" },
  { type: "run_data_contract", label: "Run Data Contract" },
  { type: "analyze_lineage_impact", label: "Analyze Lineage Impact" },
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
  { id: "command-center", name: "Asset Reliability Command Center", category: "operations", icon: "CC", color: "blue", view: "command-center", description: "Run one full raw-data to operational decision workflow with risk, checks, agent recommendation, approval, incident, and report." },
  { id: "search", name: "Global Search", category: "operations", icon: "S", color: "blue", view: "search", description: "Search objects, datasets, pipelines, events, incidents, models, investigations, and commands." },
  { id: "graph", name: "Platform Graph", category: "ontology", icon: "G", color: "teal", view: "graph", description: "Inspect how datasets, pipelines, ontology objects, incidents, and links connect." },
  { id: "object-explorer", name: "Object Explorer", category: "ontology", icon: "O", color: "teal", view: "object-explorer", description: "Explore object types, chart filters, inspect objects, and save explorations." },
  { id: "ontology", name: "Ontology Manager", category: "ontology", icon: "OM", color: "teal", view: "ontology", description: "Search object types, inspect ontology usage, and discover object sets." },
  { id: "decision", name: "Decision Intelligence", category: "operations", icon: "D", color: "blue", view: "decision", description: "Explain risk, inspect object timelines, resolve entities, simulate scenarios, and review agent plans." },
  { id: "ops", name: "Ops Control Plane", category: "operations", icon: "OC", color: "slate", view: "ops", description: "Monitor operational events, alerts, incidents, approvals, runbooks, and reliability signals." },
  { id: "investigations", name: "Investigations", category: "operations", icon: "IG", color: "blue", view: "investigations", description: "Build case boards with evidence, hypotheses, entity graphs, timelines, and reports." },
  { id: "aip", name: "AIP Logic", category: "operations", icon: "AI", color: "blue", view: "aip", description: "Build, test, debug, and run LLM-backed ontology logic functions." },
  { id: "map", name: "Map", category: "operations", icon: "M", color: "teal", view: "map", description: "Analyze geospatial and MGRS-enabled operational data." },
  { id: "workshop", name: "Workshop", category: "operations", icon: "W", color: "slate", view: "workshop", description: "Compose operational dashboards from objects, filters, widgets, and actions." },
  { id: "pipeline", name: "Pipeline Builder", category: "data", icon: "P", color: "teal", view: "pipeline", description: "Design DAG pipelines, preview transforms, deliver datasets, and inspect lineage." },
  { id: "models", name: "ModelOps", category: "data", icon: "MO", color: "blue", view: "models", description: "Manage model objectives, evaluation gates, releases, deployments, drift monitoring, and inference logs." },
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
  { type: "input_dataset", label: "Input Dataset", category: "input" },
  { type: "filter", label: "Filter", category: "transform" },
  { type: "project", label: "Project / Select", category: "transform" },
  { type: "rename", label: "Rename", category: "transform" },
  { type: "join", label: "Join", category: "transform" },
  { type: "union", label: "Union", category: "transform" },
  { type: "aggregate", label: "Aggregate", category: "transform" },
  { type: "sort", label: "Sort", category: "transform" },
  { type: "limit", label: "Limit", category: "transform" },
  { type: "unique_id", label: "Unique ID", category: "transform" },
  { type: "llm_assist", label: "LLM Assist", category: "ai" },
  { type: "ontology_output", label: "Ontology Output", category: "output" },
  { type: "dataset_output", label: "Dataset Output", category: "output" }
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
  } else if (view === "ontology") {
    refreshOntologyWorkspace();
  } else if (view === "workshop") {
    refreshWorkshop();
  } else if (view === "object-explorer") {
    refreshObjectExplorer();
  } else if (view === "pipeline") {
    refreshPipelineBuilder();
  } else if (view === "models") {
    refreshModelOpsWorkspace();
  } else if (view === "decision") {
    refreshDecisionWorkspace();
  } else if (view === "ops") {
    refreshOpsWorkspace();
  } else if (view === "investigations") {
    refreshInvestigationsWorkspace();
  } else if (view === "search") {
    refreshSearchWorkspace();
  } else if (view === "graph") {
    refreshGraphWorkspace();
  } else if (view === "command-center") {
    refreshCommandCenterWorkspace();
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
    { name: "Asset Reliability Command Center", type: "Application", path: "/workspace/command-center", role: "Owner", updated: "Current session", view: "command-center" },
    { name: "Global Search", type: "Application", path: "/workspace/search", role: "Owner", updated: "Current session", view: "search" },
    { name: "Platform Graph", type: "Application", path: "/workspace/graph", role: "Owner", updated: "Current session", view: "graph" },
    { name: "AIP Logic Workspace", type: "Application", path: "/workspace/aip", role: "Owner", updated: "Current session", view: "aip" },
    { name: "Map Workspace", type: "Application", path: "/workspace/map", role: "Owner", updated: "Current session", view: "map" },
    { name: "Object Explorer Workspace", type: "Application", path: "/workspace/object-explorer", role: "Owner", updated: "Current session", view: "object-explorer" },
    { name: "Decision Intelligence Workspace", type: "Application", path: "/workspace/decision", role: "Owner", updated: "Current session", view: "decision" },
    { name: "ModelOps Workspace", type: "Application", path: "/workspace/models", role: "Owner", updated: "Current session", view: "models" },
    { name: "Ops Control Plane", type: "Application", path: "/workspace/ops", role: "Owner", updated: "Current session", view: "ops" },
    { name: "Investigation Graph Workspace", type: "Application", path: "/workspace/investigations", role: "Owner", updated: "Current session", view: "investigations" },
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
  if (view === "search") renderSearchWorkspace();
  if (view === "graph") renderGraphWorkspace();
  if (view === "command-center") renderCommandCenterWorkspace();
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

async function refreshOntologyWorkspace() {
  await Promise.allSettled([refreshLogicCatalogs(), loadDataAssets(), loadOntologyGeneratorDrafts()]);
  if (!state.ontologyGenerator.selectedAssetId && state.datasets.length) {
    state.ontologyGenerator.selectedAssetId = state.datasets[0].id;
  }
  renderOntologyPage();
}

async function loadOntologyGeneratorDrafts() {
  try {
    state.ontologyGenerator.drafts = await api("/ontology-generator/drafts");
    if (!state.ontologyGenerator.selectedDraftId && state.ontologyGenerator.drafts.length) {
      state.ontologyGenerator.selectedDraftId = state.ontologyGenerator.drafts[0].id;
    }
  } catch (_) {
    state.ontologyGenerator.drafts = [];
  }
}

function activeOntologyDraft() {
  return (state.ontologyGenerator.drafts || []).find((draft) => draft.id === state.ontologyGenerator.selectedDraftId) || state.ontologyGenerator.drafts?.[0] || null;
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
  renderOntologyGenerator();
}

function renderOntologyGenerator() {
  if (!el("ontologyGeneratorAssetSelect")) return;
  fillSelect(
    el("ontologyGeneratorAssetSelect"),
    state.datasets.map((asset) => ({ value: asset.id, label: asset.display_name ? `${asset.display_name} (${asset.id})` : asset.id })),
    state.ontologyGenerator.selectedAssetId || state.datasets[0]?.id || "",
    "Choose dataset"
  );
  const drafts = state.ontologyGenerator.drafts || [];
  fillSelect(
    el("ontologyDraftSelect"),
    drafts.map((draft) => ({ value: draft.id, label: `${draft.draft?.display_name || draft.object_type_id} - ${draft.status}` })),
    state.ontologyGenerator.selectedDraftId,
    "No generator draft"
  );
  el("ontologyGeneratorActionsToggle").checked = !!state.ontologyGenerator.includeActions;
  el("ontologyGeneratorPipelineToggle").checked = state.ontologyGenerator.createPipelineGraph !== false;
  const draftRow = activeOntologyDraft();
  if (!draftRow) {
    el("ontologyGeneratorValidation").innerHTML = '<div class="empty-state compact-empty">Create a draft from a dataset to review inferred ontology mappings.</div>';
    el("ontologyGeneratorProperties").innerHTML = '<div class="empty-state compact-empty">No properties inferred yet</div>';
    el("ontologyGeneratorPipeline").textContent = "";
    el("ontologyGeneratorResult").textContent = state.ontologyGenerator.result ? compactJson(state.ontologyGenerator.result) : "";
    return;
  }
  const draft = draftRow.draft || {};
  if (!el("ontologyGeneratorDisplayNameInput").value) el("ontologyGeneratorDisplayNameInput").value = draft.display_name || "";
  if (!el("ontologyGeneratorObjectTypeInput").value) el("ontologyGeneratorObjectTypeInput").value = draft.object_type_id || "";
  const validation = draftRow.validation || {};
  const statusClass = validation.status === "FAIL" ? "red" : validation.status === "WARN" ? "amber" : "green";
  const issueRows = [...(validation.errors || []), ...(validation.warnings || [])];
  el("ontologyGeneratorValidation").innerHTML = `
    <div class="generator-status">
      <span class="pill ${statusClass}">${escapeHtml(validation.status || draftRow.status || "DRAFT")}</span>
      <strong>${escapeHtml(draft.display_name || draft.object_type_id || draftRow.id)}</strong>
      <span>${escapeHtml(validation.summary?.properties ?? 0)} properties - ${escapeHtml(validation.summary?.records ?? 0)} records</span>
    </div>
    ${issueRows.map((issue) => `<div class="list-item"><strong>${escapeHtml(issue.code || "ISSUE")}</strong><span>${escapeHtml(issue.message || "")}</span></div>`).join("") || '<div class="list-item"><strong>No blocking issues</strong><span>Draft is ready to apply locally.</span></div>'}
  `;
  const properties = draft.properties || [];
  el("ontologyGeneratorProperties").innerHTML = `
    <table>
      <thead><tr><th>Include</th><th>Source field</th><th>Property API name</th><th>Base type</th><th>Status</th><th>Required</th><th>Sample</th></tr></thead>
      <tbody>
        ${properties.map((prop, index) => `
          <tr>
            <td><input type="checkbox" ${prop.include === false ? "" : "checked"} disabled /></td>
            <td><strong>${escapeHtml(prop.source_field || "")}</strong>${prop.generated ? '<br><span>generated</span>' : ""}</td>
            <td>${escapeHtml(prop.api_name || prop.property_name || "")}</td>
            <td>${escapeHtml(prop.base_type || "string")}</td>
            <td>${escapeHtml(prop.status || "active")}</td>
            <td>${prop.required ? "yes" : "no"}</td>
            <td>${escapeHtml((prop.sample_values || []).slice(0, 2).join(", "))}</td>
          </tr>
        `).join("") || '<tr><td colspan="7">No properties inferred</td></tr>'}
      </tbody>
    </table>
  `;
  el("ontologyGeneratorPipeline").textContent = compactJson(draft.pipeline_graph || {});
  el("ontologyGeneratorResult").textContent = state.ontologyGenerator.result ? compactJson(state.ontologyGenerator.result) : "";
}

async function createOntologyGeneratorDraft() {
  const assetId = el("ontologyGeneratorAssetSelect").value;
  if (!assetId) throw new Error("Choose a dataset");
  const payload = {
    asset_id: assetId,
    display_name: el("ontologyGeneratorDisplayNameInput").value || null,
    object_type_id: el("ontologyGeneratorObjectTypeInput").value || null,
    include_actions: el("ontologyGeneratorActionsToggle").checked,
    create_pipeline_graph: el("ontologyGeneratorPipelineToggle").checked
  };
  const draft = await api("/ontology-generator/drafts", { method: "POST", body: JSON.stringify(payload) });
  state.ontologyGenerator.selectedDraftId = draft.id;
  state.ontologyGenerator.selectedAssetId = draft.asset_id;
  state.ontologyGenerator.result = { status: "DRAFT_CREATED", draft_id: draft.id };
  await loadOntologyGeneratorDrafts();
  renderOntologyPage();
  showToast("Ontology generator draft created");
}

async function validateOntologyGeneratorDraft() {
  const draftId = state.ontologyGenerator.selectedDraftId || el("ontologyDraftSelect").value;
  if (!draftId) throw new Error("Create or select a draft");
  state.ontologyGenerator.result = await api(`/ontology-generator/drafts/${encodeURIComponent(draftId)}/validate`, { method: "POST" });
  await loadOntologyGeneratorDrafts();
  renderOntologyPage();
  showToast(state.ontologyGenerator.result.status || "Validated");
}

async function applyOntologyGeneratorDraft() {
  const draftId = state.ontologyGenerator.selectedDraftId || el("ontologyDraftSelect").value;
  if (!draftId) throw new Error("Create or select a draft");
  state.ontologyGenerator.result = await api(`/ontology-generator/drafts/${encodeURIComponent(draftId)}/apply`, {
    method: "POST",
    body: JSON.stringify({
      actor: "workspace",
      create_actions: el("ontologyGeneratorActionsToggle").checked,
      create_pipeline_graph: el("ontologyGeneratorPipelineToggle").checked
    })
  });
  await Promise.allSettled([refreshLogicCatalogs(), loadOntologyGeneratorDrafts(), refreshPipelineBuilder()]);
  renderOntologyPage();
  showToast("Ontology resources applied");
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

async function refreshSearchWorkspace() {
  const input = el("platformSearchInput");
  const kind = selectedValue("platformSearchKind");
  state.platformSearch.query = input ? input.value : state.platformSearch.query;
  state.platformSearch.kind = kind;
  try {
    const [results, commands] = await Promise.all([
      api("/search/query", {
        method: "POST",
        body: JSON.stringify({
          q: state.platformSearch.query || "",
          kinds: kind ? [kind] : [],
          limit: 50,
          include_payload: true
        })
      }),
      api("/search/commands")
    ]);
    state.platformSearch.results = results.results || [];
    state.platformSearch.commands = commands.commands || [];
    renderSearchWorkspace();
  } catch (error) {
    showToast(error.message);
  }
}

function renderSearchWorkspace() {
  const input = el("platformSearchInput");
  const kindSelect = el("platformSearchKind");
  if (input && document.activeElement !== input) input.value = state.platformSearch.query || "";
  if (kindSelect) kindSelect.value = state.platformSearch.kind || "";
  const summary = el("platformSearchSummary");
  if (summary) {
    const kinds = new Set((state.platformSearch.results || []).map((row) => row.kind));
    summary.innerHTML = `
      <article><strong>${escapeHtml(String(state.platformSearch.results.length))}</strong><span>matching resources</span></article>
      <article><strong>${escapeHtml(String(kinds.size))}</strong><span>resource kinds</span></article>
      <article><strong>${escapeHtml(String(state.platformSearch.commands.length))}</strong><span>commands</span></article>
    `;
  }
  const results = el("platformSearchResults");
  if (results) {
    const rows = state.platformSearch.results || [];
    results.innerHTML = `
      <table>
        <thead><tr><th>Resource</th><th>Kind</th><th>Route</th><th>Score</th></tr></thead>
        <tbody>
          ${rows.map((row) => `
            <tr>
              <td><strong>${escapeHtml(row.title)}</strong><br><span>${escapeHtml(row.subtitle)}</span></td>
              <td><span class="pill">${escapeHtml(row.kind)}</span></td>
              <td>${escapeHtml(row.url)}</td>
              <td>${escapeHtml(row.score)}</td>
            </tr>
          `).join("") || '<tr><td colspan="4">No matching resources. Bootstrap the sample domain or broaden the filter.</td></tr>'}
        </tbody>
      </table>
    `;
  }
  const commands = el("platformSearchCommands");
  if (commands) {
    commands.innerHTML = (state.platformSearch.commands || []).map((command) => `
      <button class="application-row" type="button" data-open-route="${escapeHtml(command.route)}">
        <span class="app-tile-icon slate">${escapeHtml(command.id.slice(0, 2).toUpperCase())}</span>
        <span><strong>${escapeHtml(command.title)}</strong><span>${escapeHtml(command.category)} - ${escapeHtml(command.route)}</span></span>
      </button>
    `).join("") || '<div class="empty-state compact-empty">No commands available</div>';
  }
}

async function refreshGraphWorkspace() {
  try {
    state.platformGraph.overview = await api("/graph/overview?limit=200");
    renderGraphWorkspace();
  } catch (error) {
    showToast(error.message);
  }
}

function renderGraphWorkspace() {
  const overview = state.platformGraph.overview || { summary: {}, nodes: [], edges: [], node_count: 0, edge_count: 0 };
  const summary = el("platformGraphSummary");
  if (summary) {
    const items = Object.entries(overview.summary || {});
    summary.innerHTML = `
      <article><strong>${escapeHtml(String(overview.node_count || 0))}</strong><span>nodes</span></article>
      <article><strong>${escapeHtml(String(overview.edge_count || 0))}</strong><span>edges</span></article>
      ${items.slice(0, 6).map(([kind, count]) => `<article><strong>${escapeHtml(String(count))}</strong><span>${escapeHtml(kind)}</span></article>`).join("")}
    `;
  }
  const nodes = el("platformGraphNodes");
  if (nodes) {
    nodes.innerHTML = `
      <table>
        <thead><tr><th>Node</th><th>Kind</th><th>Resource</th></tr></thead>
        <tbody>
          ${(overview.nodes || []).slice(0, 80).map((node) => `
            <tr>
              <td><strong>${escapeHtml(node.label)}</strong><br><span>${escapeHtml(node.id)}</span></td>
              <td><span class="pill">${escapeHtml(node.kind)}</span></td>
              <td>${escapeHtml(node.resource_id)}</td>
            </tr>
          `).join("") || '<tr><td colspan="3">No graph nodes yet. Bootstrap data or create ontology resources.</td></tr>'}
        </tbody>
      </table>
    `;
  }
  const edges = el("platformGraphEdges");
  if (edges) {
    edges.innerHTML = `
      <table>
        <thead><tr><th>Source</th><th>Relationship</th><th>Target</th></tr></thead>
        <tbody>
          ${(overview.edges || []).slice(0, 120).map((edge) => `
            <tr>
              <td>${escapeHtml(edge.source)}</td>
              <td><strong>${escapeHtml(edge.label || edge.kind)}</strong></td>
              <td>${escapeHtml(edge.target)}</td>
            </tr>
          `).join("") || '<tr><td colspan="3">No graph edges yet.</td></tr>'}
        </tbody>
      </table>
    `;
  }
}

async function refreshCommandCenterWorkspace() {
  try {
    const assetId = state.commandCenter.selectedAssetId || "asset_pump_4";
    const [summary, validation] = await Promise.all([
      api(`/scenarios/asset-reliability/summary?asset_id=${encodeURIComponent(assetId)}`),
      api("/scenarios/asset-reliability/validation-dashboard")
    ]);
    state.commandCenter.summary = summary;
    state.commandCenter.validation = validation;
    renderCommandCenterWorkspace();
  } catch (error) {
    renderCommandCenterWorkspace();
    showToast(error.message);
  }
}

async function bootstrapCommandCenter() {
  const button = el("bootstrapCommandCenterBtn");
  if (button) button.disabled = true;
  try {
    const result = await api("/scenarios/asset-reliability/bootstrap", {
      method: "POST",
      body: JSON.stringify({ actor: "workspace", run_pipelines: true, run_checks: true })
    });
    state.commandCenter.summary = result.summary;
    state.commandCenter.validation = await api("/scenarios/asset-reliability/validation-dashboard");
    state.commandCenter.triage = null;
    state.commandCenter.actionResult = null;
    renderCommandCenterWorkspace();
    showToast("Asset reliability scenario bootstrapped");
  } catch (error) {
    showToast(error.message);
  } finally {
    if (button) button.disabled = false;
  }
}

async function runCommandCenterTriage() {
  const button = el("runCommandCenterTriageBtn");
  if (button) button.disabled = true;
  try {
    const result = await api("/scenarios/asset-reliability/run-triage", {
      method: "POST",
      body: JSON.stringify({
        actor: "workspace",
        asset_id: state.commandCenter.selectedAssetId || "asset_pump_4",
        work_order_id: "wo_pump_urgent"
      })
    });
    state.commandCenter.triage = result;
    state.commandCenter.summary = result.summary;
    state.commandCenter.validation = await api("/scenarios/asset-reliability/validation-dashboard");
    renderCommandCenterWorkspace();
    showToast("Triage complete; approval required");
  } catch (error) {
    showToast(error.message);
  } finally {
    if (button) button.disabled = false;
  }
}

async function approveCommandCenterAction() {
  const approval = state.commandCenter.triage?.approval || (state.commandCenter.summary?.approvals || []).find((item) => item.action_type_id === "escalate_work_order");
  if (!approval) {
    showToast("No staged escalation approval found");
    return;
  }
  try {
    const decision = await api(`/approvals/${approval.id}/decision`, {
      method: "POST",
      body: JSON.stringify({ actor: "workspace", decision: "APPROVED", reason: "Approved from command center" })
    });
    const execution = await api("/actions/execute", {
      method: "POST",
      body: JSON.stringify({
        action_type_id: approval.action_type_id,
        parameters: approval.parameters,
        idempotency_key: `command-center-${approval.id}`,
        actor: "workspace",
        approval_request_id: approval.id
      })
    });
    state.commandCenter.actionResult = { decision, execution };
    if (state.commandCenter.triage?.approval?.id === decision.id) {
      state.commandCenter.triage.approval = decision;
    }
    await refreshCommandCenterWorkspace();
    showToast("Escalation approved and executed");
  } catch (error) {
    showToast(error.message);
  }
}

function renderCommandCenterWorkspace() {
  const summary = state.commandCenter.summary || {};
  const kpis = summary.kpis || {};
  const metricBox = el("commandCenterKpis");
  if (metricBox) {
    const metrics = [
      ["High-risk assets", kpis.high_risk_assets ?? 0],
      ["Open work orders", kpis.open_work_orders ?? 0],
      ["Data contract", kpis.data_contract_status || "NOT_RUN"],
      ["Model monitor", kpis.model_monitor_status || "NOT_RUN"],
      ["Open approvals", kpis.open_approvals ?? 0],
      ["Open incidents", kpis.open_incidents ?? 0]
    ];
    metricBox.innerHTML = metrics.map(([label, value]) => `<article><strong>${escapeHtml(value)}</strong><span>${escapeHtml(label)}</span></article>`).join("");
  }

  const riskList = el("commandCenterRiskList");
  if (riskList) {
    const rows = summary.high_risk_assets || summary.risk_findings || [];
    riskList.innerHTML = `
      <table>
        <thead><tr><th>Asset</th><th>Status</th><th>Risk</th><th>Drivers</th></tr></thead>
        <tbody>
          ${rows.map((item) => {
            const props = item.object?.properties || {};
            const risk = item.risk || {};
            return `
              <tr data-command-asset="${escapeHtml(item.object_id)}">
                <td><strong>${escapeHtml(props.name || item.object_id)}</strong><br><span>${escapeHtml(item.object_id)}</span></td>
                <td>${escapeHtml(props.status || "-")}</td>
                <td><span class="pill ${risk.band === "critical" || risk.band === "high" ? "red" : "green"}">${escapeHtml(risk.band || "-")} ${escapeHtml(risk.score ?? "")}</span></td>
                <td>${escapeHtml((risk.drivers || []).map((driver) => driver.feature).join(", ") || "-")}</td>
              </tr>
            `;
          }).join("") || '<tr><td colspan="4">No risk findings yet. Bootstrap the scenario.</td></tr>'}
        </tbody>
      </table>
    `;
  }

  const selected = el("commandCenterSelectedAsset");
  if (selected) {
    const asset = summary.selected_asset || {};
    const props = asset.properties || {};
    selected.innerHTML = asset.id ? [
      ["Asset", props.name || asset.id],
      ["Status", props.status],
      ["Criticality", props.criticality],
      ["Vibration", props.vibration_mm_s],
      ["Temperature", props.temperature_c],
      ["Failure probability", props.predicted_failure_probability],
      ["MGRS", props.mgrs]
    ].map(([key, value]) => `<div class="kv"><span>${escapeHtml(key)}</span><strong>${escapeHtml(value ?? "-")}</strong></div>`).join("") : '<div class="empty-state compact-empty">No selected asset. Bootstrap the scenario.</div>';
  }

  const checks = el("commandCenterChecks");
  if (checks) {
    const dataContract = summary.data_contract || {};
    const monitor = summary.model_monitor || {};
    checks.innerHTML = `
      <div class="kv"><span>Data contract</span><strong>${escapeHtml(dataContract.status || "NOT_RUN")}</strong></div>
      <div class="kv"><span>Failed checks</span><strong>${escapeHtml(dataContract.summary?.failed ?? "-")}</strong></div>
      <div class="kv"><span>Model monitor</span><strong>${escapeHtml(monitor.status || "NOT_RUN")}</strong></div>
      <div class="kv"><span>Monitor alerts</span><strong>${escapeHtml((monitor.alerts || []).length)}</strong></div>
    `;
  }

  const recommendation = el("commandCenterRecommendation");
  if (recommendation) {
    const triage = state.commandCenter.triage || {};
    const session = triage.agent_session || {};
    const approval = triage.approval || (summary.approvals || [])[0];
    const actionResult = state.commandCenter.actionResult;
    recommendation.innerHTML = session.id ? `
      <div class="kv"><span>Recommendation</span><strong>${escapeHtml(session.plan?.recommendation || "-")}</strong></div>
      <div class="kv"><span>Tool trace</span><strong>${escapeHtml((session.plan?.tool_trace || []).join(" -> "))}</strong></div>
      <div class="kv"><span>Approval</span><strong>${escapeHtml(approval?.status || "-")} ${escapeHtml(approval?.id || "")}</strong></div>
      <div class="kv"><span>Action</span><strong>${escapeHtml(approval?.action_type_id || "-")}</strong></div>
      <div class="kv"><span>Execution</span><strong>${escapeHtml(actionResult?.execution?.status || "not executed")}</strong></div>
    ` : '<div class="empty-state compact-empty">Run triage to create an agent recommendation and staged approval.</div>';
  }

  const report = el("commandCenterReport");
  if (report) {
    const latest = state.commandCenter.triage?.report || summary.latest_report;
    report.textContent = latest?.body || "No report yet. Bootstrap or run triage.";
  }

  const timeline = el("commandCenterTimeline");
  if (timeline) {
    const rows = summary.timeline || [];
    timeline.innerHTML = `
      <table>
        <thead><tr><th>When</th><th>Kind</th><th>Event</th></tr></thead>
        <tbody>
          ${rows.slice(0, 12).map((row) => `
            <tr>
              <td>${escapeHtml(row.created_at ? new Date(row.created_at * 1000).toLocaleString() : "-")}</td>
              <td>${escapeHtml(row.kind)}</td>
              <td><strong>${escapeHtml(row.title)}</strong><br><span>${escapeHtml(row.id)}</span></td>
            </tr>
          `).join("") || '<tr><td colspan="3">No timeline entries yet.</td></tr>'}
        </tbody>
      </table>
    `;
  }

  const validation = el("commandCenterValidation");
  if (validation) {
    const dash = state.commandCenter.validation || {};
    validation.innerHTML = `
      <div class="kv"><span>Matrix rows</span><strong>${escapeHtml(dash.row_count ?? "-")}</strong></div>
      <div class="kv"><span>MATCH</span><strong>${escapeHtml(dash.status_counts?.MATCH ?? 0)}</strong></div>
      <div class="kv"><span>LOCAL_ANALOG</span><strong>${escapeHtml(dash.status_counts?.LOCAL_ANALOG ?? 0)}</strong></div>
      <div class="kv"><span>P0/P1 gaps</span><strong>${escapeHtml((dash.priority_gaps || []).length)}</strong></div>
    `;
  }
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
      { id: "input", type: "input_dataset", label: "Input dataset", position: { x: 80, y: 150 }, config: { asset_id: assetId } },
      { id: "filter", type: "filter", label: "Filter", position: { x: 340, y: 150 }, config: { filters: { status: { not_equals: "closed" } } } },
      { id: "project", type: "project", label: "Project", position: { x: 600, y: 150 }, config: { columns: ["id", "name", "status", "criticality"] } },
      { id: "unique_id", type: "unique_id", label: "Unique ID", position: { x: 860, y: 150 }, config: { target_field: "id", source_fields: ["id", "name"] } },
      { id: "output", type: "dataset_output", label: "Dataset output", position: { x: 1120, y: 150 }, config: { asset_id: "operations_pipeline_output" } }
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

async function loadPipelineNodeTypes() {
  try {
    const catalog = await api("/pipeline-builder/node-types");
    state.pipeline.nodeTypes = catalog.node_types || [];
  } catch (_) {
    state.pipeline.nodeTypes = PIPELINE_NODE_TYPES;
  }
}

async function refreshPipelineBuilder() {
  await Promise.allSettled([loadDataAssets(), loadPipelineNodeTypes()]);
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
  const nodes = state.pipeline.nodeTypes?.length ? state.pipeline.nodeTypes : PIPELINE_NODE_TYPES;
  el("pipelineNodeLibrary").innerHTML = nodes.map((node) => `
    <button class="node-library-item" type="button" draggable="true" data-add-pipeline-node="${escapeHtml(node.type)}">
      <strong>${escapeHtml(node.label)}</strong>
      <span>${escapeHtml(node.category || node.type)} - ${escapeHtml(node.type)}</span>
    </button>
  `).join("");
}

function renderPipelineCanvas() {
  const draft = state.pipeline.draft || defaultPipelineDraft();
  const nodeOutputs = state.pipeline.preview?.node_outputs || {};
  if (!window.d3) {
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
    return;
  }
  const canvas = el("pipelineCanvas");
  canvas.innerHTML = "";
  const width = Math.max(980, canvas.clientWidth || 980);
  const height = Math.max(520, canvas.clientHeight || 520);
  const validation = state.pipeline.validation || {};
  const nodeIssueCounts = {};
  [...(validation.errors || []), ...(validation.warnings || [])].forEach((issue) => {
    if (issue.node_id) nodeIssueCounts[issue.node_id] = (nodeIssueCounts[issue.node_id] || 0) + 1;
  });
  normalizePipelineNodePositions(draft);
  const nodeById = Object.fromEntries((draft.nodes || []).map((node) => [node.id, node]));
  const svg = d3.select(canvas).append("svg")
    .attr("class", "pipeline-svg")
    .attr("viewBox", `0 0 ${width} ${height}`)
    .attr("role", "img")
    .attr("aria-label", "Pipeline graph canvas");
  const viewport = svg.append("g").attr("class", "pipeline-viewport");
  const linksLayer = viewport.append("g").attr("class", "pipeline-links");
  const nodesLayer = viewport.append("g").attr("class", "pipeline-nodes");
  svg.call(d3.zoom().scaleExtent([0.45, 1.8]).on("zoom", (event) => {
    viewport.attr("transform", event.transform);
  })).on("dblclick.zoom", null);

  const edgePath = (edge) => {
    const source = nodeById[edge.source];
    const target = nodeById[edge.target];
    if (!source || !target) return "";
    const sx = (source.position?.x || 0) + 210;
    const sy = (source.position?.y || 0) + 45;
    const tx = target.position?.x || 0;
    const ty = (target.position?.y || 0) + 45;
    const mid = Math.max(40, (tx - sx) / 2);
    return `M ${sx} ${sy} C ${sx + mid} ${sy}, ${tx - mid} ${ty}, ${tx} ${ty}`;
  };

  linksLayer.selectAll("path")
    .data(draft.edges || [], (edge) => `${edge.source}->${edge.target}`)
    .join("path")
    .attr("class", (edge) => `pipeline-link${state.pipeline.activeEdgeId === `${edge.source}->${edge.target}` ? " selected" : ""}`)
    .attr("d", edgePath)
    .on("click", (event, edge) => {
      event.stopPropagation();
      state.pipeline.activeEdgeId = `${edge.source}->${edge.target}`;
      state.pipeline.activeNodeId = "";
      renderPipelineBuilder();
    });

  const nodeGroups = nodesLayer.selectAll("g.pipeline-svg-node")
    .data(draft.nodes || [], (node) => node.id)
    .join("g")
    .attr("class", (node) => {
      const selected = state.pipeline.activeNodeId === node.id ? " selected" : "";
      const hasIssues = nodeIssueCounts[node.id] ? " issue" : "";
      return `pipeline-svg-node${selected}${hasIssues}`;
    })
    .attr("transform", (node) => `translate(${node.position?.x || 0},${node.position?.y || 0})`)
    .call(d3.drag()
      .on("start", (event, node) => {
        event.sourceEvent.stopPropagation();
        state.pipeline.activeNodeId = node.id;
        state.pipeline.activeEdgeId = "";
      })
      .on("drag", (event, node) => {
        node.position = { x: Math.max(10, event.x), y: Math.max(10, event.y) };
        d3.select(event.sourceEvent.target.closest("g.pipeline-svg-node")).attr("transform", `translate(${node.position.x},${node.position.y})`);
        linksLayer.selectAll("path").attr("d", edgePath);
      })
      .on("end", () => renderPipelineConfig()));

  nodeGroups.append("rect").attr("width", 220).attr("height", 92).attr("rx", 8);
  nodeGroups.append("text").attr("class", "pipeline-svg-title").attr("x", 16).attr("y", 26).text((node) => node.label || node.type);
  nodeGroups.append("text").attr("class", "pipeline-svg-type").attr("x", 16).attr("y", 46).text((node) => node.type);
  nodeGroups.append("text").attr("class", "pipeline-svg-meta").attr("x", 16).attr("y", 70).text((node) => {
    const output = nodeOutputs[node.id] || {};
    const issue = nodeIssueCounts[node.id] ? `${nodeIssueCounts[node.id]} issue` : "ok";
    return `rows ${output.row_count ?? "-"} - ${issue}`;
  });
  nodeGroups.append("circle")
    .attr("class", "pipeline-port input")
    .attr("cx", 0)
    .attr("cy", 46)
    .attr("r", 8)
    .on("click", (event, node) => finishPipelineConnection(event, node.id));
  nodeGroups.append("circle")
    .attr("class", "pipeline-port output")
    .attr("cx", 220)
    .attr("cy", 46)
    .attr("r", 8)
    .on("click", (event, node) => startPipelineConnection(event, node.id));
  nodeGroups.on("click", (event, node) => {
    event.stopPropagation();
    state.pipeline.activeNodeId = node.id;
    state.pipeline.activeEdgeId = "";
    renderPipelineBuilder();
  });
  svg.on("click", () => {
    state.pipeline.activeEdgeId = "";
    state.pipeline.activeNodeId = "";
    renderPipelineBuilder();
  });
  if (!(draft.nodes || []).length) {
    canvas.innerHTML = '<div class="empty-state">Drag a node from the library to start building a pipeline graph</div>';
  }
}

function normalizePipelineNodePositions(draft) {
  (draft.nodes || []).forEach((node, index) => {
    if (!node.position) {
      node.position = { x: 80 + (index % 4) * 260, y: 90 + Math.floor(index / 4) * 150 };
    }
  });
}

function startPipelineConnection(event, nodeId) {
  event.stopPropagation();
  state.pipeline.connectingFrom = nodeId;
  showToast(`Connect ${nodeId} to an input port`);
}

function finishPipelineConnection(event, targetId) {
  event.stopPropagation();
  const sourceId = state.pipeline.connectingFrom;
  if (!sourceId || sourceId === targetId) {
    state.pipeline.connectingFrom = "";
    return;
  }
  const draft = state.pipeline.draft || defaultPipelineDraft();
  const exists = (draft.edges || []).some((edge) => edge.source === sourceId && edge.target === targetId);
  if (!exists) {
    draft.edges = [...(draft.edges || []), { source: sourceId, target: targetId }];
  }
  state.pipeline.connectingFrom = "";
  state.pipeline.activeEdgeId = `${sourceId}->${targetId}`;
  renderPipelineBuilder();
}

function autoLayoutPipelineGraph() {
  const draft = state.pipeline.draft || defaultPipelineDraft();
  normalizePipelineNodePositions(draft);
  const incoming = {};
  (draft.nodes || []).forEach((node) => { incoming[node.id] = 0; });
  (draft.edges || []).forEach((edge) => { if (incoming[edge.target] !== undefined) incoming[edge.target] += 1; });
  const levels = {};
  const queue = (draft.nodes || []).filter((node) => incoming[node.id] === 0).map((node) => node.id);
  queue.forEach((id) => { levels[id] = 0; });
  while (queue.length) {
    const source = queue.shift();
    (draft.edges || []).filter((edge) => edge.source === source).forEach((edge) => {
      levels[edge.target] = Math.max(levels[edge.target] || 0, (levels[source] || 0) + 1);
      queue.push(edge.target);
    });
  }
  const counts = {};
  (draft.nodes || []).forEach((node, index) => {
    const level = levels[node.id] ?? index;
    const slot = counts[level] || 0;
    counts[level] = slot + 1;
    node.position = { x: 80 + level * 280, y: 80 + slot * 150 };
  });
  renderPipelineBuilder();
}

function openOntologyGeneratorFromPipeline() {
  const draft = state.pipeline.draft || defaultPipelineDraft();
  const active = draft.nodes.find((node) => node.id === state.pipeline.activeNodeId);
  const input = draft.nodes.find((node) => node.type === "input_dataset");
  state.ontologyGenerator.selectedAssetId = active?.config?.source_asset_id || input?.config?.asset_id || state.datasets[0]?.id || "";
  const objectTypeId = active?.config?.object_type_id || "";
  el("ontologyGeneratorObjectTypeInput").value = objectTypeId;
  setView("ontology");
}

function renderPipelineCanvasListFallback() {
  const draft = state.pipeline.draft || defaultPipelineDraft();
  const nodeOutputs = state.pipeline.preview?.node_outputs || {};
  return draft.nodes.map((node, index) => {
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
  if (state.pipeline.activeEdgeId && !state.pipeline.activeNodeId) {
    const [source, target] = state.pipeline.activeEdgeId.split("->");
    el("pipelineConfig").innerHTML = `
      <div class="list-item"><strong>Connection</strong><span>${escapeHtml(source)} -> ${escapeHtml(target)}</span></div>
      <button class="btn full-width" data-remove-pipeline-edge="${escapeHtml(state.pipeline.activeEdgeId)}" type="button">Remove Connection</button>
    `;
    return;
  }
  const node = draft.nodes.find((item) => item.id === state.pipeline.activeNodeId) || draft.nodes[0];
  if (node && !state.pipeline.activeNodeId) state.pipeline.activeNodeId = node.id;
  if (!node) {
    el("pipelineConfig").innerHTML = '<div class="empty-state compact-empty">Select a node</div>';
    return;
  }
  const config = node.config || {};
  const nodeTypes = state.pipeline.nodeTypes?.length ? state.pipeline.nodeTypes : PIPELINE_NODE_TYPES;
  el("pipelineConfig").innerHTML = `
    <label class="field"><span>Label</span><input data-pipeline-node-field="label" value="${escapeHtml(node.label || "")}" /></label>
    <label class="field"><span>Type</span><select data-pipeline-node-field="type">${optionList(nodeTypes.map((item) => ({ value: item.type, label: item.label })), node.type)}</select></label>
    ${renderPipelineTypedConfig(node, config)}
    <label class="field"><span>Config JSON</span><textarea data-pipeline-node-field="config" rows="8">${escapeHtml(compactJson(config))}</textarea></label>
    <div id="pipelineNodePreview" class="node-preview-panel">${renderPipelineNodePreview(node.id)}</div>
    <button class="btn full-width" data-remove-pipeline-node="${escapeHtml(node.id)}" type="button">Remove Node</button>
  `;
}

function renderPipelineTypedConfig(node, config) {
  const type = node.type;
  if (type === "input_dataset") {
    return `<label class="field"><span>Dataset</span><select data-pipeline-config-field="asset_id">${datasetOptions(config.asset_id || config.dataset_id || "")}</select></label>`;
  }
  if (type === "dataset_output" || type === "output_dataset") {
    return `<label class="field"><span>Output dataset</span><input data-pipeline-config-field="asset_id" value="${escapeHtml(config.asset_id || config.dataset_id || "")}" /></label>`;
  }
  if (type === "filter") {
    return `<label class="field"><span>Filters JSON</span><textarea data-pipeline-config-field="filters" data-config-type="json" rows="4">${escapeHtml(compactJson(config.filters || {}))}</textarea></label>`;
  }
  if (type === "project" || type === "select") {
    return `<label class="field"><span>Columns</span><input data-pipeline-config-field="columns" data-config-type="csv" value="${escapeHtml((config.columns || []).join(", "))}" /></label>`;
  }
  if (type === "rename") {
    return `<label class="field"><span>Mapping JSON</span><textarea data-pipeline-config-field="mapping" data-config-type="json" rows="4">${escapeHtml(compactJson(config.mapping || config.rename || {}))}</textarea></label>`;
  }
  if (type === "join") {
    return `
      <label class="field"><span>Right dataset</span><select data-pipeline-config-field="right_asset_id">${datasetOptions(config.right_asset_id || "")}</select></label>
      <label class="field"><span>Left key</span><input data-pipeline-config-field="left_key" value="${escapeHtml(config.left_key || "")}" /></label>
      <label class="field"><span>Right key</span><input data-pipeline-config-field="right_key" value="${escapeHtml(config.right_key || "")}" /></label>
      <label class="field"><span>Join type</span><select data-pipeline-config-field="join_type">${optionList(["inner", "left"], config.join_type || "inner")}</select></label>
    `;
  }
  if (type === "union") {
    return `<label class="field"><span>Union dataset</span><select data-pipeline-config-field="asset_id">${datasetOptions(config.asset_id || "")}</select></label>`;
  }
  if (type === "aggregate") {
    return `
      <label class="field"><span>Group by</span><input data-pipeline-config-field="group_by" data-config-type="csv" value="${escapeHtml((config.group_by || []).join(", "))}" /></label>
      <label class="field"><span>Metrics JSON</span><textarea data-pipeline-config-field="metrics" data-config-type="json" rows="5">${escapeHtml(compactJson(config.metrics || []))}</textarea></label>
    `;
  }
  if (type === "sort") {
    return `
      <label class="field"><span>Field</span><input data-pipeline-config-field="field" value="${escapeHtml(config.field || "")}" /></label>
      <label class="field"><span>Direction</span><select data-pipeline-config-field="direction">${optionList(["asc", "desc"], config.direction || "asc")}</select></label>
    `;
  }
  if (type === "limit") {
    return `<label class="field"><span>Limit</span><input data-pipeline-config-field="limit" data-config-type="number" type="number" min="1" value="${escapeHtml(config.limit || config.count || 100)}" /></label>`;
  }
  if (type === "unique_id") {
    return `
      <label class="field"><span>Target field</span><input data-pipeline-config-field="target_field" value="${escapeHtml(config.target_field || "id")}" /></label>
      <label class="field"><span>Source fields</span><input data-pipeline-config-field="source_fields" data-config-type="csv" value="${escapeHtml((config.source_fields || config.fields || []).join(", "))}" /></label>
    `;
  }
  if (type === "llm_assist" || type === "llm") {
    return `
      <label class="field"><span>Prompt</span><input data-pipeline-config-field="prompt" value="${escapeHtml(config.prompt || "summarize")}" /></label>
      <label class="field"><span>Source fields</span><input data-pipeline-config-field="source_fields" data-config-type="csv" value="${escapeHtml((config.source_fields || []).join(", "))}" /></label>
      <label class="field"><span>Output field</span><input data-pipeline-config-field="output_field" value="${escapeHtml(config.output_field || "llm_summary")}" /></label>
    `;
  }
  if (type === "ontology_output") {
    return `
      <label class="field"><span>Object type</span><select data-pipeline-config-field="object_type_id">${objectTypeOptions(config.object_type_id || "")}</select></label>
      <label class="field"><span>ID field</span><input data-pipeline-config-field="id_field" value="${escapeHtml(config.id_field || "id")}" /></label>
      <label class="field"><span>Mapping JSON</span><textarea data-pipeline-config-field="mapping" data-config-type="json" rows="5">${escapeHtml(compactJson(config.mapping || {}))}</textarea></label>
      <button class="btn full-width" data-open-ontology-generator-from-pipeline type="button">Open Ontology Generator</button>
    `;
  }
  return "";
}

function renderPipelineNodePreview(nodeId) {
  const output = state.pipeline.preview?.node_outputs?.[nodeId];
  if (!output) return '<div class="empty-state compact-empty">Preview this graph to inspect this node output.</div>';
  return `
    <div class="list-item"><strong>${escapeHtml(output.row_count)} rows</strong><span>${escapeHtml((output.schema?.fields || []).map((field) => field.name).join(", "))}</span></div>
    <pre class="mini-output">${escapeHtml(compactJson(output.sample || []))}</pre>
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

function setModelOpsTab(tabName) {
  state.modelops.activeTab = tabName;
  document.querySelectorAll("[data-modelops-tab]").forEach((button) => {
    button.classList.toggle("active", button.dataset.modelopsTab === tabName);
  });
  document.querySelectorAll("[data-modelops-panel]").forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.modelopsPanel === tabName);
  });
  const labels = {
    objectives: "Objectives",
    training: "Training & Submissions",
    gates: "Evaluation Gates",
    releases: "Releases & Deployments",
    monitoring: "Monitoring",
    inference: "Inference Playground"
  };
  if (el("modelOpsTitle")) el("modelOpsTitle").textContent = labels[tabName] || "ModelOps";
}

async function refreshModelOpsWorkspace() {
  await Promise.allSettled([loadDataAssets(), loadModelOpsSummary(), loadModelObjectives(), loadModelDeployments(), loadModelMonitors()]);
  const objectiveId = state.modelops.selectedObjectiveId || state.modelops.objectives[0]?.id || "";
  state.modelops.selectedObjectiveId = objectiveId;
  if (objectiveId) {
    await Promise.allSettled([loadModelSubmissions(objectiveId), loadModelChecks(objectiveId), loadModelReleases(objectiveId)]);
  }
  const submissionId = state.modelops.selectedSubmissionId || state.modelops.submissions[0]?.id || "";
  state.modelops.selectedSubmissionId = submissionId;
  if (submissionId) await Promise.allSettled([loadModelEligibility(submissionId), loadModelCheckResults(submissionId)]);
  const deploymentId = state.modelops.selectedDeploymentId || state.modelops.deployments[0]?.id || "";
  state.modelops.selectedDeploymentId = deploymentId;
  if (deploymentId) await loadPredictionLogs(deploymentId).catch(() => {});
  renderModelOpsWorkspace();
}

async function loadModelOpsSummary() {
  state.modelops.summary = await api("/modelops/summary");
}

async function loadModelObjectives() {
  state.modelops.objectives = await api("/modeling/objectives");
}

async function loadModelSubmissions(objectiveId) {
  state.modelops.submissions = objectiveId ? await api(`/modeling/objectives/${encodeURIComponent(objectiveId)}/submissions`) : [];
}

async function loadModelChecks(objectiveId) {
  state.modelops.checks = objectiveId ? await api(`/modeling/objectives/${encodeURIComponent(objectiveId)}/checks`) : [];
}

async function loadModelCheckResults(submissionId) {
  state.modelops.checkResults = submissionId ? await api(`/modeling/submissions/${encodeURIComponent(submissionId)}/check-results`) : [];
}

async function loadModelEligibility(submissionId) {
  state.modelops.eligibility = submissionId ? await api(`/modeling/submissions/${encodeURIComponent(submissionId)}/release-eligibility`) : null;
}

async function loadModelReleases(objectiveId) {
  state.modelops.releases = objectiveId ? await api(`/modeling/objectives/${encodeURIComponent(objectiveId)}/releases`) : [];
}

async function loadModelDeployments() {
  state.modelops.deployments = await api("/modeling/deployments");
}

async function loadModelMonitors() {
  state.modelops.monitors = await api("/modelops/monitors");
  state.modelops.selectedMonitorId = state.modelops.selectedMonitorId || state.modelops.monitors[0]?.id || "";
  if (state.modelops.selectedMonitorId) {
    state.modelops.monitorRuns = await api(`/modelops/monitors/${encodeURIComponent(state.modelops.selectedMonitorId)}/runs`);
  }
}

async function loadPredictionLogs(deploymentId) {
  state.modelops.predictionLogs = deploymentId ? await api(`/modelops/deployments/${encodeURIComponent(deploymentId)}/prediction-logs`) : [];
}

function renderModelOpsWorkspace() {
  setModelOpsTab(state.modelops.activeTab || "objectives");
  renderModelOpsSelectors();
  renderModelOpsSummary();
  renderModelObjectiveList();
  renderModelSubmissionList();
  renderModelGatePanel();
  renderModelReleasePanel();
  renderModelMonitorPanel();
  renderModelInferencePanel();
  renderModelOpsRunList();
  el("modelOpsOutput").textContent = compactJson({
    objective: state.modelops.selectedObjectiveId,
    submission: state.modelops.selectedSubmissionId,
    deployment: state.modelops.selectedDeploymentId,
    monitor: state.modelops.selectedMonitorId
  });
}

function renderModelOpsSelectors() {
  fillSelect(el("modelObjectiveSelect"), state.modelops.objectives.map((objective) => ({
    value: objective.id,
    label: objective.display_name ? `${objective.display_name} (${objective.id})` : objective.id
  })), state.modelops.selectedObjectiveId, "Choose objective");
  fillSelect(el("modelSubmissionSelect"), state.modelops.submissions.map((submission) => ({
    value: submission.id,
    label: `${submission.algorithm || submission.id} (${submission.id.slice(0, 8)})`
  })), state.modelops.selectedSubmissionId, "Choose submission");
  fillSelect(el("modelDeploymentSelect"), state.modelops.deployments.map((deployment) => ({
    value: deployment.id,
    label: `${deployment.id} - ${deployment.mode}`
  })), state.modelops.selectedDeploymentId, "Choose deployment");
  ["modelInputAssetSelect", "modelTrainingAssetSelect", "modelBaselineAssetSelect", "modelCurrentAssetSelect"].forEach((id) => {
    fillSelect(el(id), state.datasets.map((asset) => ({
      value: asset.id,
      label: asset.display_name ? `${asset.display_name} (${asset.id})` : asset.id
    })), el(id)?.value || state.datasets[0]?.id || "", "Choose dataset");
  });
}

function renderModelOpsSummary() {
  const summary = state.modelops.summary || {};
  el("modelOpsSummary").innerHTML = [
    ["Objectives", summary.objectives || 0],
    ["Submissions", summary.submissions || 0],
    ["Deployments", summary.deployments || 0],
    ["Monitors", summary.monitors || 0],
    ["Prediction logs", summary.prediction_logs || 0]
  ].map(([label, value]) => `<div class="list-item"><strong>${escapeHtml(label)}</strong><span>${escapeHtml(value)}</span></div>`).join("");
}

function renderModelObjectiveList() {
  el("modelObjectiveList").innerHTML = state.modelops.objectives.map((objective) => `
    <article class="modelops-card ${objective.id === state.modelops.selectedObjectiveId ? "selected" : ""}" data-model-objective="${escapeHtml(objective.id)}">
      <div class="decision-card-head"><strong>${escapeHtml(objective.display_name || objective.id)}</strong><span class="risk-badge low">${escapeHtml(objective.problem_type)}</span></div>
      <span>${escapeHtml(objective.target_field)} from ${escapeHtml((objective.feature_fields || []).join(", "))}</span>
      <small>${escapeHtml(objective.input_asset_id || "no input dataset")}</small>
    </article>
  `).join("") || '<div class="empty-state">No modeling objectives</div>';
}

function renderModelSubmissionList() {
  el("modelSubmissionList").innerHTML = state.modelops.submissions.map((submission) => `
    <article class="modelops-card ${submission.id === state.modelops.selectedSubmissionId ? "selected" : ""}" data-model-submission="${escapeHtml(submission.id)}">
      <div class="decision-card-head"><strong>${escapeHtml(submission.algorithm || submission.id)}</strong><span class="risk-badge ${submission.released ? "low" : "medium"}">${submission.released ? "released" : "draft"}</span></div>
      <span>${escapeHtml(submission.trainer_type || "legacy")} - ${escapeHtml(submission.status)}</span>
      <pre class="mini-output">${escapeHtml(compactJson(submission.metrics || {}))}</pre>
    </article>
  `).join("") || '<div class="empty-state">No submissions for this objective</div>';
}

function renderModelGatePanel() {
  const checks = state.modelops.checks || [];
  const results = state.modelops.checkResults || [];
  const resultByCheck = Object.fromEntries(results.map((result) => [result.check_id, result]));
  el("modelGatePanel").innerHTML = `
    <div class="section-title">
      <h2>Release Eligibility</h2>
      <span class="risk-badge ${state.modelops.eligibility?.eligible ? "low" : "high"}">${state.modelops.eligibility?.eligible ? "eligible" : "blocked"}</span>
    </div>
    <div class="modelops-grid">
      ${checks.map((check) => {
        const result = resultByCheck[check.id];
        return `<article class="modelops-card">
          <strong>${escapeHtml(check.name)}</strong>
          <span>${escapeHtml(check.check_type)} ${escapeHtml(check.metric || "")} ${escapeHtml(check.operator || "")} ${escapeHtml(check.threshold ?? "")}</span>
          <span>${escapeHtml(result?.status || "not evaluated")}</span>
          ${check.check_type === "manual" ? `<div class="button-row"><button class="btn small" data-model-check-decision="${escapeHtml(check.id)}" data-model-check-status="approved" type="button">Approve</button><button class="btn small" data-model-check-decision="${escapeHtml(check.id)}" data-model-check-status="rejected" type="button">Reject</button></div>` : ""}
        </article>`;
      }).join("") || '<div class="empty-state">No checks configured</div>'}
    </div>
  `;
}

function renderModelReleasePanel() {
  const deployments = state.modelops.deployments.filter((deployment) => !state.modelops.selectedObjectiveId || deployment.objective_id === state.modelops.selectedObjectiveId);
  el("modelReleasePanel").innerHTML = `
    ${state.modelops.releases.map((release) => `
      <article class="modelops-card">
        <div class="decision-card-head"><strong>${escapeHtml(release.version)}</strong><span class="risk-badge low">${escapeHtml(release.environment)}</span></div>
        <span>${escapeHtml(release.submission_id)}</span>
      </article>
    `).join("") || '<div class="empty-state">No releases for this objective</div>'}
    ${deployments.map((deployment) => `
      <article class="modelops-card ${deployment.id === state.modelops.selectedDeploymentId ? "selected" : ""}" data-model-deployment="${escapeHtml(deployment.id)}">
        <div class="decision-card-head"><strong>${escapeHtml(deployment.id)}</strong><span class="risk-badge low">${escapeHtml(deployment.status)}</span></div>
        <span>${escapeHtml(deployment.mode)} - ${escapeHtml(deployment.submission_id)}</span>
      </article>
    `).join("")}
  `;
}

function renderModelMonitorPanel() {
  el("modelMonitorPanel").innerHTML = state.modelops.monitors.map((monitor) => `
    <article class="modelops-card ${monitor.id === state.modelops.selectedMonitorId ? "selected" : ""}" data-model-monitor="${escapeHtml(monitor.id)}">
      <div class="decision-card-head"><strong>${escapeHtml(monitor.display_name || monitor.id)}</strong>${renderMonitorStatus(monitor.latest_run?.status)}</div>
      <span>${escapeHtml(monitor.objective_id)} - ${escapeHtml((monitor.feature_fields || []).join(", "))}</span>
      <small>baseline ${escapeHtml(monitor.baseline_asset_id)}</small>
    </article>
  `).join("") || '<div class="empty-state">No monitors configured</div>';
}

function renderMonitorStatus(status = "PASS") {
  const cls = status === "FAIL" ? "critical" : status === "WARN" ? "medium" : "low";
  return `<span class="risk-badge ${cls}">${escapeHtml(status || "PASS")}</span>`;
}

function renderModelInferencePanel() {
  const logs = state.modelops.predictionLogs || [];
  el("modelInferencePanel").innerHTML = `
    <div class="section-title"><h2>Result</h2></div>
    <pre class="mini-output tall">${escapeHtml(state.modelops.inferenceResult ? compactJson(state.modelops.inferenceResult) : "No inference run yet")}</pre>
    <div class="section-title"><h2>Prediction Logs</h2></div>
    <div class="builder-list">
      ${logs.slice(0, 8).map((log) => `<div class="list-item"><strong>${escapeHtml(log.request_shape)}</strong><span>${escapeHtml(log.output_count)} predictions</span><span>${escapeHtml(new Date((log.created_at || 0) * 1000).toLocaleString())}</span></div>`).join("") || '<div class="empty-state compact-empty">No prediction logs</div>'}
    </div>
  `;
}

function renderModelOpsRunList() {
  const runs = state.modelops.monitorRuns || state.modelops.summary?.latest_runs || [];
  el("modelOpsRunList").innerHTML = runs.slice(0, 8).map((run) => `
    <button class="builder-list-button" type="button" data-model-monitor-run="${escapeHtml(run.id)}">
      <strong>${escapeHtml(run.status)}</strong>
      <span>${escapeHtml(run.current_asset_id)} - ${escapeHtml((run.alerts || []).length)} alerts</span>
    </button>
  `).join("") || '<div class="empty-state compact-empty">No monitor runs</div>';
}

async function createModelObjective() {
  const payload = {
    id: el("modelObjectiveIdInput").value.trim() || undefined,
    display_name: el("modelObjectiveNameInput").value.trim() || "Model Objective",
    problem_type: el("modelProblemTypeSelect").value,
    target_field: el("modelTargetFieldInput").value.trim(),
    feature_fields: splitCsv(el("modelFeatureFieldsInput").value),
    input_asset_id: el("modelInputAssetSelect").value || null
  };
  const created = await api("/modeling/objectives", { method: "POST", body: JSON.stringify(payload) });
  state.modelops.selectedObjectiveId = created.id;
  await refreshModelOpsWorkspace();
  showToast("Model objective created");
}

async function trainSelectedModel() {
  const objectiveId = state.modelops.selectedObjectiveId || el("modelObjectiveSelect").value;
  if (!objectiveId) throw new Error("Choose an objective");
  const payload = {
    trainer_type: el("modelTrainerTypeSelect").value,
    algorithm: el("modelAlgorithmInput").value.trim() || undefined,
    training_dataset_id: el("modelTrainingAssetSelect").value || undefined,
    target_column: el("modelTrainTargetInput").value.trim() || undefined,
    eval_metric: el("modelEvalMetricInput").value.trim() || undefined,
    quality_preset: el("modelQualityPresetSelect").value
  };
  const submission = await api(`/modeling/objectives/${encodeURIComponent(objectiveId)}/train`, { method: "POST", body: JSON.stringify(payload) });
  state.modelops.selectedSubmissionId = submission.id;
  await refreshModelOpsWorkspace();
  showToast("Model submission trained");
}

async function createModelCheck() {
  const objectiveId = state.modelops.selectedObjectiveId || el("modelObjectiveSelect").value;
  if (!objectiveId) throw new Error("Choose an objective");
  const type = el("modelCheckTypeSelect").value;
  const payload = {
    name: el("modelCheckNameInput").value.trim() || "quality_gate",
    check_type: type
  };
  if (type === "automatic") {
    payload.metric = el("modelCheckMetricInput").value.trim();
    payload.operator = el("modelCheckOperatorSelect").value;
    payload.threshold = Number(el("modelCheckThresholdInput").value || 0);
  }
  await api(`/modeling/objectives/${encodeURIComponent(objectiveId)}/checks`, { method: "POST", body: JSON.stringify(payload) });
  await refreshModelOpsWorkspace();
  showToast("Evaluation check created");
}

async function decideModelCheck(checkId, status) {
  const submissionId = state.modelops.selectedSubmissionId || el("modelSubmissionSelect").value;
  if (!submissionId) throw new Error("Choose a submission");
  await api(`/modeling/submissions/${encodeURIComponent(submissionId)}/check-results`, {
    method: "POST",
    body: JSON.stringify({
      check_id: checkId,
      status,
      reviewer: "workspace",
      comment: `Decision from ModelOps workspace: ${status}`
    })
  });
  await refreshModelOpsWorkspace();
  showToast(`Check ${status}`);
}

async function createModelRelease() {
  const objectiveId = state.modelops.selectedObjectiveId || el("modelObjectiveSelect").value;
  const submissionId = state.modelops.selectedSubmissionId || el("modelSubmissionSelect").value;
  if (!objectiveId || !submissionId) throw new Error("Choose an objective and submission");
  await api(`/modeling/objectives/${encodeURIComponent(objectiveId)}/releases`, {
    method: "POST",
    body: JSON.stringify({
      submission_id: submissionId,
      version: el("modelReleaseVersionInput").value.trim() || "v1.0",
      environment: el("modelReleaseEnvSelect").value,
      notes: "Created from ModelOps workspace"
    })
  });
  await refreshModelOpsWorkspace();
  showToast("Release created");
}

async function createModelDeployment() {
  const objectiveId = state.modelops.selectedObjectiveId || el("modelObjectiveSelect").value;
  const submissionId = state.modelops.selectedSubmissionId || el("modelSubmissionSelect").value;
  if (!objectiveId || !submissionId) throw new Error("Choose an objective and released submission");
  const deployment = await api("/modeling/deployments", {
    method: "POST",
    body: JSON.stringify({ objective_id: objectiveId, submission_id: submissionId, mode: el("modelDeploymentModeSelect").value })
  });
  state.modelops.selectedDeploymentId = deployment.id;
  await refreshModelOpsWorkspace();
  showToast("Deployment created");
}

async function createModelMonitor() {
  const objectiveId = state.modelops.selectedObjectiveId || el("modelObjectiveSelect").value;
  if (!objectiveId) throw new Error("Choose an objective");
  const monitor = await api("/modelops/monitors", {
    method: "POST",
    body: JSON.stringify({
      display_name: el("modelMonitorNameInput").value.trim() || "Deployment Drift Monitor",
      objective_id: objectiveId,
      deployment_id: state.modelops.selectedDeploymentId || el("modelDeploymentSelect").value || null,
      baseline_asset_id: el("modelBaselineAssetSelect").value,
      feature_fields: splitCsv(el("modelMonitorFieldsInput").value),
      prediction_field: el("modelPredictionFieldInput").value.trim() || "prediction",
      target_field: el("modelMonitorTargetInput").value.trim() || null,
      thresholds: parseJsonValue(el("modelMonitorThresholdsInput").value, {}, "Monitor thresholds")
    })
  });
  state.modelops.selectedMonitorId = monitor.id;
  await refreshModelOpsWorkspace();
  showToast("Model monitor created");
}

async function runSelectedModelMonitor() {
  const monitorId = state.modelops.selectedMonitorId || state.modelops.monitors[0]?.id;
  if (!monitorId) throw new Error("Create or select a monitor");
  const run = await api(`/modelops/monitors/${encodeURIComponent(monitorId)}/run`, {
    method: "POST",
    body: JSON.stringify({ current_asset_id: el("modelCurrentAssetSelect").value })
  });
  state.modelops.selectedMonitorId = monitorId;
  await refreshModelOpsWorkspace();
  el("modelOpsOutput").textContent = compactJson(run);
  showToast(`Monitor ${run.status}`);
}

async function runModelInference() {
  const deploymentId = state.modelops.selectedDeploymentId || el("modelDeploymentSelect").value;
  if (!deploymentId) throw new Error("Choose a deployment");
  const records = parseJsonValue(el("modelInferenceInput").value, [], "Inference records");
  const result = await api(`/modeling/deployments/${encodeURIComponent(deploymentId)}/infer`, {
    method: "POST",
    body: JSON.stringify({ inference_data: records })
  });
  state.modelops.inferenceResult = result;
  await loadPredictionLogs(deploymentId).catch(() => {});
  renderModelInferencePanel();
  el("modelOpsOutput").textContent = compactJson(result);
  showToast("Inference complete");
}

async function loadClassicPipelines() {
  try {
    state.classicPipelines = await api("/pipelines");
  } catch (_) {
    state.classicPipelines = [];
  }
}

function setOpsTab(tabName) {
  state.ops.activeTab = tabName;
  document.querySelectorAll("[data-ops-tab]").forEach((button) => {
    button.classList.toggle("active", button.dataset.opsTab === tabName);
  });
  document.querySelectorAll("[data-ops-panel]").forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.opsPanel === tabName);
  });
  const labels = {
    command: "Command Center",
    alerts: "Alerts",
    incidents: "Incidents",
    runbooks: "Runbooks",
    approvals: "Approvals",
    reliability: "Reliability",
    inbox: "Inbox"
  };
  if (el("opsTitle")) el("opsTitle").textContent = labels[tabName] || "Ops Control Plane";
}

async function refreshOpsWorkspace() {
  await Promise.allSettled([
    loadDataAssets(),
    loadClassicPipelines(),
    loadOpsSummary(),
    loadOpsEvents(),
    loadOpsAlertRules(),
    loadOpsAlerts(),
    loadOpsIncidents(),
    loadOpsRunbooks(),
    loadOpsInbox(),
    loadOpsApprovals(),
    loadReliabilitySummary(),
    loadDataContracts(),
    loadBackfills()
  ]);
  renderOpsWorkspace();
}

async function loadOpsSummary() { state.ops.summary = await api("/ops/summary"); }
async function loadOpsEvents() { state.ops.events = await api("/ops/events?limit=50"); }
async function loadOpsAlertRules() { state.ops.alertRules = await api("/ops/alert-rules"); }
async function loadOpsAlerts() { state.ops.alerts = await api("/ops/alerts"); }
async function loadOpsIncidents() { state.ops.incidents = await api("/ops/incidents"); }
async function loadOpsRunbooks() { state.ops.runbooks = await api("/ops/runbooks"); }
async function loadOpsInbox() { state.ops.inbox = await api("/ops/inbox"); }
async function loadOpsApprovals() { state.ops.approvals = await api("/approvals"); }
async function loadReliabilitySummary() { state.ops.reliability = await api("/reliability/summary"); }
async function loadDataContracts() { state.ops.dataContracts = await api("/reliability/data-contracts"); }
async function loadBackfills() { state.ops.backfills = await api("/reliability/backfills"); }

function renderOpsWorkspace() {
  setOpsTab(state.ops.activeTab || "command");
  renderOpsSelectors();
  renderOpsSummary();
  renderOpsEvents();
  renderOpsAlerts();
  renderOpsIncidents();
  renderOpsRunbooks();
  renderOpsApprovals();
  renderOpsReliability();
  renderOpsInbox();
  el("opsOutput").textContent = state.ops.output ? compactJson(state.ops.output) : compactJson({
    alerts: state.ops.alerts.length,
    incidents: state.ops.incidents.length,
    runbooks: state.ops.runbooks.length,
    contracts: state.ops.dataContracts.length
  });
}

function renderOpsSelectors() {
  state.ops.selectedIncidentId = state.ops.selectedIncidentId || state.ops.incidents[0]?.id || "";
  state.ops.selectedRunbookId = state.ops.selectedRunbookId || state.ops.runbooks[0]?.id || "";
  state.ops.selectedContractId = state.ops.selectedContractId || state.ops.dataContracts[0]?.id || "";
  fillSelect(el("opsIncidentSelect"), state.ops.incidents.map((incident) => ({ value: incident.id, label: `${incident.display_name} (${incident.status})` })), state.ops.selectedIncidentId, "Choose incident");
  fillSelect(el("opsRunbookSelect"), state.ops.runbooks.map((runbook) => ({ value: runbook.id, label: runbook.display_name || runbook.id })), state.ops.selectedRunbookId, "Choose runbook");
  fillSelect(el("opsContractSelect"), state.ops.dataContracts.map((contract) => ({ value: contract.id, label: contract.display_name || contract.id })), state.ops.selectedContractId, "Choose contract");
  ["opsContractAssetSelect", "opsContractRunAssetSelect"].forEach((id) => {
    fillSelect(el(id), state.datasets.map((asset) => ({ value: asset.id, label: asset.display_name ? `${asset.display_name} (${asset.id})` : asset.id })), el(id)?.value || state.datasets[0]?.id || "", "Choose dataset");
  });
  fillSelect(el("opsBackfillPipelineSelect"), state.classicPipelines.map((pipeline) => ({ value: pipeline.id, label: pipeline.display_name ? `${pipeline.display_name} (${pipeline.id})` : pipeline.id })), el("opsBackfillPipelineSelect")?.value || state.classicPipelines[0]?.id || "", "Choose pipeline");
}

function renderOpsSummary() {
  const summary = state.ops.summary || {};
  el("opsSummaryCards").innerHTML = [
    ["Events", summary.events || 0, "low"],
    ["Open alerts", summary.open_alerts || 0, summary.open_alerts ? "high" : "low"],
    ["Open incidents", summary.open_incidents || 0, summary.open_incidents ? "medium" : "low"],
    ["Pending approvals", summary.pending_approvals || 0, summary.pending_approvals ? "high" : "low"],
    ["Unread inbox", summary.unread_notifications || 0, summary.unread_notifications ? "medium" : "low"],
  ].map(([label, value, cls]) => `
    <article class="ops-metric">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
      <em class="risk-badge ${escapeHtml(cls)}">${escapeHtml(cls)}</em>
    </article>
  `).join("");
}

function renderOpsEvents() {
  el("opsEventList").innerHTML = (state.ops.events || []).slice(0, 12).map((event) => `
    <div class="list-item">
      <strong>${escapeHtml(event.title || event.event_type)}</strong>
      <span>${escapeHtml(event.source)} - ${escapeHtml(event.event_type)}</span>
      ${statusBadge(event.severity)}
    </div>
  `).join("") || '<div class="empty-state compact-empty">No operational events</div>';
}

function renderOpsAlerts() {
  el("opsAlertRuleList").innerHTML = (state.ops.alertRules || []).map((rule) => `
    <div class="list-item">
      <strong>${escapeHtml(rule.display_name || rule.id)}</strong>
      <span>${escapeHtml(rule.source || "any source")} - min ${escapeHtml(rule.min_severity)}</span>
    </div>
  `).join("") || '<div class="empty-state compact-empty">No alert rules</div>';
  const alertHtml = (state.ops.alerts || []).slice(0, 20).map((alert) => `
    <article class="modelops-card">
      <div class="decision-card-head"><strong>${escapeHtml(alert.title)}</strong>${statusBadge(alert.severity)}</div>
      <span>${escapeHtml(alert.status)} - ${escapeHtml(alert.source)} - ${escapeHtml(alert.subject_id || "")}</span>
      <small>${escapeHtml(alert.message || alert.event_id)}</small>
    </article>
  `).join("") || '<div class="empty-state">No alerts. Create a rule and evaluate events.</div>';
  if (el("opsAlertList")) el("opsAlertList").innerHTML = alertHtml;
  if (el("opsCommandAlertList")) el("opsCommandAlertList").innerHTML = alertHtml;
}

function renderOpsIncidents() {
  el("opsIncidentList").innerHTML = (state.ops.incidents || []).map((incident) => `
    <article class="modelops-card ${incident.id === state.ops.selectedIncidentId ? "selected" : ""}" data-ops-incident="${escapeHtml(incident.id)}">
      <div class="decision-card-head"><strong>${escapeHtml(incident.display_name)}</strong>${statusBadge(incident.severity)}</div>
      <span>${escapeHtml(incident.status)} - ${escapeHtml(incident.owner || "unowned")}</span>
      <small>${escapeHtml((incident.linked_objects || []).length)} objects - ${escapeHtml((incident.alert_ids || []).length)} alerts</small>
    </article>
  `).join("") || '<div class="empty-state">No incidents</div>';
}

function renderOpsRunbooks() {
  el("opsRunbookList").innerHTML = (state.ops.runbooks || []).map((runbook) => `
    <article class="modelops-card ${runbook.id === state.ops.selectedRunbookId ? "selected" : ""}" data-ops-runbook="${escapeHtml(runbook.id)}">
      <div class="decision-card-head"><strong>${escapeHtml(runbook.display_name)}</strong><span class="risk-badge ${runbook.enabled ? "low" : "muted"}">${runbook.enabled ? "enabled" : "disabled"}</span></div>
      <span>${escapeHtml((runbook.steps || []).length)} deterministic steps</span>
      <small>${escapeHtml(runbook.id)}</small>
    </article>
  `).join("") || '<div class="empty-state">No runbooks</div>';
  el("opsRunbookOutput").textContent = state.ops.output?.runbook ? compactJson(state.ops.output.runbook) : "No runbook execution yet";
}

function renderOpsApprovals() {
  el("opsApprovalList").innerHTML = (state.ops.approvals || []).slice(0, 20).map((approval) => `
    <div class="list-item">
      <strong>${escapeHtml(approval.action_type_id)}</strong>
      <span>${escapeHtml(approval.status)} - ${escapeHtml(approval.requester || "system")}</span>
      <span>${escapeHtml(approval.id)}</span>
    </div>
  `).join("") || '<div class="empty-state compact-empty">No approvals</div>';
}

function renderOpsReliability() {
  const summary = state.ops.reliability || {};
  el("opsReliabilitySummary").innerHTML = `
    <div class="modelops-grid">
      <article class="modelops-card"><strong>Contracts</strong><span>${escapeHtml(summary.data_contracts || 0)}</span></article>
      <article class="modelops-card"><strong>Backfills</strong><span>${escapeHtml(summary.backfills || 0)}</span></article>
      <article class="modelops-card"><strong>Impact runs</strong><span>${escapeHtml(summary.lineage_impact_runs || 0)}</span></article>
      <article class="modelops-card"><strong>Status</strong>${statusBadge(summary.status || "PASS")}</article>
    </div>
  `;
  el("opsDataContractList").innerHTML = (state.ops.dataContracts || []).map((contract) => `
    <article class="modelops-card ${contract.id === state.ops.selectedContractId ? "selected" : ""}" data-ops-contract="${escapeHtml(contract.id)}">
      <div class="decision-card-head"><strong>${escapeHtml(contract.display_name)}</strong>${statusBadge(contract.latest_run?.status || "PASS")}</div>
      <span>${escapeHtml(contract.asset_id)} - ${escapeHtml((contract.checks || []).length)} checks</span>
    </article>
  `).join("") || '<div class="empty-state">No data contracts</div>';
  el("opsBackfillList").innerHTML = (state.ops.backfills || []).map((plan) => `
    <div class="list-item">
      <strong>${escapeHtml(plan.display_name)}</strong>
      <span>${escapeHtml(plan.status)} - ${escapeHtml((plan.pipeline_ids || []).join(", "))}</span>
      <button class="btn small" type="button" data-run-backfill="${escapeHtml(plan.id)}">Run</button>
    </div>
  `).join("") || '<div class="empty-state compact-empty">No backfill plans</div>';
}

function renderOpsInbox() {
  el("opsInboxList").innerHTML = (state.ops.inbox || []).map((note) => `
    <div class="candidate-row">
      <div>
        <strong>${escapeHtml(note.title)}</strong>
        <span>${escapeHtml(note.status)} - ${escapeHtml(note.source)} - ${escapeHtml(note.severity)}</span>
      </div>
      <button class="btn small" type="button" data-ack-note="${escapeHtml(note.id)}">Ack</button>
    </div>
  `).join("") || '<div class="empty-state">No inbox notifications</div>';
}

function statusBadge(status = "PASS") {
  const value = String(status || "PASS");
  const lower = value.toLowerCase();
  const cls = ["critical", "fail"].includes(lower) ? "critical"
    : ["high", "warn", "warning", "medium", "open", "pending"].includes(lower) ? "medium"
    : lower === "muted" ? "muted"
    : "low";
  return `<span class="risk-badge ${cls}">${escapeHtml(value)}</span>`;
}

async function createOpsAlertRule() {
  const payload = {
    display_name: el("opsAlertRuleNameInput").value.trim() || "High severity operations",
    source: el("opsAlertRuleSourceInput").value.trim() || null,
    event_type: el("opsAlertRuleEventInput").value.trim() || null,
    min_severity: el("opsAlertRuleSeveritySelect").value,
    expression: parseJsonValue(el("opsAlertRuleExpressionInput").value, {}, "Alert expression")
  };
  state.ops.output = await api("/ops/alert-rules", { method: "POST", body: JSON.stringify(payload) });
  await refreshOpsWorkspace();
  showToast("Alert rule created");
}

async function evaluateOpsAlerts() {
  state.ops.output = await api("/ops/alerts/evaluate", { method: "POST", body: JSON.stringify({ limit: 500 }) });
  await refreshOpsWorkspace();
  showToast(`${state.ops.output.created_alerts} alerts created`);
}

async function createOpsIncident() {
  const payload = {
    display_name: el("opsIncidentNameInput").value.trim() || "Operations Incident",
    description: el("opsIncidentDescriptionInput").value.trim() || null,
    severity: el("opsIncidentSeveritySelect").value,
    owner: el("opsIncidentOwnerInput").value.trim() || null,
    linked_objects: parseJsonValue(el("opsIncidentObjectsInput").value, [], "Incident linked objects")
  };
  state.ops.output = await api("/ops/incidents", { method: "POST", body: JSON.stringify(payload) });
  state.ops.selectedIncidentId = state.ops.output.id;
  await refreshOpsWorkspace();
  showToast("Incident created");
}

async function createOpsRunbook() {
  const payload = {
    display_name: el("opsRunbookNameInput").value.trim() || "Risk Triage Runbook",
    description: "Created from Ops workspace",
    steps: parseJsonValue(el("opsRunbookStepsInput").value, [], "Runbook steps")
  };
  state.ops.output = await api("/ops/runbooks", { method: "POST", body: JSON.stringify(payload) });
  state.ops.selectedRunbookId = state.ops.output.id;
  await refreshOpsWorkspace();
  showToast("Runbook created");
}

async function executeOpsRunbook() {
  const runbookId = state.ops.selectedRunbookId || el("opsRunbookSelect").value;
  if (!runbookId) throw new Error("Choose a runbook");
  const result = await api(`/ops/runbooks/${encodeURIComponent(runbookId)}/execute`, {
    method: "POST",
    body: JSON.stringify({
      incident_id: state.ops.selectedIncidentId || el("opsIncidentSelect").value || null,
      inputs: parseJsonValue(el("opsRunbookInputsInput").value, {}, "Runbook inputs"),
      actor: "workspace"
    })
  });
  state.ops.output = { runbook: result };
  await refreshOpsWorkspace();
  showToast(`Runbook ${result.status}`);
}

async function createDataContract() {
  const payload = {
    display_name: el("opsContractNameInput").value.trim() || "Dataset Contract",
    asset_id: el("opsContractAssetSelect").value,
    checks: parseJsonValue(el("opsContractChecksInput").value, [], "Contract checks")
  };
  state.ops.output = await api("/reliability/data-contracts", { method: "POST", body: JSON.stringify(payload) });
  state.ops.selectedContractId = state.ops.output.id;
  await refreshOpsWorkspace();
  showToast("Data contract created");
}

async function runSelectedDataContract() {
  const contractId = state.ops.selectedContractId || el("opsContractSelect").value;
  if (!contractId) throw new Error("Choose a data contract");
  state.ops.output = await api(`/reliability/data-contracts/${encodeURIComponent(contractId)}/run`, {
    method: "POST",
    body: JSON.stringify({ asset_id: el("opsContractRunAssetSelect").value || null })
  });
  await refreshOpsWorkspace();
  showToast(`Contract ${state.ops.output.status}`);
}

async function analyzeOpsLineageImpact() {
  state.ops.output = await api("/reliability/lineage-impact", {
    method: "POST",
    body: JSON.stringify({
      resource_kind: el("opsImpactKindSelect").value,
      resource_id: el("opsImpactResourceInput").value.trim(),
      direction: el("opsImpactDirectionSelect").value
    })
  });
  await refreshOpsWorkspace();
  showToast("Lineage impact analyzed");
}

async function createOpsBackfill() {
  const pipelineId = el("opsBackfillPipelineSelect").value;
  if (!pipelineId) throw new Error("Choose a pipeline");
  state.ops.output = await api("/reliability/backfills", {
    method: "POST",
    body: JSON.stringify({
      display_name: el("opsBackfillNameInput").value.trim() || "Pipeline Backfill",
      pipeline_ids: [pipelineId],
      asset_ids: []
    })
  });
  await refreshOpsWorkspace();
  showToast("Backfill plan created");
}

async function runOpsBackfill(planId) {
  state.ops.output = await api(`/reliability/backfills/${encodeURIComponent(planId)}/run`, {
    method: "POST",
    body: JSON.stringify({ actor: "workspace" })
  });
  await refreshOpsWorkspace();
  showToast(`Backfill ${state.ops.output.status}`);
}

async function ackOpsNotification(notificationId) {
  state.ops.output = await api(`/ops/inbox/${encodeURIComponent(notificationId)}/ack`, { method: "POST" });
  await refreshOpsWorkspace();
  showToast("Notification acknowledged");
}

function setInvestigationsTab(tabName) {
  state.investigations.activeTab = tabName;
  document.querySelectorAll("[data-investigation-tab]").forEach((button) => {
    button.classList.toggle("active", button.dataset.investigationTab === tabName);
  });
  document.querySelectorAll("[data-investigation-panel]").forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.investigationPanel === tabName);
  });
  const labels = {
    board: "Case Board",
    graph: "Entity Graph",
    evidence: "Evidence",
    timeline: "Timeline",
    hypotheses: "Hypotheses",
    report: "Report"
  };
  if (el("investigationTitle")) el("investigationTitle").textContent = labels[tabName] || "Investigations";
}

async function refreshInvestigationsWorkspace() {
  await refreshLogicCatalogs();
  state.investigations.list = await api("/investigations").catch(() => []);
  state.investigations.selectedId = state.investigations.selectedId || state.investigations.list[0]?.id || "";
  if (state.investigations.selectedId) {
    await loadSelectedInvestigation(state.investigations.selectedId, false).catch(() => {});
  }
  renderInvestigationsWorkspace();
}

async function loadSelectedInvestigation(investigationId, render = true) {
  state.investigations.selectedId = investigationId;
  state.investigations.detail = await api(`/investigations/${encodeURIComponent(investigationId)}`);
  state.investigations.graph = await api(`/investigations/${encodeURIComponent(investigationId)}/graph`).catch(() => null);
  state.investigations.timeline = await api(`/investigations/${encodeURIComponent(investigationId)}/timeline`).catch(() => null);
  if (render) renderInvestigationsWorkspace();
}

function renderInvestigationsWorkspace() {
  setInvestigationsTab(state.investigations.activeTab || "board");
  renderInvestigationList();
  renderInvestigationDetail();
  renderInvestigationGraph();
  renderInvestigationEvidence();
  renderInvestigationTimeline();
  renderInvestigationHypotheses();
  renderInvestigationReport();
}

function renderInvestigationList() {
  el("investigationList").innerHTML = (state.investigations.list || []).map((item) => `
    <button class="builder-list-button ${item.id === state.investigations.selectedId ? "selected" : ""}" type="button" data-investigation-id="${escapeHtml(item.id)}">
      <strong>${escapeHtml(item.display_name)}</strong>
      <span>${escapeHtml(item.status)} - ${escapeHtml((item.object_refs || []).length)} objects</span>
    </button>
  `).join("") || '<div class="empty-state compact-empty">No investigations</div>';
}

function renderInvestigationDetail() {
  const detail = state.investigations.detail;
  if (!detail) {
    el("investigationBoard").innerHTML = '<div class="empty-state">Create or select an investigation</div>';
    el("investigationOutput").textContent = "";
    return;
  }
  const risks = Object.values(detail.risk || {}).filter(Boolean);
  const highRisk = risks.filter((risk) => ["high", "critical"].includes(risk.band));
  el("investigationBoard").innerHTML = `
    <div class="modelops-grid">
      <article class="modelops-card"><strong>${escapeHtml(detail.display_name)}</strong><span>${escapeHtml(detail.status)} - ${escapeHtml(detail.owner || "unowned")}</span></article>
      <article class="modelops-card"><strong>Objects</strong><span>${escapeHtml((detail.objects || []).length)}</span></article>
      <article class="modelops-card"><strong>Evidence</strong><span>${escapeHtml((detail.evidence || []).length)}</span></article>
      <article class="modelops-card"><strong>High risk</strong><span>${escapeHtml(highRisk.length)}</span></article>
    </div>
  `;
  el("investigationOutput").textContent = compactJson({
    id: detail.id,
    objects: detail.objects,
    high_risk: highRisk.map((risk) => ({ band: risk.band, score: risk.score, explanation: risk.explanation }))
  });
}

function renderInvestigationGraph() {
  const graph = state.investigations.graph;
  el("investigationGraph").innerHTML = graph ? `
    <div class="graph-strip">
      ${(graph.nodes || []).map((node) => `<span>${escapeHtml(node.kind)}:${escapeHtml(node.label || node.id)}</span>`).join("")}
    </div>
    <pre class="mini-output tall">${escapeHtml(compactJson(graph))}</pre>
  ` : '<div class="empty-state">No graph loaded</div>';
}

function renderInvestigationEvidence() {
  const evidence = state.investigations.detail?.evidence || [];
  el("investigationEvidenceList").innerHTML = evidence.map((item) => `
    <article class="modelops-card">
      <strong>${escapeHtml(item.title)}</strong>
      <span>${escapeHtml(item.source || "local")} - ${escapeHtml((item.tags || []).join(", "))}</span>
      <pre class="mini-output">${escapeHtml(compactJson(item.payload || {}))}</pre>
    </article>
  `).join("") || '<div class="empty-state">No evidence</div>';
}

function renderInvestigationTimeline() {
  const rows = state.investigations.timeline?.timeline || [];
  el("investigationTimeline").innerHTML = rows.length ? `
    <div class="timeline-list">
      ${rows.map((item) => `<article><strong>${escapeHtml(item.title || item.kind)}</strong><span>${escapeHtml(item.kind)} - ${new Date((item.at || 0) * 1000).toLocaleString()}</span></article>`).join("")}
    </div>
  ` : '<div class="empty-state">No timeline loaded</div>';
}

function renderInvestigationHypotheses() {
  const hypotheses = state.investigations.detail?.hypotheses || [];
  el("investigationHypothesisList").innerHTML = hypotheses.map((item) => `
    <article class="modelops-card">
      <div class="decision-card-head"><strong>${escapeHtml(item.statement)}</strong>${statusBadge(item.status)}</div>
      <span>confidence ${escapeHtml(item.confidence)} - evidence ${(item.linked_evidence_ids || []).length}</span>
    </article>
  `).join("") || '<div class="empty-state">No hypotheses</div>';
}

function renderInvestigationReport() {
  const reports = state.investigations.detail?.reports || [];
  const latest = state.investigations.output?.report || reports[0];
  el("investigationReport").innerHTML = latest ? `<pre class="mini-output tall">${escapeHtml(latest.body || compactJson(latest))}</pre>` : '<div class="empty-state">No report generated</div>';
}

async function createInvestigation() {
  const payload = {
    display_name: el("investigationNameInput").value.trim() || "Operations Investigation",
    description: el("investigationDescriptionInput").value.trim() || null,
    owner: el("investigationOwnerInput").value.trim() || null,
    object_refs: parseJsonValue(el("investigationObjectRefsInput").value, [], "Investigation object refs")
  };
  const created = await api("/investigations", { method: "POST", body: JSON.stringify(payload) });
  state.investigations.selectedId = created.id;
  await refreshInvestigationsWorkspace();
  showToast("Investigation created");
}

async function addInvestigationEvidence() {
  const investigationId = state.investigations.selectedId;
  if (!investigationId) throw new Error("Select an investigation");
  await api(`/investigations/${encodeURIComponent(investigationId)}/evidence`, {
    method: "POST",
    body: JSON.stringify({
      title: el("evidenceTitleInput").value.trim() || "Evidence",
      source: el("evidenceSourceInput").value.trim() || "workspace",
      object_refs: parseJsonValue(el("evidenceObjectRefsInput").value, [], "Evidence object refs"),
      payload: parseJsonValue(el("evidencePayloadInput").value, {}, "Evidence payload"),
      tags: splitCsv(el("evidenceTagsInput").value)
    })
  });
  await loadSelectedInvestigation(investigationId);
  setInvestigationsTab("evidence");
  showToast("Evidence added");
}

async function addInvestigationHypothesis() {
  const investigationId = state.investigations.selectedId;
  if (!investigationId) throw new Error("Select an investigation");
  await api(`/investigations/${encodeURIComponent(investigationId)}/hypotheses`, {
    method: "POST",
    body: JSON.stringify({
      statement: el("hypothesisStatementInput").value.trim() || "Operational risk is linked to the selected object",
      confidence: Number(el("hypothesisConfidenceInput").value || 50),
      linked_evidence_ids: splitCsv(el("hypothesisEvidenceInput").value)
    })
  });
  await loadSelectedInvestigation(investigationId);
  setInvestigationsTab("hypotheses");
  showToast("Hypothesis added");
}

async function generateInvestigationReport() {
  const investigationId = state.investigations.selectedId;
  if (!investigationId) throw new Error("Select an investigation");
  const report = await api(`/investigations/${encodeURIComponent(investigationId)}/report`, {
    method: "POST",
    body: JSON.stringify({ title: el("reportTitleInput").value.trim() || undefined })
  });
  state.investigations.output = { report };
  await loadSelectedInvestigation(investigationId, false);
  setInvestigationsTab("report");
  renderInvestigationsWorkspace();
  showToast("Report generated");
}

function splitCsv(value) {
  return String(value || "").split(",").map((item) => item.trim()).filter(Boolean);
}

function setDecisionTab(tabName) {
  state.decision.activeTab = tabName;
  document.querySelectorAll("[data-decision-tab]").forEach((button) => {
    button.classList.toggle("active", button.dataset.decisionTab === tabName);
  });
  document.querySelectorAll("[data-decision-panel]").forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.decisionPanel === tabName);
  });
  const labels = {
    risk: "Risk Board",
    explain: "Explain Object",
    timeline: "Timeline",
    entity: "Entity Resolution",
    scenario: "Scenario Simulator",
    agent: "Agent Plan"
  };
  if (el("decisionTitle")) el("decisionTitle").textContent = labels[tabName] || "Decision Intelligence";
}

async function refreshDecisionWorkspace() {
  await refreshLogicCatalogs();
  await loadAgents();
  const objectTypeId = el("decisionObjectTypeSelect")?.value || firstObjectType();
  fillSelect(el("decisionObjectTypeSelect"), state.catalogs.objectTypes.map((obj) => ({
    value: obj.id,
    label: obj.display_name ? `${obj.display_name} (${obj.id})` : obj.id
  })), objectTypeId || firstObjectType(), "Choose object type");
  fillSelect(el("decisionAgentSelect"), state.catalogs.agents.map((agent) => ({
    value: agent.id,
    label: agent.display_name || agent.id
  })), el("decisionAgentSelect")?.value || "", "Choose agent");
  await loadDecisionRules();
  if (!state.decision.evaluation) await runDecisionEvaluation(false).catch(() => renderDecisionWorkspace());
  renderDecisionWorkspace();
}

async function loadDecisionRules() {
  const objectTypeId = el("decisionObjectTypeSelect")?.value || firstObjectType();
  if (!objectTypeId) return;
  const [rules, scorecards] = await Promise.allSettled([
    api(`/decision/rules?object_type_id=${encodeURIComponent(objectTypeId)}`),
    api(`/decision/scorecards?object_type_id=${encodeURIComponent(objectTypeId)}`)
  ]);
  state.decision.rules = rules.status === "fulfilled" ? rules.value : [];
  state.decision.scorecards = scorecards.status === "fulfilled" ? scorecards.value : [];
}

function renderDecisionWorkspace() {
  setDecisionTab(state.decision.activeTab || "risk");
  renderDecisionRules();
  renderDecisionScorecards();
  renderDecisionRiskBoard();
  renderDecisionExplanation();
  renderDecisionTimeline();
  renderEntityCandidates();
  el("decisionScenarioOutput").textContent = state.decision.scenario ? compactJson(state.decision.scenario) : "No scenario run yet";
  el("decisionAgentPlan").textContent = state.decision.agentRun ? compactJson(state.decision.agentRun) : "No agent run yet";
}

function renderDecisionRules() {
  const rules = state.decision.rules || [];
  el("decisionRuleList").innerHTML = rules.map((rule) => `
    <div class="list-item">
      <strong>${escapeHtml(rule.display_name || rule.id)}</strong>
      <span>${escapeHtml(rule.severity || "info")} - ${escapeHtml(rule.id)}</span>
    </div>
  `).join("") || '<div class="empty-state compact-empty">No rules. Bootstrap defaults or create rules through the API.</div>';
}

function renderDecisionScorecards() {
  const scorecards = state.decision.scorecards || [];
  el("decisionScorecardList").innerHTML = scorecards.map((scorecard) => `
    <div class="list-item">
      <strong>${escapeHtml(scorecard.display_name || scorecard.id)}</strong>
      <span>${escapeHtml((scorecard.features || []).length)} features</span>
    </div>
  `).join("") || '<div class="empty-state compact-empty">No scorecards</div>';
}

function renderDecisionRiskBoard() {
  const findings = state.decision.evaluation?.findings || [];
  el("decisionSummary").textContent = state.decision.evaluation
    ? `${state.decision.evaluation.object_count} objects evaluated`
    : "Evaluate ontology objects against local deterministic rules";
  if (!findings.length) {
    el("decisionRiskBoard").innerHTML = '<div class="empty-state">No evaluated objects</div>';
    el("decisionOutput").textContent = state.decision.evaluation ? compactJson(state.decision.evaluation) : "";
    return;
  }
  const sorted = [...findings].sort((a, b) => (b.risk?.score || 0) - (a.risk?.score || 0));
  el("decisionRiskBoard").innerHTML = sorted.map((finding) => {
    const props = finding.object?.properties || {};
    const drivers = (finding.risk?.drivers || []).slice(0, 3).map((driver) => `<span>${escapeHtml(driver.feature || driver.rule_id || "driver")}</span>`).join("");
    return `
      <article class="decision-card" data-decision-object="${escapeHtml(finding.object_id)}">
        <div class="decision-card-head">
          <strong>${escapeHtml(props.name || props.title || finding.object_id)}</strong>
          ${renderRiskBadge(finding.risk)}
        </div>
        <span>${escapeHtml(finding.object_id)} - ${escapeHtml(props.status || props.criticality || finding.object_type_id)}</span>
        <div class="driver-row">${drivers || "<span>No drivers</span>"}</div>
      </article>
    `;
  }).join("");
  el("decisionOutput").textContent = compactJson({
    status: state.decision.evaluation.status,
    object_count: state.decision.evaluation.object_count,
    high_risk: sorted.filter((item) => ["high", "critical"].includes(item.risk?.band)).map((item) => item.object_id)
  });
}

function renderDecisionExplanation() {
  const explanation = state.decision.explanation;
  if (!explanation) {
    el("decisionExplanation").innerHTML = '<div class="empty-state">Select or enter an object ID, then explain it</div>';
    return;
  }
  const risk = explanation.risk || {};
  el("decisionExplanation").innerHTML = `
    <div class="decision-explain-head">
      <div>
        <strong>${escapeHtml(explanation.object?.id)}</strong>
        <span>${escapeHtml(explanation.object?.object_type_id)}</span>
      </div>
      ${renderRiskBadge(risk)}
    </div>
    <p>${escapeHtml(explanation.explanation || risk.explanation || "")}</p>
    <div class="driver-list">
      ${(risk.drivers || []).map((driver) => `<div><strong>${escapeHtml(driver.feature || driver.rule_id || "driver")}</strong><span>weight ${escapeHtml(driver.weight ?? 0)}</span></div>`).join("") || '<div>No active drivers matched</div>'}
    </div>
    <pre class="mini-output">${escapeHtml(compactJson({
      recommended_actions: explanation.recommended_actions,
      duplicate_warnings: explanation.duplicate_warnings,
      temporal_summary: explanation.temporal_summary
    }))}</pre>
  `;
  el("decisionOutput").textContent = compactJson(explanation);
}

function renderDecisionTimeline() {
  const rows = state.decision.timeline?.timeline || [];
  if (!rows.length) {
    el("decisionTimeline").innerHTML = '<div class="empty-state">No timeline loaded</div>';
    return;
  }
  el("decisionTimeline").innerHTML = `
    <div class="timeline-list">
      ${rows.map((item) => `
        <article>
          <strong>${escapeHtml(item.event_type)}</strong>
          <span>seq ${escapeHtml(item.seq)} - ${new Date((item.created_at || 0) * 1000).toLocaleString()}</span>
          <pre class="mini-output">${escapeHtml(compactJson({ properties: item.properties, lineage: item.lineage }))}</pre>
        </article>
      `).join("")}
    </div>
  `;
}

function renderEntityCandidates() {
  const candidates = state.decision.candidates || [];
  el("entityCandidateList").innerHTML = candidates.map((candidate) => `
    <div class="candidate-row">
      <div>
        <strong>${escapeHtml(candidate.object_ids?.join(" + ") || candidate.id)}</strong>
        <span>confidence ${escapeHtml(candidate.score)} - ${escapeHtml(candidate.status)}</span>
      </div>
      <div class="button-row">
        <button class="btn small" data-accept-candidate="${escapeHtml(candidate.id)}" type="button">Accept</button>
        <button class="btn small" data-reject-candidate="${escapeHtml(candidate.id)}" type="button">Reject</button>
      </div>
    </div>
  `).join("") || '<div class="empty-state compact-empty">No candidate queue</div>';
}

async function bootstrapDecisionRules() {
  const objectTypeId = el("decisionObjectTypeSelect").value || firstObjectType();
  await api("/decision/bootstrap", {
    method: "POST",
    body: JSON.stringify({ object_type_id: objectTypeId })
  });
  await loadDecisionRules();
  renderDecisionWorkspace();
  showToast("Decision rules bootstrapped");
}

async function runDecisionEvaluation(notify = true) {
  const objectTypeId = el("decisionObjectTypeSelect").value || firstObjectType();
  if (!objectTypeId) return;
  state.decision.evaluation = await api("/decision/evaluate", {
    method: "POST",
    body: JSON.stringify({ object_type_id: objectTypeId, filters: {}, limit: 250, persist_run: true })
  });
  if (!el("decisionObjectIdInput").value && state.decision.evaluation.findings?.[0]) {
    el("decisionObjectIdInput").value = state.decision.evaluation.findings[0].object_id;
  }
  setDecisionTab("risk");
  renderDecisionWorkspace();
  if (notify) showToast(`${state.decision.evaluation.object_count} objects evaluated`);
}

async function explainDecisionObject() {
  const objectTypeId = el("decisionObjectTypeSelect").value || firstObjectType();
  const objectId = el("decisionObjectIdInput").value.trim();
  if (!objectTypeId || !objectId) {
    showToast("Enter an object type and object ID");
    return;
  }
  state.decision.explanation = await api(`/decision/objects/${encodeURIComponent(objectTypeId)}/${encodeURIComponent(objectId)}/explain`);
  setDecisionTab("explain");
  renderDecisionWorkspace();
}

async function loadDecisionTimeline() {
  const objectTypeId = el("decisionObjectTypeSelect").value || firstObjectType();
  const objectId = el("decisionObjectIdInput").value.trim();
  if (!objectTypeId || !objectId) {
    showToast("Enter an object type and object ID");
    return;
  }
  state.decision.timeline = await api(`/temporal/objects/${encodeURIComponent(objectTypeId)}/${encodeURIComponent(objectId)}/timeline`);
  setDecisionTab("timeline");
  renderDecisionWorkspace();
}

async function runEntityResolution() {
  const objectTypeId = el("decisionObjectTypeSelect").value || firstObjectType();
  const fields = String(el("entityFieldsInput").value || "").split(",").map((item) => item.trim()).filter(Boolean);
  state.decision.entityJob = await api("/entity-resolution/jobs", {
    method: "POST",
    body: JSON.stringify({ object_type_id: objectTypeId, fields, threshold: 70, limit: 1000 })
  });
  state.decision.candidates = state.decision.entityJob.candidates || [];
  setDecisionTab("entity");
  renderDecisionWorkspace();
  showToast(`${state.decision.candidates.length} candidates`);
}

async function refreshEntityCandidates() {
  if (!state.decision.entityJob?.id) return;
  const result = await api(`/entity-resolution/jobs/${encodeURIComponent(state.decision.entityJob.id)}/candidates`);
  state.decision.candidates = result.candidates || [];
  renderDecisionWorkspace();
}

async function acceptEntityCandidate(candidateId) {
  await api(`/entity-resolution/candidates/${encodeURIComponent(candidateId)}/accept`, {
    method: "POST",
    body: JSON.stringify({ actor: "workspace" })
  });
  await refreshEntityCandidates();
}

async function rejectEntityCandidate(candidateId) {
  await api(`/entity-resolution/candidates/${encodeURIComponent(candidateId)}/reject`, {
    method: "POST",
    body: JSON.stringify({ actor: "workspace", reason: "Rejected in Decision workspace" })
  });
  await refreshEntityCandidates();
}

async function runDecisionScenario() {
  const selectedId = el("decisionObjectIdInput").value.trim();
  const seeds = String(el("scenarioSeedsInput").value || selectedId).split(",").map((item) => item.trim()).filter(Boolean);
  const overrides = parseJsonValue(el("scenarioOverridesInput").value, {}, "Scenario overrides");
  state.decision.scenario = await api("/decision/scenarios", {
    method: "POST",
    body: JSON.stringify({
      display_name: `Workspace Scenario ${new Date().toLocaleTimeString()}`,
      seed_object_ids: seeds,
      overrides,
      propagation_rules: []
    })
  });
  setDecisionTab("scenario");
  renderDecisionWorkspace();
  showToast("Scenario complete");
}

async function runDecisionAgent() {
  const agentId = el("decisionAgentSelect").value;
  if (!agentId) {
    showToast("Choose an agent");
    return;
  }
  state.decision.agentRun = await api(`/agents/${encodeURIComponent(agentId)}/sessions`, {
    method: "POST",
    body: JSON.stringify({ user_prompt: el("decisionAgentPrompt").value, max_context_objects: 8 })
  });
  setDecisionTab("agent");
  renderDecisionWorkspace();
}

function defaultPipelineNodeConfig(type) {
  const draft = state.pipeline.draft || defaultPipelineDraft();
  if (type === "input_dataset") return { asset_id: state.datasets[0]?.id || "" };
  if (type === "dataset_output" || type === "output_dataset") return { asset_id: `${draft.display_name || "pipeline"}_output`.toLowerCase().replace(/[^a-z0-9_]+/g, "_") };
  if (type === "filter") return { filters: {} };
  if (type === "project" || type === "select") return { columns: [] };
  if (type === "rename") return { mapping: {} };
  if (type === "join") return { right_asset_id: state.datasets[1]?.id || "", left_key: "", right_key: "", join_type: "inner" };
  if (type === "union") return { asset_id: state.datasets[1]?.id || "" };
  if (type === "aggregate") return { group_by: [], metrics: [{ operation: "count", alias: "n" }] };
  if (type === "sort") return { field: "", direction: "asc" };
  if (type === "limit") return { limit: 100 };
  if (type === "unique_id") return { target_field: "id", source_fields: [] };
  if (type === "llm_assist") return { prompt: "summarize", source_fields: [], output_field: "llm_summary" };
  if (type === "ontology_output") return { object_type_id: state.catalogs.objectTypes[0]?.id || "", id_field: "id", mapping: {} };
  return {};
}

function addPipelineNode(type, position = null) {
  const draft = state.pipeline.draft || defaultPipelineDraft();
  const id = `${type}_${draft.nodes.length + 1}`;
  const config = defaultPipelineNodeConfig(type);
  const previous = draft.nodes[draft.nodes.length - 1];
  const catalog = state.pipeline.nodeTypes?.length ? state.pipeline.nodeTypes : PIPELINE_NODE_TYPES;
  draft.nodes.push({
    id,
    type,
    label: catalog.find((node) => node.type === type)?.label || type,
    position: position || { x: 80 + (draft.nodes.length % 4) * 260, y: 90 + Math.floor(draft.nodes.length / 4) * 150 },
    config
  });
  if (previous) draft.edges.push({ source: previous.id, target: id });
  state.pipeline.activeNodeId = id;
  state.pipeline.activeEdgeId = "";
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
    state.objectExplorer.riskById = {};
    const ids = (state.objectExplorer.query.objects || []).map((obj) => obj.id);
    if (ids.length) {
      try {
        const decision = await api("/decision/evaluate", {
          method: "POST",
          body: JSON.stringify({ object_type_id: objectTypeId, object_ids: ids, limit: ids.length, persist_run: false })
        });
        state.objectExplorer.riskById = Object.fromEntries((decision.findings || []).map((item) => [item.object_id, item.risk]));
      } catch (_) {
        state.objectExplorer.riskById = {};
      }
    }
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
    <table><thead><tr><th></th><th>ID</th><th>Risk</th>${columns.map((column) => `<th>${escapeHtml(column)}</th>`).join("")}</tr></thead>
    <tbody>${query.objects.map((obj) => `
      <tr data-explorer-object-id="${escapeHtml(obj.id)}" class="${state.objectExplorer.selectedObjectId === obj.id ? "selected" : ""}">
        <td><input type="checkbox" data-explorer-select-id="${escapeHtml(obj.id)}"${state.objectExplorer.selectedIds.includes(obj.id) ? " checked" : ""} /></td>
        <td><strong>${escapeHtml(obj.id)}</strong></td>
        <td>${renderRiskBadge(state.objectExplorer.riskById[obj.id])}</td>
        ${columns.map((column) => `<td>${escapeHtml(runtimeCellValue(obj, column))}</td>`).join("")}
      </tr>
    `).join("")}</tbody></table>
  `;
}

function renderRiskBadge(risk) {
  if (!risk) return '<span class="risk-badge muted">none</span>';
  return `<span class="risk-badge ${escapeHtml(risk.band || "low")}">${escapeHtml(risk.band || "low")} ${escapeHtml(risk.score ?? 0)}</span>`;
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
    let explanation = null;
    try {
      explanation = await api(`/decision/objects/${encodeURIComponent(objectTypeId)}/${encodeURIComponent(objectId)}/explain`);
    } catch (_) {
      explanation = null;
    }
    el("explorerObjectPreview").className = "object-profile";
    renderExplorerProfile(profile, explanation);
  } catch (error) {
    showToast(error.message);
  }
  renderExplorerResults();
}

function renderExplorerProfile(profile, explanation = null) {
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
  const risk = explanation?.risk;
  el("explorerObjectPreview").innerHTML = `
    ${entries.map(([key, value]) => `<div class="kv"><span>${escapeHtml(key)}</span><strong>${escapeHtml(value)}</strong></div>`).join("")}
    ${risk ? `<div class="decision-inline"><strong>${renderRiskBadge(risk)}</strong><span>${escapeHtml(risk.explanation || "")}</span></div>` : ""}
  `;
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
  const configField = event.target.dataset.pipelineConfigField;
  if (!field && !configField) return;
  const node = state.pipeline.draft?.nodes?.find((item) => item.id === state.pipeline.activeNodeId);
  if (!node) return;
  try {
    if (field === "config") {
      node.config = parseJsonValue(event.target.value, {}, "Node config");
    } else if (field === "asset_id") {
      node.config = { ...(node.config || {}), asset_id: event.target.value };
    } else if (configField) {
      const valueType = event.target.dataset.configType || "text";
      let value = event.target.value;
      if (valueType === "json") value = parseJsonValue(value, configField === "metrics" ? [] : {}, `${configField} JSON`);
      if (valueType === "csv") value = value.split(",").map((item) => item.trim()).filter(Boolean);
      if (valueType === "number") value = Number(value);
      node.config = { ...(node.config || {}), [configField]: value };
    } else {
      node[field] = event.target.value;
      if (field === "type") {
        node.config = defaultPipelineNodeConfig(event.target.value);
        node.label = (state.pipeline.nodeTypes?.length ? state.pipeline.nodeTypes : PIPELINE_NODE_TYPES).find((item) => item.type === event.target.value)?.label || event.target.value;
      }
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
  if (type === "explain_object") {
    return { type, object_type_id: firstObjectType(), object_id: "", output: "explanation" };
  }
  if (type === "score_risk") {
    return { type, object_type_id: firstObjectType(), object_id: "", scorecard_ids: "", output: "risk" };
  }
  if (type === "run_scenario") {
    return { type, seed_object_ids: "", overrides: "{}", propagation_rules: "[]", output: "scenario" };
  }
  if (type === "create_incident") {
    return { type, display_name: "Logic Incident", description: "$prompt", severity: "medium", linked_objects: "[]", output: "incident" };
  }
  if (type === "evaluate_alert_rules") {
    return { type, source: "", event_type: "", status: "", limit: 500, output: "alerts" };
  }
  if (type === "run_runbook") {
    return { type, runbook_id: "", incident_id: "", inputs: "{}", output: "runbook" };
  }
  if (type === "run_data_contract") {
    return { type, contract_id: "", asset_id: "", output: "data_contract" };
  }
  if (type === "analyze_lineage_impact") {
    return { type, resource_kind: "dataset", resource_id: "", direction: "downstream", max_depth: 8, output: "lineage_impact" };
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
  if (block.type === "explain_object") return renderDecisionLogicBlock(block, "explain");
  if (block.type === "score_risk") return renderDecisionLogicBlock(block, "score");
  if (block.type === "run_scenario") return renderScenarioLogicBlock(block);
  if (block.type === "create_incident") return renderCreateIncidentBlock(block);
  if (block.type === "evaluate_alert_rules") return renderEvaluateAlertsBlock(block);
  if (block.type === "run_runbook") return renderRunbookLogicBlock(block);
  if (block.type === "run_data_contract") return renderDataContractLogicBlock(block);
  if (block.type === "analyze_lineage_impact") return renderLineageImpactLogicBlock(block);
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

function renderDecisionLogicBlock(block, mode) {
  return `
    <div class="block-grid three">
      <label class="field"><span>Object Type</span><select data-block-field="object_type_id">${objectTypeOptions(block.object_type_id)}</select></label>
      <label class="field"><span>Object ID</span><input data-block-field="object_id" value="${escapeHtml(block.object_id || "")}" placeholder="$object_id or asset_1" /></label>
      <label class="field"><span>Output Variable</span><input data-block-field="output" value="${escapeHtml(block.output || (mode === "score" ? "risk" : "explanation"))}" /></label>
      ${mode === "score" ? `<label class="field"><span>Scorecard IDs</span><input data-block-field="scorecard_ids" value="${escapeHtml(block.scorecard_ids || "")}" placeholder="optional comma list" /></label>` : ""}
    </div>
  `;
}

function renderScenarioLogicBlock(block) {
  return `
    <div class="block-grid">
      <label class="field"><span>Seed Object IDs</span><input data-block-field="seed_object_ids" value="${escapeHtml(block.seed_object_ids || "")}" placeholder="asset_1, asset_2 or $ids" /></label>
      <label class="field"><span>Output Variable</span><input data-block-field="output" value="${escapeHtml(block.output || "scenario")}" /></label>
    </div>
    <label class="field"><span>Overrides JSON</span><textarea rows="4" data-block-field="overrides">${escapeHtml(block.overrides || "{}")}</textarea></label>
    <label class="field"><span>Propagation Rules JSON</span><textarea rows="3" data-block-field="propagation_rules">${escapeHtml(block.propagation_rules || "[]")}</textarea></label>
  `;
}

function renderCreateIncidentBlock(block) {
  return `
    <div class="block-grid three">
      <label class="field"><span>Name</span><input data-block-field="display_name" value="${escapeHtml(block.display_name || "Logic Incident")}" /></label>
      <label class="field"><span>Severity</span><select data-block-field="severity">${optionList(["info", "low", "medium", "high", "critical"], block.severity || "medium")}</select></label>
      <label class="field"><span>Output Variable</span><input data-block-field="output" value="${escapeHtml(block.output || "incident")}" /></label>
    </div>
    <label class="field"><span>Description</span><textarea rows="3" data-block-field="description">${escapeHtml(block.description || "$prompt")}</textarea></label>
    <label class="field"><span>Linked Objects JSON</span><textarea rows="3" data-block-field="linked_objects">${escapeHtml(block.linked_objects || "[]")}</textarea></label>
  `;
}

function renderEvaluateAlertsBlock(block) {
  return `
    <div class="block-grid three">
      <label class="field"><span>Source</span><input data-block-field="source" value="${escapeHtml(block.source || "")}" placeholder="optional" /></label>
      <label class="field"><span>Event Type</span><input data-block-field="event_type" value="${escapeHtml(block.event_type || "")}" placeholder="optional" /></label>
      <label class="field"><span>Status</span><input data-block-field="status" value="${escapeHtml(block.status || "")}" placeholder="optional" /></label>
      <label class="field"><span>Limit</span><input type="number" data-block-field="limit" value="${escapeHtml(block.limit || 500)}" /></label>
      <label class="field"><span>Output Variable</span><input data-block-field="output" value="${escapeHtml(block.output || "alerts")}" /></label>
    </div>
  `;
}

function renderRunbookLogicBlock(block) {
  return `
    <div class="block-grid three">
      <label class="field"><span>Runbook ID</span><input data-block-field="runbook_id" value="${escapeHtml(block.runbook_id || "")}" /></label>
      <label class="field"><span>Incident ID</span><input data-block-field="incident_id" value="${escapeHtml(block.incident_id || "")}" placeholder="optional or $incident.id" /></label>
      <label class="field"><span>Output Variable</span><input data-block-field="output" value="${escapeHtml(block.output || "runbook")}" /></label>
    </div>
    <label class="field"><span>Inputs JSON</span><textarea rows="4" data-block-field="inputs">${escapeHtml(block.inputs || "{}")}</textarea></label>
  `;
}

function renderDataContractLogicBlock(block) {
  return `
    <div class="block-grid three">
      <label class="field"><span>Contract ID</span><input data-block-field="contract_id" value="${escapeHtml(block.contract_id || "")}" /></label>
      <label class="field"><span>Asset ID</span><input data-block-field="asset_id" value="${escapeHtml(block.asset_id || "")}" placeholder="optional override" /></label>
      <label class="field"><span>Output Variable</span><input data-block-field="output" value="${escapeHtml(block.output || "data_contract")}" /></label>
    </div>
  `;
}

function renderLineageImpactLogicBlock(block) {
  return `
    <div class="block-grid three">
      <label class="field"><span>Resource Kind</span><select data-block-field="resource_kind">${optionList(["dataset", "pipeline", "object_type"], block.resource_kind || "dataset")}</select></label>
      <label class="field"><span>Resource ID</span><input data-block-field="resource_id" value="${escapeHtml(block.resource_id || "")}" /></label>
      <label class="field"><span>Direction</span><select data-block-field="direction">${optionList(["downstream", "upstream"], block.direction || "downstream")}</select></label>
      <label class="field"><span>Max Depth</span><input type="number" data-block-field="max_depth" value="${escapeHtml(block.max_depth || 8)}" /></label>
      <label class="field"><span>Output Variable</span><input data-block-field="output" value="${escapeHtml(block.output || "lineage_impact")}" /></label>
    </div>
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
  const objectId = props.object_id || feature.id;
  const band = state.featureRiskById[objectId]?.band;
  if (band === "critical") return "#8f1f2b";
  if (band === "high") return "#b43b3b";
  if (band === "medium") return "#ad6b18";
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
  state.featureRiskById = {};
  el("featureCount").textContent = `${features.length} features`;
  el("mapTitle").textContent = state.layer?.display_name || "Operational Map";
  el("mapSubtitle").textContent = state.layer?.object_type_id || "Feature collection";
  renderFeatureTable(features);
  renderProfile(null);
  renderMap(true);
  loadMapRiskOverlay(features).catch(() => {});
}

async function loadMapRiskOverlay(features) {
  const objectTypeId = state.layer?.object_type_id || "asset";
  const ids = features.map((feature) => feature.properties?.object_id || feature.id).filter(Boolean);
  if (!objectTypeId || !ids.length) return;
  const decision = await api("/decision/evaluate", {
    method: "POST",
    body: JSON.stringify({ object_type_id: objectTypeId, object_ids: ids, limit: ids.length, persist_run: false })
  });
  state.featureRiskById = Object.fromEntries((decision.findings || []).map((item) => [item.object_id, item.risk]));
  renderFeatureTable(state.features);
  renderMap(false);
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
    const objectId = props.object_id || feature.id;
    return `<tr class="${selected}" data-feature-id="${escapeHtml(feature.id)}"><td>${escapeHtml(objectId)}</td><td>${escapeHtml(props.name || props.title || "")}</td><td>${escapeHtml(props.criticality || props.status || "")}</td><td>${renderRiskBadge(state.featureRiskById[objectId])}</td></tr>`;
  }).join("");
  el("featureTable").innerHTML = `<table><thead><tr><th>ID</th><th>Name</th><th>State</th><th>Risk</th></tr></thead><tbody>${rows}</tbody></table>`;
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
  if (block.type === "explain_object") {
    return {
      type: "explain_object",
      object_type_id: block.object_type_id,
      object_id: block.object_id || "$object_id",
      output: block.output || "explanation"
    };
  }
  if (block.type === "score_risk") {
    return {
      type: "score_risk",
      object_type_id: block.object_type_id,
      object_id: block.object_id || "$object_id",
      scorecard_ids: String(block.scorecard_ids || "").split(",").map((item) => item.trim()).filter(Boolean),
      output: block.output || "risk"
    };
  }
  if (block.type === "run_scenario") {
    return {
      type: "run_scenario",
      seed_object_ids: block.seed_object_ids || "",
      overrides: parseJsonValue(block.overrides, {}, "Scenario overrides"),
      propagation_rules: parseJsonValue(block.propagation_rules, [], "Scenario propagation rules"),
      output: block.output || "scenario"
    };
  }
  if (block.type === "create_incident") {
    return {
      type: "create_incident",
      display_name: block.display_name || "Logic Incident",
      description: block.description || "$prompt",
      severity: block.severity || "medium",
      linked_objects: parseJsonValue(block.linked_objects, [], "Incident linked objects"),
      output: block.output || "incident",
      actor: "workspace"
    };
  }
  if (block.type === "evaluate_alert_rules") {
    return {
      type: "evaluate_alert_rules",
      source: block.source || null,
      event_type: block.event_type || null,
      status: block.status || null,
      limit: Number(block.limit || 500),
      output: block.output || "alerts"
    };
  }
  if (block.type === "run_runbook") {
    return {
      type: "run_runbook",
      runbook_id: block.runbook_id || "",
      incident_id: block.incident_id || null,
      inputs: parseJsonValue(block.inputs, {}, "Runbook inputs"),
      output: block.output || "runbook",
      actor: "workspace"
    };
  }
  if (block.type === "run_data_contract") {
    return {
      type: "run_data_contract",
      contract_id: block.contract_id || "",
      asset_id: block.asset_id || null,
      output: block.output || "data_contract"
    };
  }
  if (block.type === "analyze_lineage_impact") {
    return {
      type: "analyze_lineage_impact",
      resource_kind: block.resource_kind || "dataset",
      resource_id: block.resource_id || "",
      direction: block.direction || "downstream",
      max_depth: Number(block.max_depth || 8),
      output: block.output || "lineage_impact"
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
  if (block.type === "explain_object" || block.type === "score_risk") {
    return { ...defaultLogicBlock(block.type), ...block, scorecard_ids: Array.isArray(block.scorecard_ids) ? block.scorecard_ids.join(", ") : (block.scorecard_ids || "") };
  }
  if (block.type === "run_scenario") {
    return {
      ...defaultLogicBlock("run_scenario"),
      ...block,
      seed_object_ids: Array.isArray(block.seed_object_ids) ? block.seed_object_ids.join(", ") : (block.seed_object_ids || ""),
      overrides: compactJson(block.overrides || {}),
      propagation_rules: compactJson(block.propagation_rules || [])
    };
  }
  if (block.type === "create_incident") {
    return { ...defaultLogicBlock("create_incident"), ...block, linked_objects: compactJson(block.linked_objects || []) };
  }
  if (block.type === "run_runbook") {
    return { ...defaultLogicBlock("run_runbook"), ...block, inputs: compactJson(block.inputs || {}) };
  }
  if (["evaluate_alert_rules", "run_data_contract", "analyze_lineage_impact"].includes(block.type)) {
    return { ...defaultLogicBlock(block.type), ...block };
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
  el("searchNav").addEventListener("click", () => setView("search"));
  el("graphNav").addEventListener("click", () => setView("graph"));
  el("commandCenterNav").addEventListener("click", () => setView("command-center"));
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
  el("platformSearchInput").addEventListener("keydown", (event) => {
    if (event.key === "Enter") refreshSearchWorkspace();
  });
  el("platformSearchKind").addEventListener("change", refreshSearchWorkspace);
  el("platformSearchBtn").addEventListener("click", refreshSearchWorkspace);
  el("platformSearchInlineBtn").addEventListener("click", refreshSearchWorkspace);
  el("refreshGraphBtn").addEventListener("click", refreshGraphWorkspace);
  el("refreshCommandCenterBtn").addEventListener("click", () => refreshCommandCenterWorkspace().catch((error) => showToast(error.message)));
  el("bootstrapCommandCenterBtn").addEventListener("click", () => bootstrapCommandCenter().catch((error) => showToast(error.message)));
  el("runCommandCenterTriageBtn").addEventListener("click", () => runCommandCenterTriage().catch((error) => showToast(error.message)));
  el("approveCommandCenterBtn").addEventListener("click", () => approveCommandCenterAction().catch((error) => showToast(error.message)));
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
    const routeButton = event.target.closest("[data-open-route]");
    if (routeButton) {
      const route = routeButton.dataset.openRoute || "";
      if (route.startsWith("/workspace/")) {
        setView(routeViewFromPath(route));
      } else {
        showToast(route);
      }
      return;
    }
    const resourceRow = event.target.closest("[data-resource-view]");
    if (resourceRow) setView(resourceRow.dataset.resourceView);
    const commandAssetRow = event.target.closest("[data-command-asset]");
    if (commandAssetRow) {
      state.commandCenter.selectedAssetId = commandAssetRow.dataset.commandAsset;
      refreshCommandCenterWorkspace().catch((error) => showToast(error.message));
    }
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
  el("decisionNav").addEventListener("click", () => setView("decision"));
  el("modelsNav").addEventListener("click", () => setView("models"));
  el("opsNav").addEventListener("click", () => setView("ops"));
  el("investigationsNav").addEventListener("click", () => setView("investigations"));
  el("pipelineNav").addEventListener("click", () => setView("pipeline"));
  el("ontologyGeneratorAssetSelect").addEventListener("change", (event) => {
    state.ontologyGenerator.selectedAssetId = event.target.value;
  });
  el("ontologyDraftSelect").addEventListener("change", (event) => {
    state.ontologyGenerator.selectedDraftId = event.target.value;
    state.ontologyGenerator.result = null;
    renderOntologyPage();
  });
  el("ontologyGeneratorActionsToggle").addEventListener("change", (event) => {
    state.ontologyGenerator.includeActions = event.target.checked;
  });
  el("ontologyGeneratorPipelineToggle").addEventListener("change", (event) => {
    state.ontologyGenerator.createPipelineGraph = event.target.checked;
  });
  el("createOntologyDraftBtn").addEventListener("click", () => createOntologyGeneratorDraft().catch((error) => showToast(error.message)));
  el("validateOntologyDraftBtn").addEventListener("click", () => validateOntologyGeneratorDraft().catch((error) => showToast(error.message)));
  el("applyOntologyDraftBtn").addEventListener("click", () => applyOntologyGeneratorDraft().catch((error) => showToast(error.message)));
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
  el("pipelineNodeLibrary").addEventListener("dragstart", (event) => {
    const type = event.target.closest("[data-add-pipeline-node]")?.dataset.addPipelineNode;
    if (type) event.dataTransfer.setData("text/pipeline-node-type", type);
  });
  el("pipelineCanvas").addEventListener("dragover", (event) => {
    if (Array.from(event.dataTransfer.types || []).includes("text/pipeline-node-type")) event.preventDefault();
  });
  el("pipelineCanvas").addEventListener("drop", (event) => {
    const type = event.dataTransfer.getData("text/pipeline-node-type");
    if (!type) return;
    event.preventDefault();
    const rect = el("pipelineCanvas").getBoundingClientRect();
    addPipelineNode(type, { x: Math.max(20, event.clientX - rect.left - 110), y: Math.max(20, event.clientY - rect.top - 46) });
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
    const edgeId = event.target.dataset.removePipelineEdge;
    if (event.target.closest("[data-open-ontology-generator-from-pipeline]")) {
      openOntologyGeneratorFromPipeline();
      return;
    }
    if (edgeId) {
      const [source, target] = edgeId.split("->");
      state.pipeline.draft.edges = state.pipeline.draft.edges.filter((edge) => edge.source !== source || edge.target !== target);
      state.pipeline.activeEdgeId = "";
      renderPipelineBuilder();
      return;
    }
    if (nodeId) {
      state.pipeline.draft.nodes = state.pipeline.draft.nodes.filter((node) => node.id !== nodeId);
      state.pipeline.draft.edges = state.pipeline.draft.edges.filter((edge) => edge.source !== nodeId && edge.target !== nodeId);
      state.pipeline.activeNodeId = state.pipeline.draft.nodes[0]?.id || "";
      renderPipelineBuilder();
    }
  });
  document.querySelectorAll("[data-pipeline-panel]").forEach((button) => {
    button.addEventListener("click", () => {
      state.pipeline.activePanel = button.dataset.pipelinePanel;
      renderPipelineConfig();
    });
  });
  el("savePipelineGraphBtn").addEventListener("click", () => savePipelineGraph().catch((error) => showToast(error.message)));
  el("autoLayoutPipelineBtn").addEventListener("click", autoLayoutPipelineGraph);
  el("validatePipelineGraphBtn").addEventListener("click", () => validatePipelineGraph().catch((error) => showToast(error.message)));
  el("previewPipelineGraphBtn").addEventListener("click", () => previewPipelineGraph().catch((error) => showToast(error.message)));
  el("deliverPipelineGraphBtn").addEventListener("click", () => deliverPipelineGraph().catch((error) => showToast(error.message)));
  el("refreshModelOpsBtn").addEventListener("click", () => refreshModelOpsWorkspace().catch((error) => showToast(error.message)));
  document.querySelectorAll("[data-modelops-tab]").forEach((button) => {
    button.addEventListener("click", () => setModelOpsTab(button.dataset.modelopsTab));
  });
  el("modelObjectiveSelect").addEventListener("change", async (event) => {
    state.modelops.selectedObjectiveId = event.target.value;
    state.modelops.selectedSubmissionId = "";
    await refreshModelOpsWorkspace();
  });
  el("modelSubmissionSelect").addEventListener("change", async (event) => {
    state.modelops.selectedSubmissionId = event.target.value;
    await refreshModelOpsWorkspace();
  });
  el("modelDeploymentSelect").addEventListener("change", async (event) => {
    state.modelops.selectedDeploymentId = event.target.value;
    await refreshModelOpsWorkspace();
  });
  el("createModelObjectiveBtn").addEventListener("click", () => createModelObjective().catch((error) => showToast(error.message)));
  el("trainModelBtn").addEventListener("click", () => trainSelectedModel().catch((error) => showToast(error.message)));
  el("createModelCheckBtn").addEventListener("click", () => createModelCheck().catch((error) => showToast(error.message)));
  el("modelGatePanel").addEventListener("click", (event) => {
    const button = event.target.closest("[data-model-check-decision]");
    if (!button) return;
    decideModelCheck(button.dataset.modelCheckDecision, button.dataset.modelCheckStatus).catch((error) => showToast(error.message));
  });
  el("createModelReleaseBtn").addEventListener("click", () => createModelRelease().catch((error) => showToast(error.message)));
  el("createModelDeploymentBtn").addEventListener("click", () => createModelDeployment().catch((error) => showToast(error.message)));
  el("createModelMonitorBtn").addEventListener("click", () => createModelMonitor().catch((error) => showToast(error.message)));
  el("runModelMonitorBtn").addEventListener("click", () => runSelectedModelMonitor().catch((error) => showToast(error.message)));
  el("runModelInferenceBtn").addEventListener("click", () => runModelInference().catch((error) => showToast(error.message)));
  el("modelObjectiveList").addEventListener("click", async (event) => {
    const objectiveId = event.target.closest("[data-model-objective]")?.dataset.modelObjective;
    if (!objectiveId) return;
    state.modelops.selectedObjectiveId = objectiveId;
    state.modelops.selectedSubmissionId = "";
    await refreshModelOpsWorkspace();
  });
  el("modelSubmissionList").addEventListener("click", async (event) => {
    const submissionId = event.target.closest("[data-model-submission]")?.dataset.modelSubmission;
    if (!submissionId) return;
    state.modelops.selectedSubmissionId = submissionId;
    await refreshModelOpsWorkspace();
  });
  el("modelReleasePanel").addEventListener("click", async (event) => {
    const deploymentId = event.target.closest("[data-model-deployment]")?.dataset.modelDeployment;
    if (!deploymentId) return;
    state.modelops.selectedDeploymentId = deploymentId;
    await refreshModelOpsWorkspace();
  });
  el("modelMonitorPanel").addEventListener("click", async (event) => {
    const monitorId = event.target.closest("[data-model-monitor]")?.dataset.modelMonitor;
    if (!monitorId) return;
    state.modelops.selectedMonitorId = monitorId;
    await refreshModelOpsWorkspace();
  });
  el("refreshOpsBtn").addEventListener("click", () => refreshOpsWorkspace().catch((error) => showToast(error.message)));
  document.querySelectorAll("[data-ops-tab]").forEach((button) => {
    button.addEventListener("click", () => setOpsTab(button.dataset.opsTab));
  });
  el("evaluateOpsAlertsBtn").addEventListener("click", () => evaluateOpsAlerts().catch((error) => showToast(error.message)));
  el("createOpsAlertRuleBtn").addEventListener("click", () => createOpsAlertRule().catch((error) => showToast(error.message)));
  el("createOpsIncidentBtn").addEventListener("click", () => createOpsIncident().catch((error) => showToast(error.message)));
  el("createOpsRunbookBtn").addEventListener("click", () => createOpsRunbook().catch((error) => showToast(error.message)));
  el("executeOpsRunbookBtn").addEventListener("click", () => executeOpsRunbook().catch((error) => showToast(error.message)));
  el("createDataContractBtn").addEventListener("click", () => createDataContract().catch((error) => showToast(error.message)));
  el("runDataContractBtn").addEventListener("click", () => runSelectedDataContract().catch((error) => showToast(error.message)));
  el("analyzeLineageImpactBtn").addEventListener("click", () => analyzeOpsLineageImpact().catch((error) => showToast(error.message)));
  el("createBackfillBtn").addEventListener("click", () => createOpsBackfill().catch((error) => showToast(error.message)));
  el("opsIncidentSelect").addEventListener("change", (event) => { state.ops.selectedIncidentId = event.target.value; renderOpsWorkspace(); });
  el("opsRunbookSelect").addEventListener("change", (event) => { state.ops.selectedRunbookId = event.target.value; renderOpsWorkspace(); });
  el("opsContractSelect").addEventListener("change", (event) => { state.ops.selectedContractId = event.target.value; renderOpsWorkspace(); });
  el("opsIncidentList").addEventListener("click", (event) => {
    const incidentId = event.target.closest("[data-ops-incident]")?.dataset.opsIncident;
    if (!incidentId) return;
    state.ops.selectedIncidentId = incidentId;
    renderOpsWorkspace();
  });
  el("opsRunbookList").addEventListener("click", (event) => {
    const runbookId = event.target.closest("[data-ops-runbook]")?.dataset.opsRunbook;
    if (!runbookId) return;
    state.ops.selectedRunbookId = runbookId;
    renderOpsWorkspace();
  });
  el("opsDataContractList").addEventListener("click", (event) => {
    const contractId = event.target.closest("[data-ops-contract]")?.dataset.opsContract;
    if (!contractId) return;
    state.ops.selectedContractId = contractId;
    renderOpsWorkspace();
  });
  el("opsBackfillList").addEventListener("click", (event) => {
    const planId = event.target.closest("[data-run-backfill]")?.dataset.runBackfill;
    if (planId) runOpsBackfill(planId).catch((error) => showToast(error.message));
  });
  el("opsInboxList").addEventListener("click", (event) => {
    const noteId = event.target.closest("[data-ack-note]")?.dataset.ackNote;
    if (noteId) ackOpsNotification(noteId).catch((error) => showToast(error.message));
  });
  el("refreshInvestigationsBtn").addEventListener("click", () => refreshInvestigationsWorkspace().catch((error) => showToast(error.message)));
  document.querySelectorAll("[data-investigation-tab]").forEach((button) => {
    button.addEventListener("click", () => setInvestigationsTab(button.dataset.investigationTab));
  });
  el("createInvestigationBtn").addEventListener("click", () => createInvestigation().catch((error) => showToast(error.message)));
  el("addEvidenceBtn").addEventListener("click", () => addInvestigationEvidence().catch((error) => showToast(error.message)));
  el("addHypothesisBtn").addEventListener("click", () => addInvestigationHypothesis().catch((error) => showToast(error.message)));
  el("generateReportBtn").addEventListener("click", () => generateInvestigationReport().catch((error) => showToast(error.message)));
  el("investigationList").addEventListener("click", (event) => {
    const investigationId = event.target.closest("[data-investigation-id]")?.dataset.investigationId;
    if (investigationId) loadSelectedInvestigation(investigationId).catch((error) => showToast(error.message));
  });
  el("refreshDecisionBtn").addEventListener("click", () => refreshDecisionWorkspace().catch((error) => showToast(error.message)));
  el("decisionObjectTypeSelect").addEventListener("change", async () => {
    state.decision.evaluation = null;
    state.decision.explanation = null;
    state.decision.timeline = null;
    await loadDecisionRules();
    renderDecisionWorkspace();
  });
  document.querySelectorAll("[data-decision-tab]").forEach((button) => {
    button.addEventListener("click", () => setDecisionTab(button.dataset.decisionTab));
  });
  el("bootstrapDecisionBtn").addEventListener("click", () => bootstrapDecisionRules().catch((error) => showToast(error.message)));
  el("evaluateDecisionBtn").addEventListener("click", () => runDecisionEvaluation().catch((error) => showToast(error.message)));
  el("explainDecisionBtn").addEventListener("click", () => explainDecisionObject().catch((error) => showToast(error.message)));
  el("loadTimelineBtn").addEventListener("click", () => loadDecisionTimeline().catch((error) => showToast(error.message)));
  el("runDecisionScenarioBtn").addEventListener("click", () => runDecisionScenario().catch((error) => showToast(error.message)));
  el("runEntityResolutionBtn").addEventListener("click", () => runEntityResolution().catch((error) => showToast(error.message)));
  el("runDecisionAgentBtn").addEventListener("click", () => runDecisionAgent().catch((error) => showToast(error.message)));
  el("decisionRiskBoard").addEventListener("click", (event) => {
    const objectId = event.target.closest("[data-decision-object]")?.dataset.decisionObject;
    if (!objectId) return;
    el("decisionObjectIdInput").value = objectId;
    explainDecisionObject().catch((error) => showToast(error.message));
  });
  el("entityCandidateList").addEventListener("click", (event) => {
    const acceptId = event.target.closest("[data-accept-candidate]")?.dataset.acceptCandidate;
    const rejectId = event.target.closest("[data-reject-candidate]")?.dataset.rejectCandidate;
    if (acceptId) acceptEntityCandidate(acceptId).catch((error) => showToast(error.message));
    if (rejectId) rejectEntityCandidate(rejectId).catch((error) => showToast(error.message));
  });
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
