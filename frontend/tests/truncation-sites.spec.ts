import { expect, test, type APIResponse, type Locator, type Page } from "@playwright/test";

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
 *
 * N9 added a third table, which the gate had read as counted: the pipeline
 * builder's contract panel summarised every issue and handed its table the first
 * twenty-five. The total was on screen, and the rows behind it were not. The N7d
 * census found it, and the gate now refuses a cut into a table that pages,
 * whatever count is beside it.
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

/** The text of one grid column's cells, in the order they are drawn. */
async function valuesOf(scope: Locator, column: string) {
  const headers = await scope.locator("thead .grid-sort").evaluateAll((buttons) =>
    buttons.map((button) => (button.textContent || "").replace(/[▲▼]/g, "").trim()));
  return scope.locator("tbody tr").evaluateAll((rows, at) => rows.map((row) => row.children[at]?.textContent || ""), headers.indexOf(column));
}

/** A published object type requiring `name`, and a graph feeding it rows with none. */
async function rejectingContract(page: Page, rejected: number) {
  // Digits only: the suffix also goes into an ontology `api_name`.
  const suffix = `${Date.now()}`;
  const assetId = `n9_contract_asset_${suffix}`;
  const objectTypeId = `n9_contract_type_${suffix}`;
  const graphName = `N9 contract ${suffix}`;
  const properties = { assetId: { base_type: "string", required: true }, name: { base_type: "string", required: true } };
  const settled = async (response: APIResponse) => {
    expect(response.ok(), await response.text()).toBeTruthy();
    return response;
  };
  await settled(await page.request.post("/data-assets", { data: {
    id: assetId, display_name: graphName, kind: "dataset", asset_schema: {},
    records: Array.from({ length: rejected }, (unused, index) => ({ asset_id: `N9-${suffix}-${index}`, name: null }))
  } }));
  await settled(await page.request.post("/object-types", { data: {
    id: objectTypeId, display_name: graphName, description: "N9 contract target",
    properties: { assetId: { type: "string" }, name: { type: "string" } }
  } }));
  await settled(await page.request.put(`/ontology/object-types/${objectTypeId}/profile`, { data: {
    api_name: `NineContract${suffix}`, primary_key: "assetId", title_key: "name", properties
  } }));
  const environments = await (await page.request.get("/ontology/environments?project_id=default")).json() as Array<{ name: string; current_revision_id?: string | null }>;
  const activeRevisionId = environments.find((item) => item.name === "production")?.current_revision_id;
  const release = await page.request.post("/ontology/change-sets", { data: {
    project_id: "default", title: `Publish ${graphName}`,
    ...(activeRevisionId ? { base_revision_id: activeRevisionId } : {}),
    changes: activeRevisionId ? [{ operation: "add_object_type", resource: {
      id: objectTypeId, display_name: graphName, description: "N9 contract target",
      primary_key: "assetId", title_key: "name", status: "ACTIVE", properties
    } }] : []
  } });
  await settled(release);
  const change = await release.json() as { id: string };
  await settled(await page.request.post(`/ontology/change-sets/${change.id}/validate`));
  await settled(await page.request.post(`/ontology/change-sets/${change.id}/decision`, { data: { approve: true } }));
  await settled(await page.request.post(`/ontology/change-sets/${change.id}/publish`, { data: { environment: "production" } }));
  await settled(await page.request.post("/pipeline-builder/graphs", { data: {
    id: `n9_contract_graph_${suffix}`, display_name: graphName, nodes: [
      { id: "input", type: "input_dataset", label: "Contract input", position: { x: 80, y: 120 }, config: { asset_id: assetId } },
      { id: "ontology", type: "ontology_output", label: "Contract ontology output", position: { x: 390, y: 120 }, config: {
        object_type_id: objectTypeId, primary_key: "asset_id", property_mapping: { asset_id: "assetId", name: "name" },
        write_mode: "upsert", on_error: "quarantine", quarantine_asset_id: `${assetId}_quarantine`, source_asset_id: assetId
      } }
    ], edges: [{ source: "input", target: "ontology" }]
  } }));
  return graphName;
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
      .toHaveText(`Showing 1–40 of ${loaded} rows`);
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
    await expect(panel.locator("caption")).toHaveText("Showing 1–40 of 250 rows");
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

  test("the contract panel's issues can all be read, and it says when the contract kept fewer", async ({ page }) => {
    // 130 rejected rows, one missing `name` each: past the twenty-five the call
    // site kept, past the forty the table renders, and past the 100 violations
    // the contract carries. The old build shows twenty-five rows and no caption.
    // A build that removed only the call-site cut captions 100 and says nothing
    // of the other thirty.
    const graphName = await rejectingContract(page, 130);
    await page.goto("/workspace/pipeline");
    await page.locator(".output-rail .resource-row").filter({ hasText: graphName }).click();
    await page.getByRole("button", { name: /Contract ontology output \d+ rows ontology_output/ }).click();
    const contract = page.getByRole("region", { name: "Ontology output contract" });
    const issues = contract.locator("details").filter({ has: page.locator("summary", { hasText: "contract issues" }) });
    // Its own summary: the grid nests its filter and column disclosures inside.
    await expect(issues.locator(":scope > summary")).toHaveText("100 contract issues");

    await expect(issues.locator("tbody tr")).toHaveCount(40);
    await expect(issues.locator("caption"),
                 "the panel cut its issues before the table saw them, so the table had nothing to count")
      .toHaveText("Showing 1–40 of 100 rows");
    await issues.getByRole("button", { name: "Next rows" }).click();
    await issues.getByRole("button", { name: "Next rows" }).click();
    await expect(issues.locator("caption"), "the last issue the contract carries cannot be reached")
      .toHaveText("Showing 81–100 of 100 rows");

    await expect(issues.getByRole("note"),
                 "130 rows were rejected and the contract carries 100, and nothing says so")
      .toHaveText("Listing the issues of the first 100 of 130 rejected rows");
  });

  test("contract issues sort, and say they rank only the issues the contract carries", async ({ page }) => {
    // The same 130 rejected rows. The contract carries the issues of the first 100, so
    // a descending sort by row puts row 100 on top, where it reads as the last rejected
    // row unless something says thirty more were rejected after it.
    const graphName = await rejectingContract(page, 130);
    await page.goto("/workspace/pipeline");
    await page.locator(".output-rail .resource-row").filter({ hasText: graphName }).click();
    await page.getByRole("button", { name: /Contract ontology output \d+ rows ontology_output/ }).click();
    const contract = page.getByRole("region", { name: "Ontology output contract" });
    const issues = contract.locator("details").filter({ has: page.locator("summary", { hasText: "contract issues" }) });
    const rowHeader = issues.locator("thead th").filter({ has: page.getByRole("button", { name: "row", exact: true }) });
    const scope = issues.locator(".grid-sort-scope");
    await expect(issues.locator("tbody tr")).toHaveCount(40);
    await expect(scope, "an unsorted grid has no sort to qualify").toHaveCount(0);

    await rowHeader.getByRole("button").click();
    await expect(rowHeader).toHaveAttribute("aria-sort", "ascending");
    await expect.poll(async () => (await valuesOf(issues, "row"))[0]).toBe("1");
    await rowHeader.getByRole("button").click();
    await expect(rowHeader).toHaveAttribute("aria-sort", "descending");
    await expect.poll(async () => (await valuesOf(issues, "row"))[0], "the issues do not sort by row").toBe("100");
    await expect(scope, "a sort of the 100 issues the contract kept does not say it ranks only those")
      .toHaveText("Sorted by row: this orders only the issues of the first 100 of 130 rejected rows.");
    // No gate sees how the contract panel's own styles land on the grid inside it.
    await issues.screenshot({ path: "test-results/screenshots/contract-issues-grid.png" });

    await rowHeader.getByRole("button").click();
    await expect(rowHeader).toHaveAttribute("aria-sort", "none");
    await expect(scope, "the sentence outlived the sort it described").toHaveCount(0);
  });
});
