import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const routes = [
  "command-center",
  "imports",
  "ontology",
  "pipeline",
  "object-explorer",
  "map",
  "models",
  "decision",
  "ops",
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

    if (["pipeline", "ontology", "object-explorer", "map", "models", "decision", "ops", "workshop", "command-center"].includes(route)) {
      await page.screenshot({ path: `test-results/screenshots/${testInfo.project.name}-${route}.png`, fullPage: true });
    }
  });
}

test("Object Explorer queries bootstrapped ontology objects and opens a typed profile", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-1280", "Run the stateful explorer workflow once on desktop.");
  expect((await page.request.post("/scenarios/asset-reliability/bootstrap", { data: {} })).ok()).toBeTruthy();
  await page.goto("/workspace/object-explorer?type=asset");
  await expect(page.getByRole("heading", { name: "Object Explorer" })).toBeVisible();
  const table = page.locator(".explorer-table");
  await expect(table).toBeVisible();
  await expect(table).toContainText("asset_pump_4");
  await table.getByRole("button", { name: "asset_pump_4" }).click();
  const preview = page.locator(".panel").filter({ has: page.getByRole("heading", { name: "Object Preview" }) });
  await expect(preview).toContainText("Line 4 Pump");
  await expect(preview).toContainText(/inbound|outbound/);
  await page.getByLabel("Search objects").fill("Chiller");
  await page.getByRole("button", { name: "Run", exact: true }).click();
  await expect(table).toContainText("asset_chiller_2");
  await expect(table).not.toContainText("asset_pump_4");
});

test("Operational Map renders ontology features and supports selection and MGRS", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-1280", "Run the stateful GIS workflow once on desktop.");
  expect((await page.request.post("/scenarios/asset-reliability/bootstrap", { data: {} })).ok()).toBeTruthy();
  await page.goto("/workspace/map");
  await expect(page.getByRole("heading", { name: "Operational Map" })).toBeVisible();
  const map = page.getByLabel("Operational GIS map");
  await expect(map.locator(".leaflet-container")).toBeVisible();
  await expect(map.locator(".leaflet-interactive").first()).toBeVisible();
  await page.locator(".map-feature-list").getByRole("button", { name: /Line 4 Pump/ }).click();
  const selection = page.locator(".panel").filter({ has: page.getByRole("heading", { name: "Selection" }) });
  await expect(selection).not.toContainText("Select a feature");
  await page.getByRole("button", { name: "Encode point" }).click();
  await expect(page.getByLabel("MGRS coordinate")).not.toHaveValue("");
});

test("ModelOps completes objective-to-monitor lifecycle through structured controls", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-1280", "Run the stateful ModelOps lifecycle once on desktop.");
  const suffix = Date.now();
  const baselineId = `browser_model_baseline_${suffix}`;
  const currentId = `browser_model_current_${suffix}`;
  const objectiveName = `Browser Asset Risk ${suffix}`;
  for (const asset of [
    { id: baselineId, display_name: "Browser model baseline", records: [{ temperature: 10, pressure: 20, risk_score: 15 }, { temperature: 12, pressure: 22, risk_score: 17 }] },
    { id: currentId, display_name: "Browser model current", records: [{ temperature: 32, pressure: 60, risk_score: 46 }, { temperature: 34, pressure: 64, risk_score: 49 }] }
  ]) {
    expect((await page.request.post("/data-assets", { data: { ...asset, kind: "dataset", asset_schema: {} } })).ok()).toBeTruthy();
  }

  await page.goto("/workspace/models");
  await page.getByLabel("Objective name").fill(objectiveName);
  await page.getByLabel("Target field").fill("risk_score");
  await page.getByLabel("Feature fields").fill("temperature, pressure");
  await page.getByLabel("Objective input dataset").selectOption(baselineId);
  await page.getByRole("button", { name: "Create objective" }).click();
  await expect(page.getByRole("status")).toContainText("Objective created");
  await expect(page.getByLabel("Selected objective")).toHaveValue(/.+/);

  await page.getByRole("button", { name: "Training", exact: true }).click();
  await page.getByLabel("Training dataset").selectOption(baselineId);
  await page.getByRole("button", { name: "Train model" }).click();
  await expect(page.getByRole("status")).toContainText("Training completed");
  await expect(page.getByLabel("Selected submission")).toHaveValue(/.+/);

  await page.getByRole("button", { name: "Evaluation Gates", exact: true }).click();
  await page.getByLabel("Gate name").fill("mae_gate");
  await page.getByLabel("Gate metric").fill("mae");
  await page.getByLabel("Gate threshold").fill("10");
  await page.getByRole("button", { name: "Add gate" }).click();
  await expect(page.getByRole("status")).toContainText("Evaluation gate created");
  await page.getByRole("button", { name: "Evaluate all gates" }).click();
  await expect(page.getByRole("status")).toContainText("Evaluation gates executed");
  await expect(page.locator(".modelops-gate-list")).toContainText("approved");

  await page.getByRole("button", { name: "Releases & Deployments", exact: true }).click();
  await page.getByRole("button", { name: "Create release" }).click();
  await expect(page.getByRole("status")).toContainText("Release created");
  await page.getByRole("button", { name: "Start deployment" }).click();
  await expect(page.getByRole("status")).toContainText("Deployment started");
  await expect(page.getByLabel("Selected deployment")).toHaveValue(/.+/);

  await page.getByRole("button", { name: "Monitoring", exact: true }).click();
  await page.getByLabel("Monitor deployment").selectOption({ index: 1 });
  await page.getByLabel("Baseline dataset").selectOption(baselineId);
  await page.getByRole("button", { name: "Create monitor" }).click();
  await expect(page.getByRole("status")).toContainText("Monitor created");
  await page.getByLabel("Current monitor dataset").selectOption(currentId);
  await page.getByRole("button", { name: "Run drift check" }).click();
  await expect(page.getByRole("status")).toContainText("Monitor run completed");
  await expect(page.getByRole("heading", { name: "Latest Drift Evidence" }).locator("xpath=..")).toContainText("FAIL");

  await page.getByRole("button", { name: "Inference Playground", exact: true }).click();
  await page.getByLabel("Record 1 temperature").fill("20");
  await page.getByLabel("Record 1 pressure").fill("30");
  await page.getByRole("button", { name: "Run inference" }).click();
  await expect(page.getByRole("status")).toContainText("Inference completed");
  await expect(page.locator(".modelops-inference-layout")).toContainText("25");
  await expect(page.locator(".modelops-run-history")).toContainText("1 predictions");
});

test("Decision Intelligence evaluates, explains, traces, and simulates ontology objects", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-1280", "Run the stateful decision workflow once on desktop.");
  expect((await page.request.post("/scenarios/asset-reliability/bootstrap", { data: {} })).ok()).toBeTruthy();
  await page.goto("/workspace/decision");
  await expect(page.getByRole("heading", { name: "Decision Intelligence" })).toBeVisible();
  await page.getByLabel("Decision object type").selectOption("asset");
  await page.getByRole("button", { name: "Bootstrap rules" }).click();
  await expect(page.getByRole("status")).toContainText("Decision defaults created");
  await page.getByRole("button", { name: "Evaluate risk" }).click();
  await expect(page.getByRole("status")).toContainText("Risk evaluation completed");
  await expect(page.getByText("Line 4 Pump", { exact: true })).toBeVisible();
  await page.getByText("Line 4 Pump", { exact: true }).click();
  await page.getByRole("button", { name: "Explain selected object" }).click();
  await expect(page.getByRole("status")).toContainText("Explanation loaded");
  await expect(page.locator(".decision-narrative")).not.toBeEmpty();
  await page.getByRole("button", { name: "Timeline", exact: true }).click();
  await page.getByRole("button", { name: "Load timeline" }).click();
  await expect(page.getByRole("status")).toContainText("Timeline loaded");
  await expect(page.locator(".decision-timeline article").first()).toBeVisible();
  await page.getByRole("button", { name: "Scenario Simulator", exact: true }).click();
  await page.getByRole("button", { name: "Run impact scenario" }).click();
  await expect(page.getByRole("status")).toContainText("Scenario completed");
  await expect(page.getByRole("heading", { name: "Before / After Impact" }).locator("xpath=..")).toContainText("changed");
});

test("Operational Control promotes events through alerts, incidents, runbooks, and inbox", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-1280", "Run the stateful Ops workflow once on desktop.");
  await page.goto("/workspace/ops");
  await expect(page.getByRole("heading", { name: "Operational Control Plane" })).toBeVisible();
  await page.getByRole("button", { name: "Alerts", exact: true }).click();
  await page.getByLabel("Alert rule name").fill(`Browser critical rule ${Date.now()}`);
  await page.getByRole("button", { name: "Create rule" }).click();
  await expect(page.getByRole("status")).toContainText("Alert rule created");
  await page.getByLabel("Operational event title").fill("Browser reliability threshold exceeded");
  await page.getByRole("button", { name: "Ingest event" }).click();
  await expect(page.getByRole("status")).toContainText("Operational event ingested");
  await page.getByRole("button", { name: "Evaluate alerts" }).click();
  await expect(page.getByRole("status")).toContainText("Alert rules evaluated");
  await expect(page.locator(".ops-alert-list")).toContainText("Browser reliability threshold exceeded");
  await page.getByRole("button", { name: "Incidents", exact: true }).click();
  await page.getByLabel("Incident name").fill("Browser asset reliability incident");
  await page.getByRole("button", { name: "Open incident" }).click();
  await expect(page.getByRole("status")).toContainText("Incident opened");
  await expect(page.locator(".ops-incident-list")).toContainText("Browser asset reliability incident");
  await page.getByRole("button", { name: "Runbooks", exact: true }).click();
  await page.getByLabel("Runbook name").fill("Browser owner notification");
  await page.getByRole("button", { name: "Create runbook" }).click();
  await expect(page.getByRole("status")).toContainText("Runbook created");
  await page.getByLabel("Runbook incident").selectOption({ label: "Browser asset reliability incident" });
  await page.getByRole("button", { name: "Execute" }).click();
  await expect(page.getByRole("status")).toContainText("Runbook execution completed");
  await page.getByRole("button", { name: "Inbox", exact: true }).click();
  await expect(page.locator(".ops-inbox-list")).toContainText("Reliability review required");
  await page.locator(".ops-inbox-list article").filter({ hasText: "Reliability review required" }).getByRole("button", { name: "Acknowledge" }).click();
  await expect(page.getByRole("status")).toContainText("Notification acknowledged");
});

test("command palette supports keyboard navigation", async ({ page }) => {
  await page.goto("/workspace/command-center");
  await page.keyboard.press("Control+K");
  const palette = page.getByRole("dialog", { name: "Search workspaces" });
  await expect(palette).toBeVisible();
  await palette.getByPlaceholder("Find a workspace or capability").fill("entity resolution");
  await palette.getByRole("button", { name: /Entity Resolution/ }).click();
  await expect(page).toHaveURL(/\/workspace\/entity-resolution$/);
});

test("command center completes governed triage, approval, action, and report through visible controls", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-1280", "Run the stateful no-code operational workflow once on desktop.");
  test.setTimeout(90_000);
  await page.goto("/workspace/command-center");
  await page.locator(".top-actions").getByRole("button", { name: "Start with sample data" }).click();
  const riskPanel = page.locator(".panel").filter({ has: page.getByRole("heading", { name: "High-Risk Assets" }) });
  await expect(riskPanel).toContainText("Line 4 Pump", { timeout: 30_000 });
  await page.locator(".top-actions").getByRole("button", { name: "Run reliability triage" }).click();

  const governance = page.locator(".panel").filter({ has: page.getByRole("heading", { name: "Governed Approval and Action" }) });
  await expect(governance).toContainText("PENDING");
  await governance.getByLabel("Decision reason").fill("Browser evaluator reviewed the reliability evidence.");
  await governance.getByRole("button", { name: "Approve action" }).click();
  await expect(governance).toContainText("APPROVED");
  await governance.getByRole("button", { name: "Execute approved action" }).click();
  await expect(governance.getByLabel("Governed action evidence")).toContainText("SUCCESS");
  await expect(page.locator(".stepper button").filter({ hasText: "Execute governed action" })).toContainText("complete");

  const downloadPromise = page.waitForEvent("download");
  await page.locator(".top-actions").getByRole("button", { name: "Export proof report" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe("asset-reliability-report.md");
  await expect(page.locator(".stepper button").filter({ hasText: "Export proof report" })).toContainText("complete");
});

test("command center completes Connect-to-Report with a promoted project dataset", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-1280", "Run the project-owned Connect-to-Report workflow once on desktop.");
  test.setTimeout(90_000);
  const assetId = `evaluator_industrial_assets_${Date.now()}`;
  const created = await page.request.post("/data-assets", { data: {
    id: assetId,
    project_id: "default",
    display_name: "Evaluator industrial assets",
    kind: "dataset",
    asset_schema: {
      id: "string", name: "string", status: "string", criticality: "string",
      predicted_failure_probability: "number", latitude: "number", longitude: "number"
    },
    records: [
      { id: "evaluator-pump", name: "Evaluator Pump", status: "DEGRADED", criticality: "high", predicted_failure_probability: 0.91, latitude: 37.7924, longitude: -122.4012 },
      { id: "evaluator-chiller", name: "Evaluator Chiller", status: "RUNNING", criticality: "medium", predicted_failure_probability: 0.22, latitude: 37.7893, longitude: -122.4072 }
    ]
  } });
  expect(created.ok(), await created.text()).toBeTruthy();

  await page.goto("/workspace/command-center");
  const panel = page.locator(".panel").filter({ has: page.getByRole("heading", { name: "Use your promoted dataset" }) });
  await panel.getByLabel("Promoted dataset ID").fill(assetId);
  await panel.getByRole("button", { name: "Compile and run workflow" }).click();
  await expect(page.getByText("Your dataset is connected to a project-owned ontology, hydration pipeline, and explainable risk scorecard.")).toBeVisible();
  await expect(panel.locator(".industrial-result-summary")).toContainText("READY");
  await expect(panel.locator(".industrial-result-summary")).toContainText(/1\.\d+\.0/);
  await expect(panel.locator(".industrial-result-summary")).toContainText("2");
  await expect(panel.locator(".industrial-result-summary")).toContainText("1");
  await expect(panel.locator(".industrial-result-summary")).toContainText("Immutable source");
  await expect(panel.locator(".industrial-result-summary")).toContainText(/dataset_snapshot_/);
  await expect(panel.locator(".industrial-result-summary")).toContainText("Execution plan");
  await expect(panel.locator(".industrial-result-summary")).toContainText(/pipeline_plan_/);
  await expect(page.locator(".stepper button").filter({ hasText: "Analyze" })).toContainText("available");

  await page.locator(".top-actions").getByRole("button", { name: "Analyze your highest-risk asset" }).click();
  const governance = page.locator(".panel").filter({ has: page.getByRole("heading", { name: "Governed Approval and Action" }) });
  await expect(governance).toContainText("PENDING");
  await expect(governance).toContainText("default__request_asset_inspection");
  await governance.getByLabel("Decision reason").fill("Evaluator reviewed the imported asset evidence.");
  await governance.getByRole("button", { name: "Approve action" }).click();
  await expect(governance).toContainText("APPROVED");
  await governance.getByRole("button", { name: "Execute approved action" }).click();
  await expect(governance.getByLabel("Governed action evidence")).toContainText("SUCCESS");
  await expect(page.locator(".stepper button").filter({ hasText: "Act" })).toContainText("complete");

  const downloadPromise = page.waitForEvent("download");
  await page.locator(".top-actions").getByRole("button", { name: "Export proof report" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe("default-asset-reliability-report.md");

  const evaluatorPanel = page.locator(".panel").filter({ has: page.getByRole("heading", { name: "Independent evaluator evidence" }) });
  const evidenceButton = evaluatorPanel.getByRole("button", { name: "Export sealed evaluator evidence" });
  await expect(evidenceButton).toBeDisabled();
  await evaluatorPanel.getByLabel("External team ID").fill("browser-external-team");
  await evaluatorPanel.getByLabel("Organization ID").fill("browser-external-org");
  await evaluatorPanel.getByLabel("Deployment ID").fill("browser-deployment-001");
  await evaluatorPanel.getByLabel("Evaluator alias").fill("browser-operator");
  await evaluatorPanel.getByLabel("This team is independent from OntologyOS development.").check();
  await evaluatorPanel.getByLabel("The workflow used this organization's operational data, not the bundled sample scenario.").check();
  await expect(evidenceButton).toBeEnabled();
  const evidenceDownloadPromise = page.waitForEvent("download");
  await evidenceButton.click();
  const evidenceDownload = await evidenceDownloadPromise;
  expect(evidenceDownload.suggestedFilename()).toBe("browser-external-team-ontologyos-evaluation.json");
  await expect(evaluatorPanel.getByRole("status")).toContainText("INCOMPLETE");
  await expect(evaluatorPanel.getByRole("status")).toContainText("oidc authentication required");
  await expect(evaluatorPanel.getByRole("status")).toContainText("own data provenance required");
  await page.screenshot({ path: `test-results/screenshots/${testInfo.project.name}-industrial-connect-to-report.png`, fullPage: true });
});

test("command center monitors background snapshot onboarding", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-1280", "Run the background worker workflow once on desktop.");
  test.setTimeout(90_000);
  const assetId = `evaluator_background_assets_${Date.now()}`;
  const created = await page.request.post("/data-assets", { data: {
    id: assetId, project_id: "default", display_name: "Background evaluator assets", kind: "dataset",
    asset_schema: {
      id: "string", name: "string", status: "string", criticality: "string",
      predicted_failure_probability: "number", latitude: "number", longitude: "number"
    },
    records: [
      { id: "background-pump", name: "Background Pump", status: "DEGRADED", criticality: "high", predicted_failure_probability: 0.93, latitude: 37.78, longitude: -122.41 },
      { id: "background-chiller", name: "Background Chiller", status: "RUNNING", criticality: "medium", predicted_failure_probability: 0.18, latitude: 37.79, longitude: -122.40 }
    ]
  } });
  expect(created.ok(), await created.text()).toBeTruthy();

  await page.goto("/workspace/command-center");
  const panel = page.locator(".panel").filter({ has: page.getByRole("heading", { name: "Use your promoted dataset" }) });
  await panel.getByLabel("Promoted dataset ID").fill(assetId);
  await panel.getByLabel("Execution mode").selectOption("background");
  const responsePromise = page.waitForResponse((response) =>
    response.url().includes("/api/v1/industrial/workflows/asset-reliability/onboard") && response.request().method() === "POST"
  );
  await panel.getByRole("button", { name: "Compile and run workflow" }).click();
  const queuedResponse = await responsePromise;
  expect(queuedResponse.status()).toBe(202);
  const queued = await queuedResponse.json() as { resources: { execution_job: string } };
  await expect(panel.getByLabel("Background onboarding status")).toContainText("QUEUED");

  await page.reload();
  await expect(panel.getByLabel("Background onboarding status")).toContainText("QUEUED");

  const worker = await page.request.post("/pipeline-builder/workers/run-next", { data: {
    worker_id: "evaluator-background-worker", job_id: queued.resources.execution_job, lease_seconds: 120
  } });
  expect(worker.ok(), await worker.text()).toBeTruthy();
  await expect(panel.getByLabel("Background onboarding status")).toContainText("SUCCEEDED", { timeout: 15_000 });
  await expect(panel.locator(".industrial-result-summary")).toContainText("2");
  await expect(page.getByText("Background onboarding completed. Snapshot, ontology, risk, and execution evidence are ready.")).toBeVisible();
});

test("responsive workspace navigation stays compact and keyboard operable", async ({ page }, testInfo) => {
  test.skip(!testInfo.project.name.includes("mobile"), "Responsive navigation is exercised in a mobile project.");
  await page.goto("/workspace/ontology");
  const navigation = page.getByRole("navigation", { name: "Workspaces" });
  const toggle = page.getByRole("button", { name: "Open workspace navigation" });
  await expect(toggle).toBeVisible();
  await expect(navigation).toBeHidden();
  await toggle.focus();
  await page.keyboard.press("Enter");
  await expect(navigation).toBeVisible();
  await expect(page.getByRole("button", { name: "Close workspace navigation" })).toBeVisible();
  await navigation.getByRole("button", { name: /Pipeline Builder/ }).click();
  await expect(page).toHaveURL(/\/workspace\/pipeline$/);
  await expect(navigation).toBeHidden();
});

test("builder route transitions release collaboration stream database sessions", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-1280", "Run the streaming connection lifecycle stress once on desktop.");
  const suffix = Date.now();
  const builders = [
    { route: "workshop", artifactType: "workshop" },
    { route: "aip", artifactType: "aip_logic" },
    { route: "investigations", artifactType: "investigation_graph" },
    { route: "entity-resolution", artifactType: "entity_resolution" }
  ];
  for (const builder of builders) {
    const response = await page.request.post("/artifacts", { data: {
      id: `stream_lifecycle_${builder.artifactType}_${suffix}`,
      artifact_type: builder.artifactType,
      display_name: `Stream lifecycle ${builder.artifactType} ${suffix}`,
      state: { nodes: [], edges: [] }
    } });
    expect(response.ok()).toBeTruthy();
  }
  for (let cycle = 0; cycle < 5; cycle += 1) {
    for (const builder of builders) {
      await page.goto(`/workspace/${builder.route}`);
      await expect(page.locator(".collaboration-presence")).toBeVisible();
    }
  }
  await page.goto("/workspace/command-center");
  const probes = await Promise.all(Array.from({ length: 20 }, () => page.request.get("/jobs/summary")));
  expect(probes.every((response) => response.ok())).toBeTruthy();
});

test("visual builder reviews and applies a governed change proposal", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-1280", "Run the stateful review workflow once on desktop.");
  const suffix = Date.now();
  const artifactId = `browser_review_workshop_${suffix}`;
  const displayName = `Reviewed workshop ${suffix}`;
  const createResponse = await page.request.post("/artifacts", { data: {
    id: artifactId,
    artifact_type: "workshop",
    display_name: displayName,
    state: { nodes: [{
      id: "risk_metric",
      position: { x: 120, y: 100 },
      data: { label: "Risk metric", nodeType: "metric", fields: [] }
    }], edges: [], widgets: [] }
  } });
  expect(createResponse.status()).toBe(201);
  const artifact = await createResponse.json() as { lock_version: number };
  const proposalResponse = await page.request.post(`/api/v1/artifacts/${artifactId}/proposals`, { data: {
    title: "Clarify the risk metric",
    expected_lock_version: artifact.lock_version,
    commands: [{
      command_id: `browser-review-${suffix}`,
      command: "update_node",
      payload: { node_id: "risk_metric", changes: { data: {
        label: "Critical asset risk", nodeType: "metric", fields: []
      } } }
    }]
  } });
  expect(proposalResponse.status()).toBe(201);

  await page.goto("/workspace/workshop");
  await page.getByLabel("Workshop artifact").selectOption({ label: displayName });
  await page.getByRole("tab", { name: /Proposals/ }).click();
  await expect(page.getByText("Clarify the risk metric", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByText("APPROVED", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Apply" }).click();
  await expect(page.getByText("APPLIED", { exact: true })).toBeVisible();
  await expect(page.getByText(/Applied reviewed proposal as revision 2/)).toBeVisible();
  await expect(page.getByText("Critical asset risk", { exact: true })).toBeVisible();
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
    await expect(page.getByRole("row", { name: /s3 AVAILABLE/ })).toBeVisible();
    await expect(page.getByRole("row", { name: /sftp AVAILABLE/ })).toBeVisible();
    await expect(page.getByRole("row", { name: /kafka AVAILABLE/ })).toBeVisible();
  } finally {
    await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
  }
});

test("data onboarding exposes structured S3 configuration without raw credentials", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-1280", "Run the structured connector workflow once on desktop.");
  await page.goto("/workspace/imports");
  await page.getByLabel("Adapter").selectOption("s3");
  await expect(page.getByLabel("S3 endpoint URL")).toBeVisible();
  await expect(page.getByLabel("Bucket")).toBeVisible();
  await expect(page.getByLabel("Region")).toBeVisible();
  await expect(page.getByLabel("Object prefix")).toBeVisible();
  await expect(page.getByLabel("Authentication")).toHaveValue("aws");
  await expect(page.getByLabel("Access key ID")).toBeVisible();
  await expect(page.getByLabel("Secret access key (write only)")).toHaveAttribute("type", "password");
  await expect(page.getByLabel("Session token (optional, write only)")).toHaveAttribute("type", "password");
  await expect(page.getByRole("cell", { name: "s3" })).toBeVisible();
  await expect(page.getByRole("row", { name: /s3 AVAILABLE/ })).toBeVisible();
});

test("data onboarding exposes pinned-host SFTP configuration", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-1280", "Run the structured connector workflow once on desktop.");
  await page.goto("/workspace/imports");
  await page.getByLabel("Adapter").selectOption("sftp");
  await expect(page.getByLabel("SFTP host")).toBeVisible();
  await expect(page.getByLabel("Port")).toBeVisible();
  await expect(page.getByLabel("Username")).toBeVisible();
  await expect(page.getByLabel("Remote path")).toBeVisible();
  await expect(page.getByLabel("Host key SHA256")).toBeVisible();
  await expect(page.getByLabel("Authentication")).toHaveValue("sftp_password");
  await expect(page.getByLabel("Password", { exact: true })).toHaveAttribute("type", "password");
  await page.getByLabel("Authentication").selectOption("sftp_private_key");
  await expect(page.getByLabel("Private key (write only)")).toBeVisible();
  await expect(page.getByRole("row", { name: /sftp AVAILABLE/ })).toBeVisible();
});

test("data onboarding exposes durable Kafka partition ingestion configuration", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-1280", "Run the structured connector workflow once on desktop.");
  await page.goto("/workspace/imports");
  await page.getByLabel("Adapter").selectOption("kafka");
  await expect(page.getByLabel("Bootstrap servers")).toBeVisible();
  await expect(page.getByLabel("Topic")).toBeVisible();
  await expect(page.getByLabel("Security protocol")).toHaveValue("PLAINTEXT");
  await expect(page.getByLabel("Authentication")).toHaveValue("none");
  await page.getByLabel("Security protocol").selectOption("SASL_SSL");
  await expect(page.getByLabel("SASL mechanism")).toBeVisible();
  await expect(page.getByLabel("Authentication")).toHaveValue("kafka_sasl_plain");
  await expect(page.getByLabel("Username")).toBeVisible();
  await expect(page.getByLabel("Password", { exact: true })).toHaveAttribute("type", "password");
  await expect(page.getByRole("row", { name: /kafka AVAILABLE/ })).toBeVisible();
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

test("control panel validates, dry-runs, and restores an integrity-protected snapshot", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-1280", "Run the stateful recovery workflow once on desktop.");
  await page.goto("/workspace/control-panel");
  await page.getByRole("button", { name: "Recovery", exact: true }).click();
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download snapshot" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/^ontology-platform-.*\.json$/);
  const validationPanel = page.locator(".panel").filter({ has: page.getByRole("heading", { name: "Recovery Validation" }) });
  await expect(validationPanel).toContainText("VALID");
  await expect(validationPanel).toContainText("Resources");
  const controls = page.locator(".panel").filter({ has: page.getByRole("heading", { name: "Restore Controls" }) });
  await controls.getByRole("button", { name: "Run dry run" }).click();
  await expect(controls).toContainText("VALIDATED");
  await controls.getByLabel("Type RESTORE to confirm").fill("RESTORE");
  await controls.getByRole("button", { name: "Restore snapshot" }).click();
  await expect(controls).toContainText("IMPORTED");
});

test("control panel exposes human signed-extension onboarding and evidence", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-1280", "Run the extension administration acceptance once on desktop.");
  await page.goto("/workspace/control-panel");
  await page.getByRole("button", { name: "Extensions", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Extension Scope" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Vendor Trust Key" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Signed Package" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Active Extensions" })).toBeVisible();
  await expect(page.getByText("signed_sandbox_v1", { exact: true })).toBeVisible();
  await expect(page.getByText("v1", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Register key" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Verify package" })).toBeDisabled();
  await expect(page.locator("body")).not.toContainText("bundle_base64");
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

test("ontology release studio reviews a semantic change before publication", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-1280", "Run the stateful ontology release workflow once on desktop.");
  const suffix = Date.now();
  const objectTypeId = `release_asset_${suffix}`;
  const displayName = `Release Asset ${suffix}`;
  const created = await page.request.post("/object-types", { data: {
    id: objectTypeId,
    display_name: displayName,
    description: "Browser release acceptance type",
    properties: { asset_id: { type: "string", required: true } }
  } });
  expect(created.ok()).toBeTruthy();

  await page.goto("/workspace/ontology");
  await page.locator(".manager-resource-nav .resource-row").filter({ hasText: displayName }).click();
  await page.getByRole("button", { name: /^releases$/i }).click();
  const studio = page.locator(".ontology-release-studio");
  await expect(studio.getByRole("heading", { name: "Ontology Releases" })).toBeVisible();

  await studio.getByRole("button", { name: "Capture current" }).click();
  await expect(studio.getByRole("status")).toContainText("immutable draft revision");
  const propertyName = `reviewedField${suffix}`;
  await studio.getByLabel("Property API name").fill(propertyName);
  await studio.getByLabel("Reason and description").fill("Browser acceptance evidence for a reviewed additive change.");
  await studio.getByRole("button", { name: "Create change set" }).click();
  await studio.getByRole("button", { name: new RegExp(`^Add ${propertyName}`) }).click();
  await expect(studio.getByText("NON_BREAKING", { exact: true }).first()).toBeVisible();
  await expect(studio.getByRole("heading", { name: "Semantic diff" })).toBeVisible();
  await expect(studio.getByRole("heading", { name: "Migration plan" })).toBeVisible();

  await studio.getByRole("button", { name: "Validate", exact: true }).click();
  await expect(studio.getByRole("button", { name: "Approve", exact: true })).toBeEnabled();
  await studio.getByRole("button", { name: "Approve", exact: true }).click();
  await expect(studio.getByRole("button", { name: "Publish", exact: true })).toBeEnabled();
  await studio.getByRole("button", { name: "Publish", exact: true }).click();
  await expect(studio.getByRole("status")).toContainText("Downstream compatibility has been refreshed");
  await expect(studio.locator(".ontology-revision-history .release-table-row").first()).toBeVisible();

  const consumerId = `browser_release_consumer_${suffix}`;
  const bound = await page.request.post("/api/v1/ontology/contracts/bind", { data: {
    project_id: "default", consumer_kind: "test", consumer_id: consumerId, consumer_version: "1",
    payload: { object_type_id: objectTypeId, properties: [propertyName] }
  } });
  expect(bound.ok()).toBeTruthy();
  await studio.getByRole("button", { name: "Refresh", exact: true }).click();
  const contractHealth = studio.getByRole("region", { name: "Downstream Contract Health" });
  await expect(contractHealth).toContainText(consumerId);
  await expect(contractHealth).toContainText("CURRENT");

  await studio.getByLabel("Operation").selectOption("archive_property");
  await studio.getByLabel("Property API name").fill(propertyName);
  await studio.getByLabel("Reason and description").fill("Browser acceptance for a governed breaking ontology change.");
  await studio.getByRole("button", { name: "Create change set" }).click();
  await studio.getByRole("button", { name: new RegExp(`^Archive ${propertyName}`) }).click();
  await studio.getByRole("button", { name: "Validate", exact: true }).click();
  const affectedConsumers = studio.getByRole("heading", { name: "Affected consumers" }).locator("..");
  await expect(affectedConsumers).toBeVisible();
  await expect(affectedConsumers.getByText(consumerId, { exact: false })).toBeVisible();
  await studio.getByRole("button", { name: "Approve", exact: true }).click();
  await expect(studio.getByRole("button", { name: "Publish", exact: true })).toBeDisabled();
  await studio.getByRole("checkbox", { name: /reviewed the migration plan/i }).check();
  await expect(studio.getByRole("button", { name: "Publish", exact: true })).toBeEnabled();
  await studio.getByRole("button", { name: "Publish", exact: true }).click();
  await expect(studio.getByRole("status")).toContainText("Downstream compatibility has been refreshed");
  await expect(contractHealth).toContainText("FAIL");
  await expect(contractHealth).toContainText("BROKEN");
  await expect(contractHealth).toContainText(consumerId);
});

test("ontology health center evaluates, remediates, and simulates policy", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-1280", "Run the stateful ontology health workflow once on desktop.");
  const suffix = Date.now();
  const objectTypeId = `health_browser_asset_${suffix}`;
  const displayName = `Health Browser Asset ${suffix}`;
  const assetId = `health_browser_dataset_${suffix}`;
  expect((await page.request.post("/object-types", { data: {
    id: objectTypeId, display_name: displayName, description: "Browser health acceptance object",
    properties: { assetId: { type: "string" }, name: { type: "string" } }
  } })).ok()).toBeTruthy();
  expect((await page.request.put(`/ontology/object-types/${objectTypeId}/profile`, { data: {
    api_name: `HealthBrowserAsset${suffix}`, primary_key: "assetId", title_key: "name",
    properties: { assetId: { base_type: "string", required: true }, name: { base_type: "string", required: true } }
  } })).ok()).toBeTruthy();
  expect((await page.request.post("/data-assets", { data: {
    id: assetId, display_name: displayName, kind: "dataset", asset_schema: {}, records: [{ assetId: "HB-1", name: "Browser pump" }]
  } })).ok()).toBeTruthy();
  expect((await page.request.post("/objects", { data: {
    id: `${objectTypeId}_1`, object_type_id: objectTypeId, source_asset_id: assetId,
    properties: { assetId: "HB-1", name: "Browser pump" }
  } })).ok()).toBeTruthy();

  await page.goto("/workspace/ontology");
  await page.locator(".manager-resource-nav .resource-row").filter({ hasText: displayName }).click();
  await page.getByRole("button", { name: /^health center$/i }).click();
  const center = page.locator(".ontology-health-center");
  await expect(center.getByRole("heading", { name: "Ontology Health Center" })).toBeVisible();
  await center.getByRole("button", { name: "Run health check" }).click();
  await expect(center.getByRole("status")).toContainText("Health evaluation completed: WARN");
  await expect(center.getByText("No configured object view", { exact: true })).toBeVisible();
  await center.getByRole("button", { name: "Generate view" }).click();
  await expect(center.getByRole("status")).toContainText("Standard object view generated and published");
  await expect(center.getByText("No configured object view", { exact: true })).toHaveCount(0);
  await center.getByRole("button", { name: "Simulate", exact: true }).click();
  await expect(center.locator(".policy-decision-card")).toContainText("DENY");
  await expect(center.locator(".policy-decision-card")).toContainText("Denied by policy rule");
});

test("ontology schema registry publishes a revision and downloads source and an installable package", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-1280", "Run the stateful schema registry workflow once on desktop.");
  const suffix = Date.now();
  const objectTypeId = `registry_browser_asset_${suffix}`;
  const displayName = `Registry Browser Asset ${suffix}`;
  expect((await page.request.post("/object-types", { data: {
    id: objectTypeId, display_name: displayName, description: "Browser registry contract",
    properties: { assetId: { type: "string" }, name: { type: "string" } }
  } })).ok()).toBeTruthy();
  expect((await page.request.put(`/ontology/object-types/${objectTypeId}/profile`, { data: {
    api_name: `RegistryBrowserAsset${suffix}`, primary_key: "assetId", title_key: "name",
    properties: { assetId: { base_type: "string", required: true }, name: { base_type: "string", required: true } }
  } })).ok()).toBeTruthy();
  const createdChange = await page.request.post("/ontology/change-sets", { data: {
    project_id: "default", title: `Registry browser baseline ${suffix}`, changes: []
  } });
  expect(createdChange.ok()).toBeTruthy();
  const change = await createdChange.json();
  expect((await page.request.post(`/ontology/change-sets/${change.id}/validate`)).ok()).toBeTruthy();
  expect((await page.request.post(`/ontology/change-sets/${change.id}/decision`, { data: { approve: true } })).ok()).toBeTruthy();
  const publication = await page.request.post(`/ontology/change-sets/${change.id}/publish`, { data: { environment: "production" } });
  expect(publication.ok()).toBeTruthy();
  const published = await publication.json();
  const revisionId = published.revision.id as string;
  const version = `1.0.${suffix}`;

  await page.goto("/workspace/ontology");
  await page.locator(".manager-resource-nav .resource-row").filter({ hasText: displayName }).click();
  await page.getByRole("button", { name: /^schema registry$/i }).click();
  const registry = page.getByRole("region", { name: "Ontology schema registry" });
  await expect(registry.getByRole("heading", { name: "Schema Registry" })).toBeVisible();
  await registry.getByLabel("Published revision").selectOption(revisionId);
  await registry.getByLabel("Semantic version").fill(version);
  await registry.getByRole("button", { name: "Check compatibility" }).click();
  await expect(registry.getByRole("status")).toContainText(/Compatibility result: (NON_BREAKING|NO_CHANGE)/);
  await registry.getByRole("button", { name: "Publish registry" }).click();
  await expect(registry.getByRole("status")).toContainText(`Published production registry version ${version}`);
  await expect(registry.getByRole("button", { name: new RegExp(`${version} production`) })).toBeVisible();
  const sourceDownloadPromise = page.waitForEvent("download");
  await registry.getByRole("button", { name: "TypeScript source" }).click();
  const sourceDownload = await sourceDownloadPromise;
  expect(sourceDownload.suggestedFilename()).toBe("ontology.ts");

  const packageButton = registry.getByRole("button", { name: "Download .tgz" });
  await expect(packageButton).toBeVisible();
  await expect(registry.getByText(/@ontologyos\/default-production/)).toBeVisible();
  const packageDownloadPromise = page.waitForEvent("download");
  await packageButton.click();
  const packageDownload = await packageDownloadPromise;
  expect(packageDownload.suggestedFilename()).toBe(`ontologyos-default-production-${version}.tgz`);
  await expect(registry.getByRole("status")).toContainText("Downloaded installable @ontologyos/default-production");
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

test("pipeline deploys an immutable snapshot through visible partition-worker controls", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-1280", "Run the distributed Pipeline workflow once on desktop.");
  const suffix = Date.now();
  const assetId = `browser_distributed_asset_${suffix}`;
  const graphId = `browser_distributed_pipeline_${suffix}`;
  const graphName = `Browser distributed pipeline ${suffix}`;
  const snapshotRoot = join(tmpdir(), "ontology-platform-snapshots");
  mkdirSync(snapshotRoot, { recursive: true });
  const fixture = mkdtempSync(join(snapshotRoot, "browser-partitions-"));
  try {
    const python = process.env.PYTHON_BIN || "python";
    execFileSync(python, ["-c", [
      "import pathlib, sys",
      "import pyarrow as pa",
      "import pyarrow.parquet as pq",
      "root = pathlib.Path(sys.argv[1])",
      "root.mkdir(parents=True, exist_ok=True)",
      "for index in range(4):",
      "    rows = [{'asset_id': f'asset-{index}-high', 'score': 90 + index}, {'asset_id': f'asset-{index}-low', 'score': 20 + index}]",
      "    pq.write_table(pa.Table.from_pylist(rows), root / f'part-{index:03d}.parquet', compression='zstd')"
    ].join("\n"), fixture]);
    expect((await page.request.post("/data-assets", { data: {
      id: assetId, display_name: graphName, kind: "dataset", asset_schema: {}, records: []
    } })).ok()).toBeTruthy();
    const registeredResponse = await page.request.post(`/api/v1/datasets/${assetId}/snapshots/register`, { data: {
      storage_uri: pathToFileURL(fixture).href, storage_format: "parquet"
    } });
    const registeredBody = await registeredResponse.text();
    expect(registeredResponse.ok(), registeredBody).toBeTruthy();
    const snapshot = JSON.parse(registeredBody) as { id: string };
    expect((await page.request.post("/pipeline-builder/graphs", { data: {
      id: graphId, display_name: graphName,
      nodes: [
        { id: "input", type: "input_dataset", config: { asset_id: assetId, snapshot_id: snapshot.id } },
        { id: "filter", type: "filter", config: { field: "score", operator: "gte", value: 80 } },
        { id: "output", type: "dataset_output", config: { asset_id: `${assetId}_output` } }
      ],
      edges: [{ source: "input", target: "filter" }, { source: "filter", target: "output" }]
    } })).ok()).toBeTruthy();

    await page.goto("/workspace/pipeline");
    await page.locator(".output-rail .resource-row").filter({ hasText: graphName }).click();
    await page.getByLabel("Engine").selectOption("duckdb");
    await page.getByLabel("Delivery strategy").selectOption("partitioned");
    await page.getByLabel("Maximum partitions").fill("3");
    await page.getByRole("button", { name: "Deploy", exact: true }).click();
    const execution = page.locator(".pipeline-execution-state");
    await expect(execution).toContainText("SUCCEEDED", { timeout: 30_000 });
    await expect(execution).toContainText("partitioned");
    const partitions = execution.getByText("Partition jobs (3)").locator("xpath=..");
    await expect(partitions).toBeVisible();
    await expect(partitions.locator("tbody tr")).toHaveCount(3);
    await expect(partitions.locator("tbody")).toContainText("pipeline.duckdb.partition");
    await expect(partitions.locator("tbody")).not.toContainText("FAILED");

    const jobId = (await execution.locator("dt", { hasText: "job id" }).locator("xpath=following-sibling::dd").textContent())?.trim();
    expect(jobId).toBeTruthy();
    const jobResponse = await page.request.get(`/jobs/${jobId}`);
    expect(jobResponse.ok()).toBeTruthy();
    const job = await jobResponse.json() as { result: { row_count: number; output_snapshot: { id: string } } };
    expect(job.result.row_count).toBe(4);
    const outputRows = await page.request.post(`/api/v1/dataset-snapshots/${job.result.output_snapshot.id}/query`, { data: {
      fields: ["asset_id", "score"], order_by: "asset_id", limit: 20
    } });
    expect(outputRows.ok()).toBeTruthy();
    expect(((await outputRows.json()) as { rows: unknown[] }).rows).toHaveLength(4);
  } finally {
    rmSync(fixture, { recursive: true, force: true });
  }
});

test("pipeline ontology output previews and persists contract evidence", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-1280", "Run the stateful ontology contract workflow once on desktop.");
  const suffix = Date.now();
  const assetId = `browser_contract_asset_${suffix}`;
  const objectTypeId = `browser_contract_type_${suffix}`;
  const graphId = `browser_contract_graph_${suffix}`;
  const graphName = `Browser ontology contract ${suffix}`;
  expect((await page.request.post("/data-assets", { data: {
    id: assetId, display_name: graphName, kind: "dataset", asset_schema: {},
    records: [{ asset_id: `BC-${suffix}-1`, name: "Valid asset" }, { asset_id: `BC-${suffix}-2`, name: null }]
  } })).ok()).toBeTruthy();
  expect((await page.request.post("/object-types", { data: {
    id: objectTypeId, display_name: graphName, description: "Browser contract target",
    properties: { assetId: { type: "string" }, name: { type: "string" } }
  } })).ok()).toBeTruthy();
  expect((await page.request.put(`/ontology/object-types/${objectTypeId}/profile`, { data: {
    api_name: `BrowserContract${suffix}`, primary_key: "assetId", title_key: "name",
    properties: { assetId: { base_type: "string", required: true }, name: { base_type: "string", required: true } }
  } })).ok()).toBeTruthy();
  const environmentsResponse = await page.request.get("/ontology/environments?project_id=default");
  expect(environmentsResponse.ok()).toBeTruthy();
  const environments = await environmentsResponse.json() as Array<{ name: string; current_revision_id?: string | null }>;
  const activeRevisionId = environments.find((item) => item.name === "production")?.current_revision_id;
  const contractRelease = await page.request.post("/ontology/change-sets", { data: {
    project_id: "default", title: `Publish ${graphName}`,
    ...(activeRevisionId ? { base_revision_id: activeRevisionId } : {}),
    changes: activeRevisionId ? [{
      operation: "add_object_type",
      resource: {
        id: objectTypeId, display_name: graphName, description: "Browser contract target",
        primary_key: "assetId", title_key: "name", status: "ACTIVE",
        properties: { assetId: { base_type: "string", required: true }, name: { base_type: "string", required: true } }
      }
    }] : []
  } });
  expect(contractRelease.ok()).toBeTruthy();
  const contractChange = await contractRelease.json() as { id: string };
  expect((await page.request.post(`/ontology/change-sets/${contractChange.id}/validate`)).ok()).toBeTruthy();
  expect((await page.request.post(`/ontology/change-sets/${contractChange.id}/decision`, { data: { approve: true } })).ok()).toBeTruthy();
  expect((await page.request.post(`/ontology/change-sets/${contractChange.id}/publish`, { data: { environment: "production" } })).ok()).toBeTruthy();
  expect((await page.request.post("/pipeline-builder/graphs", { data: {
    id: graphId, display_name: graphName, nodes: [
      { id: "input", type: "input_dataset", label: "Contract input", position: { x: 80, y: 120 }, config: { asset_id: assetId } },
      { id: "ontology", type: "ontology_output", label: "Contract ontology output", position: { x: 390, y: 120 }, config: {
        object_type_id: objectTypeId, primary_key: "asset_id",
        property_mapping: { asset_id: "assetId", name: "name" }, write_mode: "upsert",
        on_error: "quarantine", quarantine_asset_id: `${assetId}_quarantine`, source_asset_id: assetId
      } }
    ], edges: [{ source: "input", target: "ontology" }]
  } })).ok()).toBeTruthy();

  await page.goto("/workspace/pipeline");
  await page.locator(".output-rail .resource-row").filter({ hasText: graphName }).click();
  await page.getByRole("button", { name: /Contract ontology output 2 rows ontology_output/ }).click();
  const contract = page.getByRole("region", { name: "Ontology output contract" });
  await expect(contract).toContainText("PARTIAL");
  await expect(contract).toContainText("1 contract issue");
  await expect(contract).toContainText("Required ontology property is missing");
  await page.getByRole("button", { name: "Deploy", exact: true }).click();
  await expect(page.locator(".pipeline-execution-state")).toContainText("SUCCEEDED");
  await expect(page.getByRole("heading", { name: "Ontology Contracts" }).locator("xpath=.." )).toContainText("WARN");
  await expect(page.getByRole("button", { name: new RegExp(`${objectTypeId} ontology PARTIAL`) })).toBeVisible();
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
  await expect(runtime.getByLabel("Execution mode")).toHaveValue("graph");
  await runtime.getByRole("button", { name: "Run agent" }).click();
  await expect(runtime.locator(".agent-job-state")).toContainText("SUCCEEDED");
  const taskGraph = runtime.getByLabel("Agent task graph");
  await expect(taskGraph).toContainText("2 independently retryable tool stages");
  await expect(taskGraph.locator("tbody tr")).toHaveCount(4);
  await expect(taskGraph).toContainText("Context");
  await expect(taskGraph).toContainText("Synthesis");
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
