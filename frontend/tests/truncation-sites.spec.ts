import { expect, test, type Page } from "@playwright/test";

/**
 * The two tables `audit_table_truncation` found cutting in silence.
 *
 * N8 of `GOAL_HONEST_UI_2026-09-11.md`. N4's gate counted four truncations
 * reaching a table and two of them silent:
 *
 *   OpsWorkspace     events.slice(0, 25) -> rows -> <DataTable>
 *   ObjectExplorer   query.columns.slice(0, 8) -> <table>
 *
 * The first is the way round N3's caption: `DataTable` counts what it is given,
 * so rows cut before they arrive leave it nothing to count. The second is the
 * eight-column cap N3 removed from the shared table, alive in the one screen
 * that draws its own.
 *
 * Both fixes met a second cut one layer down, on the server, and a caption over
 * a list the server had already trimmed would have said a wrong number where
 * there used to be none. The events endpoint stops at the 250 the client asks
 * for, and `_object_schema_columns` returned at most twelve. Each test here is
 * sized past both layers, so each would fail against a build that fixed only
 * the one the gate could see.
 */
const FEED = "Live Operational Feed";

async function ingest(page: Page, count: number, label: string) {
  // Batched rather than one at a time or all at once: sequential posts cost the
  // test its timeout at 250, and 250 at once is a load test, not a fixture.
  for (let start = 0; start < count; start += 25) {
    const batch = Array.from({ length: Math.min(25, count - start) }, (unused, offset) =>
      page.request.post("/ops/events/ingest", { data: {
        source: "truncation-fixture", event_type: "fixture.row", severity: "medium",
        title: `${label} ${start + offset}`
      } }));
    for (const response of await Promise.all(batch)) {
      expect(response.ok(), await response.text()).toBeTruthy();
    }
  }
}

async function eventsHeld(page: Page) {
  const summary = await page.request.get("/ops/summary");
  expect(summary.ok()).toBeTruthy();
  return (await summary.json()).events as number;
}

function feedTable(page: Page) {
  return page.locator(".panel").filter({ has: page.getByRole("heading", { name: FEED }) });
}

test.describe("a table the gate found says what it is not showing", () => {
  test.beforeEach(async ({}, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-1280", "Runs once; the fixtures are stateful.");
  });

  test("the operations feed hands every loaded event to the table, which counts them", async ({ page }) => {
    // Forty-one is past both the twenty-five the call site used to keep and the
    // forty the table renders, so the old build shows twenty-five rows and no
    // caption, and the new one shows forty under a caption.
    await ingest(page, 41, `Feed row ${Date.now()}`);
    const loaded = (await (await page.request.get("/ops/events?limit=250")).json()).length as number;
    expect(loaded, "the fixture did not land").toBeGreaterThan(40);

    await page.goto("/workspace/ops");
    const panel = feedTable(page);
    await expect(panel.locator("tbody tr")).toHaveCount(40);
    await expect(panel.locator("caption"),
                 "the feed cut its events before the table saw them, so the table had nothing to count")
      .toHaveText(`Showing 40 of ${loaded} rows`);
  });

  test("the feed says so when the server holds more events than it loaded", async ({ page }) => {
    // The events endpoint returns at most the 250 the client asks for. Past
    // that, the table's own caption reads "40 of 250" -- true of what arrived,
    // silent about what did not -- so the panel says how many exist.
    const before = await eventsHeld(page);
    await ingest(page, Math.max(0, 251 - before), `Held row ${Date.now()}`);
    const held = await eventsHeld(page);
    expect(held, "the fixture did not reach past the endpoint's limit").toBeGreaterThan(250);

    await page.goto("/workspace/ops");
    const panel = feedTable(page);
    await expect(panel.locator("caption")).toHaveText("Showing 40 of 250 rows");
    await expect(panel.getByRole("note"),
                 "the server holds more events than the feed loaded, and nothing says so")
      .toHaveText(`Loaded the latest 250 of ${held.toLocaleString("en-US")} events`);
  });

  test("the object explorer names the columns it is not drawing", async ({ page }) => {
    // Fourteen properties: past the eight the explorer draws, and past the
    // twelve the query endpoint used to return, so a build that captioned the
    // client cut and left the server's would read "8 of 12".
    const stamp = Date.now();
    const typeId = `wide_explorer_${stamp}`;
    const names = Array.from({ length: 14 }, (unused, index) => `p${String(index + 1).padStart(2, "0")}`);
    const values = Object.fromEntries(names.map((name) => [name, `${name}-value`]));
    expect((await page.request.post("/object-types", { data: {
      id: typeId, display_name: `Wide Explorer ${stamp}`, description: "Fourteen properties",
      properties: Object.fromEntries(names.map((name) => [name, { type: "string" }]))
    } })).ok()).toBeTruthy();
    const assetId = `wide_explorer_dataset_${stamp}`;
    expect((await page.request.post("/data-assets", { data: {
      id: assetId, display_name: `Wide Explorer ${stamp}`, kind: "dataset", asset_schema: {}, records: [values]
    } })).ok()).toBeTruthy();
    const object = await page.request.post("/objects", { data: {
      id: `${typeId}_1`, object_type_id: typeId, source_asset_id: assetId, properties: values
    } });
    expect(object.ok(), await object.text()).toBeTruthy();

    await page.goto(`/workspace/object-explorer?type=${typeId}`);
    const table = page.locator(".explorer-table table");
    await expect(table).toContainText(`${typeId}_1`);
    await expect(table.locator("caption"),
                 "the explorer draws eight of the type's columns and does not say there are more")
      .toHaveText("Showing 8 of 14 columns");
  });

  test("an explorer table drawing every column says nothing", async ({ page }) => {
    // The same rule as N3's complete table: a caption reading "3 of 3" teaches a
    // person to stop reading captions.
    const stamp = Date.now();
    const typeId = `narrow_explorer_${stamp}`;
    const values = { name: "Narrow", status: "ok", owner: "fixture" };
    expect((await page.request.post("/object-types", { data: {
      id: typeId, display_name: `Narrow Explorer ${stamp}`, description: "Three properties",
      properties: { name: { type: "string" }, status: { type: "string" }, owner: { type: "string" } }
    } })).ok()).toBeTruthy();
    const assetId = `narrow_explorer_dataset_${stamp}`;
    expect((await page.request.post("/data-assets", { data: {
      id: assetId, display_name: `Narrow Explorer ${stamp}`, kind: "dataset", asset_schema: {}, records: [values]
    } })).ok()).toBeTruthy();
    expect((await page.request.post("/objects", { data: {
      id: `${typeId}_1`, object_type_id: typeId, source_asset_id: assetId, properties: values
    } })).ok()).toBeTruthy();

    await page.goto(`/workspace/object-explorer?type=${typeId}`);
    const table = page.locator(".explorer-table table");
    await expect(table).toContainText(`${typeId}_1`);
    await expect(table.locator("caption"),
                 "a table drawing every column is announcing a truncation that did not happen")
      .toHaveCount(0);
  });
});
