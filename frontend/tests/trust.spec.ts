import { expect, test, type Page } from "@playwright/test";

/**
 * What the app must not claim, and what must not take it down.
 * `GOAL_FOUNDATIONS_2026-09-25.md`.
 *
 * A2: browser storage is a convenience. A private window, blocked site data or a
 * full quota makes it throw, and an older build can leave any shape in it. Before
 * A2, five storage calls were unguarded and nothing caught an error thrown by a
 * screen, so React unmounted the whole root: a blank page, sidebar and all.
 *
 * Storage and error handling do not change with the viewport, so these run once,
 * on desktop. Each was run against a build with the thing it defends removed, and
 * failed, before it was believed.
 */

// Every Storage method throws, as it does with site data blocked.
async function blockStorage(page: Page) {
  await page.addInitScript(() => {
    const refuse = () => {
      throw new DOMException("The operation is insecure.", "SecurityError");
    };
    for (const method of ["getItem", "setItem", "removeItem", "clear", "key"]) {
      Object.defineProperty(Storage.prototype, method, { configurable: true, value: refuse });
    }
  });
}

async function shellStands(page: Page, heading: string) {
  await expect(page.locator(".sidebar"), "the sidebar").toBeVisible();
  await expect(page.getByRole("heading", { name: heading, exact: true }).first(), `the ${heading} heading`).toBeVisible();
}

// A builder's collaboration effect reads storage once an artifact exists; its join
// request is the sign that the effect ran without throwing.
async function openBuilderWithArtifact(page: Page, view: string) {
  const joined = page.waitForRequest((request) => /\/artifacts\/[^/]+\/collaboration\/join$/.test(new URL(request.url()).pathname));
  await page.goto(`/workspace/${view}`);
  const create = page.getByRole("button", { name: "Create draft" });
  await expect(create.or(page.locator(".visual-builder-shell")).first()).toBeVisible();
  if (await create.isVisible()) await create.click();
  await joined;
}

test.describe("GOAL_FOUNDATIONS A2", () => {
  test.beforeEach(({}, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-1280", "Storage and error handling are checked once, on desktop.");
  });

  test("A blocked store leaves every screen standing", async ({ page }) => {
    await blockStorage(page);
    await page.goto("/workspace/command-center");
    await shellStands(page, "Asset Reliability Command Center");

    for (const [view, title] of [["workshop", "Workshop"], ["aip", "AIP Logic"],
                                 ["investigations", "Investigations"], ["entity-resolution", "Entity Resolution"]]) {
      await openBuilderWithArtifact(page, view);
      await shellStands(page, title);
    }

    // Platform Graph reads its saved layout once the overview has loaded, and places
    // the nodes only after that read; the asset scenario gives it nodes to place.
    expect((await page.request.post("/scenarios/asset-reliability/bootstrap", { data: {} })).ok()).toBeTruthy();
    await page.goto("/workspace/graph");
    await expect(page.locator(".react-flow__node").first(), "a placed graph node").toBeVisible();
    await shellStands(page, "Platform Graph");
  });

  for (const stored of ["{bad", "null", "\"x\""]) {
    test(`A corrupt recents list is ignored: ${stored}`, async ({ page }) => {
      await page.addInitScript((value) => window.localStorage.setItem("ontology.recentViews", value), stored);
      await page.goto("/workspace/command-center");
      await shellStands(page, "Asset Reliability Command Center");
      await expect(page.locator(".recent-links"), "no recents from a corrupt list").toHaveCount(0);
    });
  }

  // The boundary: an overview whose nodes are not a list makes Platform Graph throw
  // in its layout effect. The shell stands, the failure names the screen, and the
  // sidebar still navigates.
  test("A screen that throws leaves the shell standing and names itself", async ({ page }) => {
    await page.route((url) => url.pathname === "/graph/overview",
                     (route) => route.fulfill({ json: { nodes: "not a list", edges: [], summary: {} } }));
    await page.goto("/workspace/graph");
    await expect(page.getByRole("alert").filter({ hasText: "Platform Graph failed." }), "the screen's failure").toBeVisible();
    await expect(page.locator(".sidebar"), "the sidebar").toBeVisible();
    await page.locator(".sidebar").getByRole("button", { name: /^Command Center/ }).click();
    await shellStands(page, "Asset Reliability Command Center");
  });
});

/**
 * A3: each screen claims only what it does. One test per screen; each checks the
 * screen's words against what its control actually does.
 */
test.describe("GOAL_FOUNDATIONS A3", () => {
  test.beforeEach(({}, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-1280", "Claims are checked once, on desktop.");
  });

  // a. Neighbors narrows the graph to a node's neighbours among the nodes already
  // loaded; it fetches nothing. So nothing on the page may promise to expand one.
  test("Platform Graph promises only the neighbours it has loaded", async ({ page }) => {
    expect((await page.request.post("/scenarios/asset-reliability/bootstrap", { data: {} })).ok()).toBeTruthy();
    await page.goto("/workspace/graph");
    const node = page.locator(".react-flow__node").first();
    await expect(node).toBeVisible();
    await node.click();
    const requested: string[] = [];
    page.on("request", (request) => {
      const path = new URL(request.url()).pathname;
      if (path.startsWith("/graph/")) requested.push(path);
    });
    await page.getByRole("button", { name: "Neighbors" }).click();
    await expect(page.getByRole("button", { name: "Show all loaded nodes" })).toBeVisible();
    expect(requested, "turning on Neighbors fetches nothing").toEqual([]);
    await expect(page.locator(".page-header"), "the header's promise").not.toContainText(/expand/i);
  });

  // b. An automation created with "Enabled on create" unchecked was never paused,
  // yet it read "paused" in the metric, its row and its detail. The backend has one
  // switch, so the screen names the off state for what it is.
  test("Automate does not call a never-enabled automation paused", async ({ page }) => {
    await page.goto("/workspace/automate");
    await expect(page.getByRole("heading", { name: "Automate", exact: true })).toBeVisible();
    const name = `Created off ${Date.now()}`;
    await page.getByLabel("Display name").fill(name);
    const enabled = page.getByRole("checkbox", { name: "Enabled on create" });
    if (await enabled.isChecked()) await enabled.uncheck();
    await page.getByRole("button", { name: "Create automation" }).click();
    const row = page.locator("tr").filter({ hasText: name });
    await expect(row).toBeVisible();
    await expect(row.locator(".badge").first(), "its row").toHaveText("disabled");
    await expect(page.locator(".metric-card").filter({ hasText: /paused/i }), "a Paused metric").toHaveCount(0);
    await row.click();
    await expect(page.locator("section.panel").filter({ has: page.getByRole("heading", { name: "Automation Detail" }) })
      .locator(".badge").first(), "its detail").toHaveText("disabled");
  });

  // c. "Create release" keyed on the submission having trained, not on the gate the
  // Gates tab shows, and its first request marked the submission released before the
  // gated release was refused. A pending manual gate makes a submission ineligible.
  test("ModelOps releases only what its gates allow", async ({ page }) => {
    const suffix = Date.now();
    const assetId = `release_gate_${suffix}`;
    expect((await page.request.post("/data-assets", { data: {
      id: assetId, display_name: "Release gate data", kind: "dataset", asset_schema: {},
      records: [{ temperature: 10, pressure: 20, risk_score: 15 }, { temperature: 30, pressure: 60, risk_score: 45 }],
    } })).ok()).toBeTruthy();
    const objective = await (await page.request.post("/modeling/objectives", { data: {
      display_name: `Release gate ${suffix}`, problem_type: "regression", target_field: "risk_score",
      feature_fields: ["temperature", "pressure"], input_asset_id: assetId,
    } })).json();
    const submission = await (await page.request.post(`/modeling/objectives/${objective.id}/train`,
                                                      { data: { training_dataset_id: assetId } })).json();
    expect((await page.request.post(`/modeling/objectives/${objective.id}/checks`,
                                    { data: { name: "human_review", check_type: "manual" } })).ok()).toBeTruthy();

    const released: string[] = [];
    page.on("request", (request) => {
      if (request.method() === "POST" && /\/release(s)?$/.test(new URL(request.url()).pathname)) released.push(request.url());
    });
    await page.goto("/workspace/models");
    await page.getByLabel("Selected objective").selectOption(objective.id);
    await page.getByLabel("Selected submission").selectOption(submission.id);
    await page.getByRole("button", { name: "Releases & Deployments", exact: true }).click();
    await expect(page.getByRole("button", { name: "Create release" }), "Create release, with a gate pending").toBeDisabled();
    await expect(page.getByRole("note").filter({ hasText: "has not passed its gates" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Start deployment" }), "Start deployment").toBeDisabled();
    expect(released, "no release request was sent").toEqual([]);
  });

  // d. The alert-rule form and the test-event form shared one severity and one source:
  // choosing the event's severity changed the rule's, and the event, which had no source
  // field, posted whatever the rule's source input held.
  test("Ops' rule form and test-event form keep their own fields", async ({ page }) => {
    await page.goto("/workspace/ops");
    await page.getByRole("button", { name: "Alerts", exact: true }).click();
    await page.getByLabel("Operational event severity").selectOption("critical");
    await expect(page.getByLabel("Alert minimum severity"), "the rule's minimum severity").toHaveValue("high");
    await page.getByLabel("Alert rule source").fill("rule-only-source");
    const ingested = page.waitForRequest((request) => request.method() === "POST"
      && new URL(request.url()).pathname === "/ops/events/ingest");
    await page.getByLabel("Operational event title").fill(`Own fields ${Date.now()}`);
    await page.getByRole("button", { name: "Ingest event" }).click();
    const body = (await ingested).postDataJSON();
    expect.soft(body.severity, "the event's severity").toBe("critical");
    expect.soft(body.source, "the event's source").toBe("decision");
  });
});
