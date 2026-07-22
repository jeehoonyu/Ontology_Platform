import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

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
  "validation"
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

test("visual builder supports keyboard add, editable fields, save, and publish", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-1280", "Run the stateful builder workflow once on desktop.");
  await page.goto("/workspace/workshop");
  const create = page.getByRole("button", { name: "Create draft" });
  const canvas = page.locator(".visual-flow-canvas");
  await expect(create.or(canvas)).toBeVisible();
  if (await create.isVisible()) await create.click();
  await expect(canvas).toBeVisible();
  await page.getByRole("button", { name: /Metric Show an operational KPI/ }).click();
  await expect(page.getByRole("heading", { name: "Node settings" })).toBeVisible();
  await page.getByRole("button", { name: "Add" }).click();
  await page.getByLabel("Field name").fill("metricBinding");
  await page.getByLabel("Field value").fill("asset.risk.score");
  await page.getByRole("button", { name: /Save/ }).click();
  await expect(page.locator(".operation-message")).toContainText(/Saved revision/);
  await page.getByRole("button", { name: /Publish/ }).click();
  await expect(page.locator(".operation-message")).toContainText(/Published revision/);
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

test("platform graph supports selection, dragging, and neighborhood exploration", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-1280", "Run the stateful graph workflow once on desktop.");
  await page.request.post("/scenarios/asset-reliability/bootstrap", { data: {} });
  await page.goto("/workspace/graph");
  const canvas = page.locator(".platform-graph-canvas");
  const firstNode = canvas.locator(".react-flow__node").first();
  await expect(firstNode).toBeVisible();
  const before = await firstNode.boundingBox();
  expect(before).not.toBeNull();
  await firstNode.dragTo(canvas, { targetPosition: { x: 440, y: 260 } });
  const after = await firstNode.boundingBox();
  expect(after).not.toBeNull();
  expect(Math.abs((after?.x || 0) - (before?.x || 0)) + Math.abs((after?.y || 0) - (before?.y || 0))).toBeGreaterThan(5);
  await firstNode.click();
  await expect(page.getByRole("heading", { name: "Selected Resource" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Neighbors" })).toBeEnabled();
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
