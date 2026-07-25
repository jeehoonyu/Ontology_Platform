import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { createServer } from "node:http";

const routes = [
  "command-center",
  "imports",
  "ontology",
  "pipeline",
  "workshop",
  "aip",
  "investigations",
  "entity-resolution",
  "graph",
  "validation",
  "control-panel"
];

for (const route of routes) {
  test(`${route} is aligned, human-readable, and accessible`, async ({ page }, testInfo) => {
    await page.goto(`/workspace/${route}`);
    await expect(page.locator(".app-shell")).toBeVisible();
    await expect(page.locator(".sidebar")).toBeVisible();
    await expect(page.locator("body")).not.toContainText("[object Object]");
    await expect(page.locator("pre:visible")).toHaveCount(0);

    const bodyOverflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(bodyOverflow).toBeLessThanOrEqual(2);

    const accessibility = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
    const blocking = accessibility.violations.filter((violation) => violation.impact === "critical" || violation.impact === "serious");
    expect(blocking, blocking.map((item) => `${item.id}: ${item.help}`).join("\n")).toEqual([]);

    if (["pipeline", "ontology", "workshop", "command-center"].includes(route)) {
      await page.screenshot({ path: `test-results/screenshots/${testInfo.project.name}-${route}.png`, fullPage: true });
    }
  });
}

test("command palette supports keyboard navigation", async ({ page }) => {
  await page.goto("/workspace/command-center");
  await page.keyboard.press("Control+K");
  const palette = page.getByRole("dialog", { name: "Search workspaces" });
  await expect(palette).toBeVisible();
  await palette.getByPlaceholder("Find a workspace or capability").fill("entity resolution");
  await palette.getByRole("button", { name: /Entity Resolution/ }).click();
  await expect(page).toHaveURL(/\/workspace\/entity-resolution$/);
});

test("data onboarding previews a live connector with write-only credentials and fetch evidence", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-1280", "Run the stateful live connector workflow once on desktop.");
  const server = createServer((request, response) => {
    if (request.headers.authorization !== "Bearer browser-secret") {
      response.writeHead(401).end();
      return;
    }
    response.writeHead(200, { "content-type": "application/json" });
    response.end(JSON.stringify({ records: [
      { asset_id: "browser-live-1", name: "Live Browser Pump", status: "DEGRADED" },
      { asset_id: "browser-live-2", name: "Live Browser Chiller", status: "RUNNING" }
    ] }));
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  try {
    const address = server.address();
    if (!address || typeof address === "string") throw new Error("Could not determine connector test server port");
    await page.goto("/workspace/imports");
    await expect(page.getByRole("heading", { name: "Live Connector" })).toBeVisible();
    await page.getByLabel("Source ID").fill(`browser_live_source_${Date.now()}`);
    await page.getByLabel("Base URL").fill(`http://127.0.0.1:${address.port}`);
    await page.getByLabel("Secret (write only)").fill("browser-secret");
    await page.getByRole("button", { name: "Save and Preview" }).click();
    await expect(page.getByText("Live Browser Pump", { exact: true })).toBeVisible();
    await expect(page.getByText("SUCCEEDED", { exact: true })).toBeVisible();
    await expect(page.getByLabel("Secret (write only)")).toHaveValue("");
    await expect(page.getByRole("cell", { name: "s3" })).toBeVisible();
    await expect(page.getByText("PLUGIN_REQUIRED", { exact: true }).first()).toBeVisible();
  } finally {
    await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
  }
});

test("runtime operations shows durable telemetry, budgets, and SLO controls", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-1280", "Run the stateful runtime operations workflow once on desktop.");
  const projectId = `browser-runtime-${Date.now()}`;
  const workerName = `browser-worker-${Date.now()}`;
  const queued = await page.request.post("/jobs", { data: {
    project_id: projectId,
    job_type: "pipeline.preview",
    estimated_compute_seconds: 2,
    estimated_cost_usd: 0.05,
    estimated_records: 10
  } });
  expect(queued.ok()).toBeTruthy();
  const job = await queued.json() as { id: string };
  const claimResponse = await page.request.post("/jobs/claim", { data: { worker_id: workerName, job_id: job.id } });
  const claimed = (await claimResponse.json() as { job: { lease_token: string } }).job;
  await page.request.post(`/jobs/${job.id}/complete`, { data: {
    lease_token: claimed.lease_token,
    result: { compute_seconds: 3, estimated_cost_usd: 0.08, records_out: 12 }
  } });
  await page.request.put("/runtime/observability/budgets", { data: {
    project_id: projectId,
    metric: "executions",
    limit_value: 20,
    window_seconds: 86400,
    enforcement: "HARD",
    enabled: true
  } });
  const sloResponse = await page.request.post("/runtime/observability/slo-policies", { data: {
    project_id: projectId,
    display_name: "Browser availability",
    metric: "availability",
    operator: "gte",
    threshold: 0.99,
    window_seconds: 86400,
    severity: "warning",
    enabled: true
  } });
  const slo = await sloResponse.json() as { id: string };
  await page.request.post(`/runtime/observability/slo-policies/${slo.id}/evaluate`, { data: {} });
  await page.request.put(`/runtime/workers/${workerName}`, { data: {
    project_id: projectId,
    supported_job_types: ["pipeline.preview"],
    max_concurrency: 2,
    labels: { pool: "browser" }
  } });
  await page.request.put(`/runtime/queues/${projectId}`, { data: {
    weight: 2,
    max_concurrency: 5,
    paused: false
  } });

  await page.goto("/workspace/control-panel");
  await page.getByRole("button", { name: "Runtime" }).click();
  await page.getByLabel("Project", { exact: true }).fill(projectId);
  await expect(page.getByRole("heading", { name: "Durable Job Telemetry" })).toBeVisible();
  await expect(page.getByText("pipeline.preview", { exact: true })).toBeVisible();
  await expect(page.getByText("Browser availability", { exact: true })).toBeVisible();
  await expect(page.getByText(workerName, { exact: true })).toBeVisible();
  const fleetPanel = page.locator(".panel").filter({ has: page.getByRole("heading", { name: "Worker Fleet" }) });
  await expect(fleetPanel.getByText("ACTIVE", { exact: true })).toBeVisible();
  const queuePanel = page.locator(".panel").filter({ has: page.getByRole("heading", { name: "Queue Policy" }) });
  await expect(queuePanel.getByRole("cell", { name: projectId })).toBeVisible();
  const budgetPanel = page.locator(".panel").filter({ has: page.getByRole("heading", { name: "Project Budgets" }) });
  await expect(budgetPanel.getByRole("cell", { name: "executions" })).toBeVisible();
});

test("control panel issues a one-time project worker token and revokes it", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-1280", "Run the stateful worker credential workflow once on desktop.");
  const suffix = Date.now();
  const accountId = `browser-worker-${suffix}`;
  await page.goto("/workspace/control-panel");
  await page.getByRole("button", { name: "Auth", exact: true }).click();
  const accountPanel = page.locator(".panel").filter({ has: page.getByRole("heading", { name: "Create Worker Service Account" }) });
  await accountPanel.getByLabel("Service account ID").fill(accountId);
  await accountPanel.getByLabel("Display name").fill(`Browser Worker ${suffix}`);
  await accountPanel.getByRole("button", { name: "Create" }).click();
  const tokenPanel = page.locator(".panel").filter({ has: page.getByRole("heading", { name: "Issue Project Worker Token" }) });
  await tokenPanel.getByLabel("Service account").selectOption(accountId);
  await tokenPanel.getByLabel("Project ID").fill("default");
  await tokenPanel.getByRole("button", { name: "Issue once" }).click();
  const secretField = tokenPanel.getByLabel("One-time worker token");
  await expect(secretField).toHaveValue(/^tok_.{32,}$/);
  const secret = await secretField.inputValue();
  const apiTokenPanel = page.locator(".panel").filter({ has: page.getByRole("heading", { name: "API Tokens" }) });
  await apiTokenPanel.getByLabel("Token to revoke").selectOption({ label: secret.slice(0, 12) });
  await apiTokenPanel.getByRole("button", { name: "Revoke" }).click();
  const revokedTokenRow = apiTokenPanel.getByRole("row").filter({ hasText: secret.slice(0, 12) });
  await expect(revokedTokenRow.getByRole("cell", { name: "true", exact: true })).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: "Auth", exact: true }).click();
  await expect(page.locator("body")).not.toContainText(secret);
});

test("visual builder supports typed configuration, preview, save, and publish", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-1280", "Run the stateful builder workflow once on desktop.");
  await page.goto("/workspace/workshop");
  const create = page.getByRole("button", { name: "Create draft" });
  const canvas = page.locator(".visual-flow-canvas");
  await expect(create.or(canvas)).toBeVisible();
  if (await create.isVisible()) await create.click();
  await expect(canvas).toBeVisible();
  await page.locator(".node-library-list > button").filter({ hasText: "Metric" }).first().click();
  await expect(page.getByRole("heading", { name: "Node settings" })).toBeVisible();
  await page.getByLabel("Data source").fill("asset.risk.score");
  await page.getByLabel("Display label").fill("Asset risk");
  await page.getByRole("button", { name: /Save/ }).click();
  await expect(page.locator(".operation-message")).toContainText(/Saved revision/);
  await page.getByRole("button", { name: /Preview/ }).click();
  await expect(page.locator(".builder-execution-drawer")).toContainText(/\d+ nodes/);
  await page.getByRole("button", { name: /Publish/ }).click();
  await expect(page.locator(".operation-message")).toContainText(/Published revision/);
});

test("visual builders show collaborators and receive clean remote revisions", async ({ browser }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-1280", "Run the multi-user collaboration workflow once on desktop.");
  const contextA = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const contextB = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const pageA = await contextA.newPage();
  const pageB = await contextB.newPage();
  try {
    const suffix = Date.now();
    const created = await pageA.request.post("/artifacts", { data: {
      artifact_type: "workshop",
      display_name: `Collaborative workshop ${suffix}`,
      state: {
        nodes: [{ id: "initial", position: { x: 80, y: 80 }, data: { label: "Initial metric", nodeType: "metric" } }],
        edges: [],
        widgets: []
      }
    } });
    expect(created.ok()).toBeTruthy();
    const artifact = await created.json() as { id: string };

    await Promise.all([pageA.goto("/workspace/workshop"), pageB.goto("/workspace/workshop")]);
    await pageA.getByLabel("Workshop artifact").selectOption(artifact.id);
    await pageB.getByLabel("Workshop artifact").selectOption(artifact.id);
    await expect(pageA.locator(".collaboration-presence")).toContainText("2 editing");
    await expect(pageB.locator(".collaboration-presence")).toContainText("2 editing");
    await expect(pageB.locator(".react-flow__node")).toHaveCount(1);

    await pageA.locator(".node-library-list > button").filter({ hasText: "Metric" }).first().click();
    await pageA.getByRole("button", { name: /Save/ }).click();
    await expect(pageA.locator(".operation-message")).toContainText(/Saved revision/);
    await expect(pageB.locator(".react-flow__node")).toHaveCount(2);
  } finally {
    await contextA.close();
    await contextB.close();
  }
});

test("ontology maps dataset fields with hydrated preview", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-1280", "Run the stateful ontology mapping workflow once on desktop.");
  await page.request.post("/scenarios/asset-reliability/bootstrap", { data: {} });
  await page.goto("/workspace/ontology");
  const mappingPanel = page.locator(".ontology-mapping-panel");
  await expect(mappingPanel.getByRole("heading", { name: "Dataset to Ontology Mapping" })).toBeVisible();
  await mappingPanel.getByLabel("Source dataset").selectOption({ index: 1 });
  await mappingPanel.getByRole("button", { name: "Suggest mappings" }).click();
  await expect(mappingPanel.getByText(/Suggested \d+ compatible field mappings/)).toBeVisible();
  await expect(mappingPanel.getByText(/Hydrated object preview/)).toBeVisible();
});

test("ontology manager publishes and installs a governed package", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-1280", "Run the governed package workflow once on desktop.");
  const suffix = Date.now();
  const objectTypeId = `packaged_asset_${suffix}`;
  const displayName = `Packaged Asset ${suffix}`;
  const created = await page.request.post("/object-types", { data: {
    id: objectTypeId,
    display_name: displayName,
    description: "Browser package acceptance type",
    properties: { asset_id: { type: "string", required: true }, status: { type: "string" } }
  } });
  expect(created.ok()).toBeTruthy();

  await page.goto("/workspace/ontology");
  await page.locator(".manager-resource-nav .resource-row").filter({ hasText: displayName }).click();
  const packagePanel = page.locator(".ontology-package-panel");
  await expect(packagePanel).toBeVisible();
  const initialize = packagePanel.getByRole("button", { name: "Initialize workspace" });
  if (await initialize.isVisible()) {
    await initialize.click();
    await expect(packagePanel).toContainText("Package workspace initialized");
  }
  await packagePanel.getByLabel("Package").selectOption("");
  await packagePanel.getByRole("button", { name: "Create from selected type" }).click();
  await expect(packagePanel).toContainText("Package created");
  await packagePanel.getByLabel("New version").fill("1.0.0");
  await packagePanel.getByRole("button", { name: "Capture selected type" }).click();
  await expect(packagePanel).toContainText("Captured 1.0.0");
  await packagePanel.getByRole("button", { name: "Publish" }).click();
  await expect(packagePanel).toContainText("Published 1.0.0");
  await packagePanel.getByLabel("Namespace").fill(`browser_${suffix}`);
  await packagePanel.getByRole("button", { name: "Install package" }).click();
  await expect(packagePanel).toContainText("Installed 1.0.0");
});

test("pipeline creates a graph and accepts a dragged node", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-1280", "Run the stateful pipeline workflow once on desktop.");
  await page.goto("/workspace/pipeline");
  await page.getByRole("button", { name: "New pipeline" }).click();
  await expect(page.getByText(/Pipeline draft created/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Propose" })).toBeEnabled();
  const canvas = page.locator(".pipeline-canvas");
  const source = page.getByRole("button", { name: "Input Dataset input" });
  const dataTransfer = await page.evaluateHandle(() => new DataTransfer());
  const canvasBox = await canvas.boundingBox();
  expect(canvasBox).not.toBeNull();
  await source.dispatchEvent("dragstart", { dataTransfer });
  await canvas.dispatchEvent("dragover", { dataTransfer });
  await canvas.dispatchEvent("drop", {
    dataTransfer,
    clientX: (canvasBox?.x || 0) + 360,
    clientY: (canvasBox?.y || 0) + 180
  });
  await source.dispatchEvent("dragend", { dataTransfer });
  await expect(canvas.locator(".pipeline-node")).toHaveCount(1);
  await expect(page.getByText(/Added input_dataset at drop location/)).toBeVisible();
});

test("pipeline preview runs through durable worker evidence", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-1280", "Run the stateful Pipeline execution workflow once on desktop.");
  const suffix = Date.now();
  const assetId = `browser_async_asset_${suffix}`;
  const graphId = `browser_async_pipeline_${suffix}`;
  const graphName = `Browser async pipeline ${suffix}`;
  await page.request.post("/data-assets", { data: {
    id: assetId,
    display_name: "Browser async assets",
    kind: "dataset",
    asset_schema: {},
    records: [{ id: "asset-1", risk: 91 }, { id: "asset-2", risk: 35 }]
  } });
  await page.request.post("/pipeline-builder/graphs", { data: {
    id: graphId,
    display_name: graphName,
    nodes: [
      { id: "input", type: "input_dataset", config: { asset_id: assetId } },
      { id: "filter", type: "filter", config: { field: "risk", operator: "gte", value: 80 } },
      { id: "output", type: "dataset_output", config: { asset_id: `${assetId}_output` } }
    ],
    edges: [{ source: "input", target: "filter" }, { source: "filter", target: "output" }]
  } });
  await page.goto("/workspace/pipeline");
  await page.locator(".output-rail .resource-row").filter({ hasText: graphName }).click();
  await expect(page.locator(".workspace-header")).toContainText(graphName);
  await page.getByRole("button", { name: "Preview", exact: true }).click();
  const execution = page.locator(".pipeline-execution-state");
  await expect(execution).toContainText("SUCCEEDED");
  await expect(execution.locator("progress")).toHaveAttribute("value", "100");
  await execution.getByText("Execution events").click();
  await expect(execution).toContainText("job.progress");
  await expect(page.locator(".workbench-status-strip")).toContainText(/preview succeeded/i);
});

test("AIP agent runtime exposes durable policy and citation evidence", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-1280", "Run the stateful agent execution workflow once on desktop.");
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  const suffix = Date.now();
  const objectTypeId = `browser_incident_${suffix}`;
  const objectId = `browser_incident_object_${suffix}`;
  const actionId = `browser_escalate_${suffix}`;
  const agentId = `browser_agent_${suffix}`;
  await page.request.post("/object-types", { data: {
    id: objectTypeId,
    display_name: "Browser incident",
    properties: { severity: { type: "string" } }
  } });
  await page.request.post("/objects", { data: {
    id: objectId,
    object_type_id: objectTypeId,
    properties: { severity: "critical" }
  } });
  await page.request.post("/action-types", { data: {
    id: actionId,
    display_name: "Browser escalation",
    parameters: { incident_id: { type: "string", required: true } },
    rules: { requires_approval: true }
  } });
  await page.request.post("/agents", { data: {
    id: agentId,
    display_name: `Browser Agent ${suffix}`,
    description: "A governed browser-test agent",
    allowed_object_types: [objectTypeId],
    allowed_actions: [actionId]
  } });
  await page.request.put(`/aip/agents/${agentId}/tools`, { data: {
    tools: [
      { name: "find incident", type: "object_query", object_type_id: objectTypeId, trigger: "incident" },
      { name: "escalate", type: "action", action_type_id: actionId, trigger: "escalate" }
    ],
    retrieval: { ontology: [objectTypeId] }
  } });
  await page.request.post("/artifacts", { data: {
    artifact_type: "aip_logic",
    display_name: `Browser AIP Logic ${suffix}`,
    state: { nodes: [{ id: "query", type: "object_query", position: { x: 120, y: 120 }, data: { nodeType: "object_query", label: "Query incidents" } }], edges: [] }
  } });

  await page.goto("/workspace/aip");
  await expect(page.locator(".app-shell"), pageErrors.join("\n")).toBeVisible();
  await page.waitForTimeout(1000);
  expect(pageErrors).toEqual([]);
  const runtime = page.locator(".agent-runtime-panel");
  await expect(runtime).toBeVisible();
  await runtime.getByLabel("Agent").selectOption(agentId);
  await runtime.getByLabel("Instruction").fill("escalate the critical incident");
  await runtime.getByRole("button", { name: "Add parameter" }).click();
  await runtime.getByLabel("Parameter 1 name").fill("incident_id");
  await runtime.getByLabel("Parameter 1 value").fill(objectId);
  await runtime.getByRole("button", { name: "Run agent" }).click();
  await expect(runtime.locator(".agent-job-state")).toContainText("SUCCEEDED");
  await expect(runtime).toContainText("APPROVAL_REQUIRED");
  await expect(runtime).toContainText("1 objects retrieved");
  await expect(runtime).toContainText("Approval ");
  await expect(runtime.locator(".agent-event-strip")).toContainText("succeeded");
});

test("platform graph supports selection, dragging, and neighborhood exploration", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-1280", "Run the stateful graph workflow once on desktop.");
  await page.request.post("/scenarios/asset-reliability/bootstrap", { data: {} });
  await page.goto("/workspace/graph");
  const canvas = page.locator(".platform-graph-canvas");
  const firstNode = canvas.locator(".react-flow__node").first();
  await expect(firstNode).toBeVisible();
  await firstNode.click();
  await expect(page.getByRole("button", { name: "Neighbors" })).toBeEnabled();
  const before = await firstNode.boundingBox();
  expect(before).not.toBeNull();
  await page.mouse.move((before?.x || 0) + (before?.width || 0) / 2, (before?.y || 0) + (before?.height || 0) / 2);
  await page.mouse.down();
  await page.mouse.move((before?.x || 0) + (before?.width || 0) / 2 + 120, (before?.y || 0) + (before?.height || 0) / 2 + 80, { steps: 12 });
  await page.mouse.up();
  const after = await firstNode.boundingBox();
  expect(after).not.toBeNull();
  expect(Math.abs((after?.x || 0) - (before?.x || 0)) + Math.abs((after?.y || 0) - (before?.y || 0))).toBeGreaterThan(5);
  await expect(page.getByRole("heading", { name: "Selected Resource" })).toBeVisible();
});

test("ontology relationship designer creates a governed link by connecting ports", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-1280", "Run the stateful ontology relationship workflow once on desktop.");
  await page.request.post("/scenarios/asset-reliability/bootstrap", { data: {} });
  await page.goto("/workspace/ontology");
  const canvas = page.locator(".ontology-relationship-canvas");
  await expect(canvas).toBeVisible();
  const graphNodes = canvas.locator(".react-flow__node");
  expect(await graphNodes.count()).toBeGreaterThan(1);
  const nodeIds = await graphNodes.evaluateAll((items) => items.map((item) => item.getAttribute("data-id") || "").filter(Boolean));
  const existingLinks = await (await page.request.get("/link-types")).json() as Array<{ source_object_type_id: string; target_object_type_id: string }>;
  const openPair = nodeIds.flatMap((source) => nodeIds.filter((target) => source !== target).map((target) => ({ source, target })))
    .find((pair) => !existingLinks.some((link) => link.source_object_type_id === pair.source && link.target_object_type_id === pair.target));
  expect(openPair).toBeDefined();
  const sourceHandle = canvas.locator(`.react-flow__node[data-id="${openPair?.source}"] .react-flow__handle.source`);
  const targetHandle = canvas.locator(`.react-flow__node[data-id="${openPair?.target}"] .react-flow__handle.target`);
  await sourceHandle.dragTo(targetHandle, { force: true });
  await expect(page.getByRole("status")).toContainText("Relationship created and audited");
  await expect(canvas.locator(".react-flow__edge")).not.toHaveCount(0);
  const actionName = `Review asset ${Date.now()}`;
  await page.getByLabel("New action name").fill(actionName);
  await page.getByLabel("New action description").fill("Governed action created through the ontology manager.");
  await page.getByRole("button", { name: "Add action" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Action type created and audited" })).toBeVisible();
});
