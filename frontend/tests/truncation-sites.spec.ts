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

/**
 * How far a statement's text runs past the nearest box that clips it: its own, the pane,
 * the table's scroll area, or the window. A caption's words are measured in the span that
 * holds them. `scrollWidth` cannot see this for that span, which is as wide as its words
 * wherever they end up, so the words themselves are measured.
 */
async function hiddenPx(statement: Locator) {
  return statement.evaluate((element) => {
    const target = element.tagName === "CAPTION" && element.firstElementChild ? element.firstElementChild : element;
    let limit = document.documentElement.clientWidth;
    // From the statement's own box outwards: a line cut behind its own ellipsis hides its
    // count as surely as a pane's edge does.
    for (let node: Element | null = target; node; node = node.parentElement) {
      if (/(auto|scroll|hidden|clip)/.test(getComputedStyle(node).overflowX)) limit = Math.min(limit, node.getBoundingClientRect().right);
    }
    const range = document.createRange();
    range.selectNodeContents(target);
    return Math.round(range.getBoundingClientRect().right - limit);
  });
}

/** A statement of how much is missing loses the count at its end when it runs past the edge. */
async function expectUnclipped(statement: Locator, message: string) {
  await expect.poll(() => hiddenPx(statement), { message }).toBeLessThanOrEqual(1);
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

/**
 * A fresh object type of `count` real objects for the Decision workspace, hydrated by
 * one pipeline run, with a rule and a scorecard under which an object at an index in
 * `risky` scores 90 (critical) and every other object 0 (low).
 */
async function riskScoredType(page: Page, count: number, risky: Set<number>) {
  const suffix = `${Date.now()}`;
  const typeId = `risk_board_${suffix}`;
  const settled = async (response: APIResponse, label: string) => {
    const text = await response.text();
    expect(response.ok(), `${label}: ${text.slice(0, 500)}`).toBeTruthy();
    return JSON.parse(text || "null");
  };
  await settled(await page.request.post("/object-types", { data: {
    id: typeId, display_name: `Risk board ${suffix}`, description: "Decision workspace limits",
    properties: { name: { type: "string" }, status: { type: "string" }, criticality: { type: "string" } }
  } }), "object type");
  const records = Array.from({ length: count }, (unused, offset) => {
    const index = offset + 1;
    return {
      id: `${typeId}_${String(index).padStart(4, "0")}`, name: `Object ${index}`,
      status: risky.has(index) ? "DEGRADED" : "RUNNING", criticality: risky.has(index) ? "high" : "low"
    };
  });
  await settled(await page.request.post("/data-assets", { data: {
    id: `${typeId}_feed`, display_name: `Risk board feed ${suffix}`, kind: "dataset", asset_schema: {}, records
  } }), "feed");
  await settled(await page.request.post("/pipelines", { data: {
    id: `${typeId}_hydrate`, display_name: `Risk board hydrate ${suffix}`, input_asset_id: `${typeId}_feed`,
    steps: [{ operation: "map_to_ontology", object_type_id: typeId, object_id_field: "id",
              property_map: { name: "$name", status: "$status", criticality: "$criticality" }, omit_nulls: true }]
  } }), "pipeline");
  // The run route answers 200 when the run fails, so its status is what is checked.
  const run = await settled(await page.request.post(`/pipelines/${typeId}_hydrate/run?actor=test`), "hydrate");
  expect(run.status, JSON.stringify(run).slice(0, 500)).toBe("SUCCESS");
  await settled(await page.request.post("/decision/rules", { data: {
    id: `${typeId}_degraded`, display_name: "Degraded", object_type_id: typeId,
    expression: { field: "status", op: "eq", value: "DEGRADED" }, severity: "high"
  } }), "rule");
  await settled(await page.request.post("/decision/scorecards", { data: {
    id: `${typeId}_scorecard`, display_name: "Risk board scorecard", object_type_id: typeId,
    features: [
      { rule_id: `${typeId}_degraded`, weight: 60, reason: "degraded" },
      { field: "criticality", op: "eq", value: "high", weight: 30, reason: "high criticality" }
    ],
    thresholds: { medium: 35, high: 65, critical: 85 }
  } }), "scorecard");
  return typeId;
}

/**
 * A fresh object type of real objects for entity resolution, hydrated by one pipeline
 * run. `build` makes the records from the type id, each with an `id`, and any of `name`,
 * `serial_number` and `status`.
 */
async function entityType(page: Page, build: (typeId: string) => Array<Record<string, string>>) {
  const suffix = `${Date.now()}`;
  const typeId = `entity_scan_${suffix}`;
  const settled = async (response: APIResponse, label: string) => {
    const text = await response.text();
    expect(response.ok(), `${label}: ${text.slice(0, 500)}`).toBeTruthy();
    return JSON.parse(text || "null");
  };
  await settled(await page.request.post("/object-types", { data: {
    id: typeId, display_name: `Entity scan ${suffix}`, description: "Entity resolution coverage",
    properties: { name: { type: "string" }, serial_number: { type: "string" }, status: { type: "string" } }
  } }), "object type");
  await settled(await page.request.post("/data-assets", { data: {
    id: `${typeId}_feed`, display_name: `Entity scan feed ${suffix}`, kind: "dataset", asset_schema: {}, records: build(typeId)
  } }), "feed");
  await settled(await page.request.post("/pipelines", { data: {
    id: `${typeId}_hydrate`, display_name: `Entity scan hydrate ${suffix}`, input_asset_id: `${typeId}_feed`,
    steps: [{ operation: "map_to_ontology", object_type_id: typeId, object_id_field: "id",
              property_map: { name: "$name", serial_number: "$serial_number", status: "$status" }, omit_nulls: true }]
  } }), "pipeline");
  const run = await settled(await page.request.post(`/pipelines/${typeId}_hydrate/run?actor=test`), "hydrate");
  expect(run.status, JSON.stringify(run).slice(0, 500)).toBe("SUCCESS");
  return typeId;
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
    await expectUnclipped(panel.getByRole("note"), "the note is cut off, hiding how many events the server holds");
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
    // The Outputs pane is about 180px wide at this viewport, narrower than the sentence.
    await expectUnclipped(issues.getByRole("note"), "the note is cut off in the Outputs pane, hiding how many rows were rejected");

    // A filter gives the grid its longest caption, about twice the pane's width on one line.
    await issues.locator("details.grid-filters summary").click();
    await issues.getByRole("textbox", { name: "Rows where field contains", exact: true }).fill("name");
    await expect(issues.locator("caption")).toContainText("100 rows in all · filtered on field");
    await expectUnclipped(issues.locator("caption"), "the filtered caption runs past the pane, hiding how many rows there are in all");
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

  test("the Outputs pane keeps a table's caption and a contract's counts in view, at its default and narrow widths", async ({ page }) => {
    // The pane is 220px wide by default and 160px at its narrowest. A table's caption there
    // sits in a table at least 620px wide, and a contract row kept its counts in a narrow
    // column behind an ellipsis. Measured before the fix, with 12,345 lineage rows: the
    // caption, paged past row 80, ran 13px past its scroll area and 73px at the narrow
    // width; the counts lost 31px, and 89px narrow.
    //
    // The lineage is real. An input's field lineage has a row per field, so one record of
    // 1,200 fields gives 1,200 rows. Counts in the thousands come only from a run over that
    // many rows, so the contracts reply is the real one with just its counts enlarged.
    const suffix = `${Date.now()}`;
    const assetId = `outputs_lineage_${suffix}`;
    const graphName = `Outputs lineage ${suffix}`;
    const wideRecord = Object.fromEntries(Array.from({ length: 1200 }, (unused, index) => [`f${String(index + 1).padStart(4, "0")}`, "v"]));
    const asset = await page.request.post("/data-assets", { data: {
      id: assetId, display_name: graphName, kind: "dataset", asset_schema: {}, records: [wideRecord]
    } });
    expect(asset.ok(), await asset.text()).toBeTruthy();
    const graph = await page.request.post("/pipeline-builder/graphs", { data: {
      id: `outputs_lineage_graph_${suffix}`, display_name: graphName,
      nodes: [{ id: "input", type: "input_dataset", label: "Lineage input", position: { x: 80, y: 120 }, config: { asset_id: assetId } }],
      edges: []
    } });
    expect(graph.ok(), await graph.text()).toBeTruthy();
    await page.route((url) => /\/ui-state\/pipeline\/[^/]+\/ontology-contracts$/.test(url.pathname), async (route) => {
      const response = await route.fetch();
      const body = await response.json();
      const contract = {
        field_lineage: [], violations: [], input_rows: 15801, created_objects: 0, updated_objects: 0, unchanged_objects: 0,
        ...(body.sections?.latest?.[0] ?? {}),
        node_id: "ontology", object_type_id: "enlarged_counts", status: "PARTIAL", accepted_rows: 12345, rejected_rows: 3456
      };
      body.sections = { ...body.sections, latest: [contract] };
      await route.fulfill({ response, json: body });
    });
    await page.goto("/workspace/pipeline");
    await page.locator(".output-rail .resource-row").filter({ hasText: graphName }).click();
    // Chosen by name: switching graphs does not clear the node selected on the last one.
    await page.getByRole("button", { name: /Lineage input \d+ rows input_dataset/ }).click();

    // No locale is pinned, so the numbers are formatted the way this browser formats them.
    const [total, accepted, rejected] = await page.evaluate(() => [(1200).toLocaleString(), (12345).toLocaleString(), (3456).toLocaleString()]);
    const lineage = page.locator(".pipeline-lineage-details");
    await lineage.locator("summary").click();
    await lineage.getByRole("button", { name: "Next rows" }).click();
    await lineage.getByRole("button", { name: "Next rows" }).click();
    const caption = lineage.locator("caption");
    await expect(caption).toHaveText(`Showing 81–120 of ${total} rows`);
    const counts = page.locator(".ontology-contract-row small", { hasText: "accepted" });
    await expect(counts).toHaveText(`${accepted} accepted / ${rejected} rejected`);

    await expectUnclipped(caption, "the lineage caption runs past the table's scroll area, hiding how many rows there are");
    await expectUnclipped(counts, "the contract's counts are cut off, hiding how many rows were rejected");

    await page.getByLabel("Width of right pane").selectOption({ label: "Narrow · 160px" });
    await expectUnclipped(caption, "at the pane's narrow width the lineage caption runs past the table's scroll area");
    await expectUnclipped(counts, "at the pane's narrow width the contract's counts are cut off");
  });
});

test.describe("a list the gate cannot see says what it is not showing", () => {
  test.beforeEach(async ({}, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-1280", "Runs once; the fixtures are stateful.");
  });

  test("the ontology manager's Drafts list says how many drafts there are, and shows the rest", async ({ page }) => {
    // The panel showed the six most recently updated drafts and nothing else: no count, and
    // no way to reach a seventh. `audit_table_truncation` follows cuts into tables only, so
    // it never saw this one. Draft times are whole seconds, so two drafts made a second
    // before the other six are the two a correct list hides, and then shows on request.
    const suffix = `${Date.now()}`;
    const assetId = `drafts_asset_${suffix}`;
    const asset = await page.request.post("/data-assets", { data: {
      id: assetId, display_name: `Drafts asset ${suffix}`, kind: "dataset", asset_schema: {},
      records: [{ asset_id: "D-1", name: "First" }, { asset_id: "D-2", name: "Second" }]
    } });
    expect(asset.ok(), await asset.text()).toBeTruthy();
    const createDraft = async (label: string) => {
      const id = `drafts_${label}_${suffix}`;
      const response = await page.request.post("/ontology-generator/drafts", { data: {
        id, asset_id: assetId, object_type_id: `${id}_type`
      } });
      expect(response.ok(), await response.text()).toBeTruthy();
      return id;
    };
    const older = [await createDraft("older_1"), await createDraft("older_2")];
    await page.waitForTimeout(1100);
    const newer: string[] = [];
    for (let index = 1; index <= 6; index += 1) newer.push(await createDraft(`newer_${index}`));
    const held = (await (await page.request.get("/ontology-generator/drafts")).json() as Array<{ id: string }>).length;
    expect(held, "the fixture did not reach past the six the panel shows").toBeGreaterThanOrEqual(8);

    await page.goto("/workspace/ontology");
    const panel = page.locator(".manager-resource-nav .panel").filter({ has: page.getByRole("heading", { name: "Drafts", exact: true }) });
    const rows = panel.locator(".resource-row");
    await expect(rows).toHaveCount(6);
    for (const id of newer) {
      await expect(rows.filter({ hasText: id }), `${id} is newer than two others and is not among the six shown`).toHaveCount(1);
    }
    // No locale is pinned, so the count is formatted the way this browser formats it.
    const count = await page.evaluate((total) => total.toLocaleString(), held);
    const note = panel.getByRole("note");
    await expect(note, "the panel shows six drafts of more and does not say so")
      .toHaveText(`Showing the 6 most recently updated of ${count} drafts`);
    await expectUnclipped(note, "the note is cut off in the Resources pane, hiding how many drafts there are");

    await panel.getByRole("button", { name: `Show all ${count} drafts` }).click();
    await expect(rows, "the drafts past the sixth cannot be reached").toHaveCount(held);
    for (const id of older) await expect(rows.filter({ hasText: id })).toHaveCount(1);
    await expect(note, "the note still says six are shown when every draft is").toHaveCount(0);

    await panel.getByRole("button", { name: "Show only the 6 most recent" }).click();
    await expect(rows).toHaveCount(6);
  });

  test("Object Explorer facets draw every bin, and a value list says how many values it holds", async ({ page }) => {
    test.setTimeout(120_000);
    // A facet card drew its first seven buckets whatever the facet: a histogram has eight,
    // and the eighth holds the maximum, so the top of every distribution was missing; a
    // value list kept 7 of the server's 20 of however many there were, with nothing said.
    // Here 23 objects: 23 names, 10 sites, and scores 0 to 110 in eight bins.
    const suffix = `${Date.now()}`;
    const typeId = `facets_${suffix}`;
    const settled = async (response: APIResponse, label: string) => {
      const text = await response.text();
      expect(response.ok(), `${label}: ${text.slice(0, 500)}`).toBeTruthy();
      return JSON.parse(text || "null");
    };
    await settled(await page.request.post("/object-types", { data: {
      id: typeId, display_name: `Facets ${suffix}`, description: "Explorer facet cuts",
      properties: { name: { type: "string" }, score: { type: "number" }, site: { type: "string" } }
    } }), "object type");
    const records = Array.from({ length: 23 }, (unused, index) => ({
      id: `${typeId}_${String(index + 1).padStart(2, "0")}`, name: `n${String(index + 1).padStart(2, "0")}`,
      score: index * 5, site: `site_${index % 10}`
    }));
    await settled(await page.request.post("/data-assets", { data: {
      id: `${typeId}_feed`, display_name: `Facets feed ${suffix}`, kind: "dataset", asset_schema: {}, records
    } }), "feed");
    await settled(await page.request.post("/pipelines", { data: {
      id: `${typeId}_hydrate`, display_name: `Facets hydrate ${suffix}`, input_asset_id: `${typeId}_feed`,
      steps: [{ operation: "map_to_ontology", object_type_id: typeId, object_id_field: "id",
                property_map: { name: "$name", score: "$score", site: "$site" }, omit_nulls: true }]
    } }), "pipeline");
    const run = await settled(await page.request.post(`/pipelines/${typeId}_hydrate/run?actor=test`), "hydrate");
    expect(run.status, JSON.stringify(run).slice(0, 500)).toBe("SUCCESS");

    await page.goto(`/workspace/object-explorer?type=${typeId}`);
    const card = (field: string) => page.locator(".facet-card-react").filter({ has: page.locator("header strong").getByText(field, { exact: true }) });
    const buckets = (field: string) => card(field).locator(":scope > button");

    await expect(buckets("score"), "a histogram's eighth bin, the one holding the maximum, is not drawn").toHaveCount(8);
    await expect(buckets("score").last()).toContainText("110");
    await expect(card("score").getByRole("note"), "a histogram draws every bin and has nothing to say").toHaveCount(0);

    const names = card("name");
    await expect(buckets("name")).toHaveCount(7);
    await expect(names.getByRole("note"), "the name facet shows 7 of 23 values and does not say so")
      .toHaveText("Showing the 7 most common of 23 values");
    await expectUnclipped(names.getByRole("note"), "the facet note is cut off, hiding how many values there are");
    await names.getByRole("button", { name: "Show the 20 most common" }).click();
    await expect(buckets("name"), "the values past the seventh cannot be reached").toHaveCount(20);
    await expect(names.getByRole("button", { name: "Show only the 7 most common" })).toHaveAttribute("aria-expanded", "true");
    await expect(names.getByRole("note"), "the server kept 20 of 23 and the card does not say so")
      .toHaveText("Showing the 20 most common of 23 values");
    await names.getByRole("button", { name: "Show only the 7 most common" }).click();
    await expect(buckets("name")).toHaveCount(7);

    const sites = card("site");
    await expect(sites.getByRole("note")).toHaveText("Showing the 7 most common of 10 values");
    await sites.getByRole("button", { name: "Show all 10 values" }).click();
    await expect(buckets("site")).toHaveCount(10);
    await expect(sites.getByRole("note"), "the note still says seven are shown when every value is").toHaveCount(0);
  });

  test("the Risk Board scores the whole type, counts every scored object, and says how much it lists", async ({ page }) => {
    test.setTimeout(120_000);
    // The workspace asked for 250 objects and the server scored the first 250 by id. The
    // metrics counted them as the type, and a critical object at id 251 moved no number
    // and never reached the board. Here 300 objects: index 2, and 251 to 300, are critical.
    const typeId = await riskScoredType(page, 300, new Set([2, ...Array.from({ length: 50 }, (unused, offset) => 251 + offset)]));

    await page.goto("/workspace/decision");
    await page.getByLabel("Decision object type").selectOption(typeId);
    await expect(page.getByRole("status")).toHaveText("Ontology context loaded");
    await page.getByRole("button", { name: "Evaluate risk" }).click();
    await expect(page.getByRole("status")).toHaveText("Risk evaluation completed", { timeout: 30_000 });

    const metric = (label: string) => page.locator(".decision-metrics .metric-card")
      .filter({ has: page.locator("span", { hasText: new RegExp(`^${label}$`) }) }).locator("strong");
    await expect(metric("Objects evaluated"), "the metrics count only the objects the board was sent").toHaveText("300");
    await expect(metric("High-risk findings"), "a critical object past the first 250 by id is not counted").toHaveText("51");
    await expect(metric("Average risk"), "the average is taken over the findings kept, not every scored object").toHaveText("15");

    const board = page.locator(".panel").filter({ has: page.getByRole("heading", { name: "Risk Board", exact: true }) });
    const cards = board.locator(".decision-risk-grid > button");
    await expect(cards).toHaveCount(250);
    for (const index of [251, 275, 300]) {
      await expect(cards.filter({ hasText: `${typeId}_${String(index).padStart(4, "0")}` }), `critical object ${index} is not on the board`).toHaveCount(1);
    }
    await expect(page.getByLabel("Decision object ID"), "the riskiest object is not the one selected").toHaveValue(`${typeId}_0002`);

    // No locale is pinned, so the counts are formatted the way this browser formats them.
    const [listed, scored, others] = await page.evaluate(() => [(250).toLocaleString(), (300).toLocaleString(), (50).toLocaleString()]);
    const note = board.getByRole("note");
    await expect(note, "the board lists 250 of 300 scored objects and does not say so")
      .toHaveText(`Showing the ${listed} highest-risk of ${scored} evaluated objects; none of the other ${others} scores above 0.`);
    await expectUnclipped(note, "the board's note is cut off, hiding how many objects were scored");
    await expect(page.getByRole("note").filter({ hasText: "Scored the first" }), "the ceiling note shows though the whole type was scored").toHaveCount(0);
  });

  test("the Risk Board says so when the server's ceiling cut the scope it scored", async ({ page }) => {
    // A scope past the server's ceiling takes more objects than a test should make, so the
    // type is small and real and the evaluate reply is the real one with only its total
    // enlarged, the way the Outputs pane test enlarges only counts.
    const typeId = await riskScoredType(page, 5, new Set([3]));
    await page.route((url) => url.pathname === "/decision/evaluate", async (route) => {
      const response = await route.fetch();
      const body = await response.json();
      await route.fulfill({ response, json: { ...body, objects_in_scope: 12345 } });
    });

    await page.goto("/workspace/decision");
    await page.getByLabel("Decision object type").selectOption(typeId);
    await expect(page.getByRole("status")).toHaveText("Ontology context loaded");
    await page.getByRole("button", { name: "Evaluate risk" }).click();
    await expect(page.getByRole("status")).toHaveText("Risk evaluation completed", { timeout: 30_000 });

    const [scored, inScope] = await page.evaluate(() => [(5).toLocaleString(), (12345).toLocaleString()]);
    const note = page.getByRole("note").filter({ hasText: "Scored the first" });
    await expect(note, "the scope was cut at the ceiling and nothing says so")
      .toHaveText(`Scored the first ${scored} of ${inScope} active objects, by id. Every figure and the board below cover only those ${scored}.`);
    await expectUnclipped(note, "the ceiling note is cut off, hiding how many objects the scope holds");
  });

  test("the Candidate Review Queue says how much of the type it compared, and Explain does not call an uncompared object clear", async ({ page }) => {
    test.setTimeout(240_000);
    // A job compares every pair among the objects it reads. It read at most 1,000, in no
    // stated order, while the queue read as the whole duplicate list and Explain called any
    // object with no pending candidate "clear". Here 1,100 objects: a duplicate pair at 1
    // and 2, inside the scan, and another at 1,099 and 1,100, past it. The rest carry no
    // name or serial number, so their pairs score nothing and write no candidate.
    const pairs: Record<number, Record<string, string>> = {
      1: { name: "Kestrel Valve", serial_number: "KV-1" }, 2: { name: "Kestrel Valve", serial_number: "KV-1" },
      1099: { name: "Osprey Pump", serial_number: "OP-9" }, 1100: { name: "Osprey Pump", serial_number: "OP-9" }
    };
    const typeId = await entityType(page, (id) => Array.from({ length: 1100 }, (unused, offset) => {
      const index = offset + 1;
      return { id: `${id}_${String(index).padStart(4, "0")}`, status: "RUNNING", ...(pairs[index] ?? {}) };
    }));

    await page.goto("/workspace/decision");
    await page.getByLabel("Decision object type").selectOption(typeId);
    await expect(page.getByRole("status")).toHaveText("Ontology context loaded");
    const views = page.getByRole("navigation", { name: "Decision intelligence views" });
    await views.getByRole("button", { name: "Entity Resolution" }).click();
    await page.getByRole("button", { name: "Find duplicates" }).click();
    await expect(page.getByRole("status")).toHaveText("Entity review queue generated", { timeout: 180_000 });

    const queue = page.locator(".panel").filter({ has: page.getByRole("heading", { name: "Candidate Review Queue", exact: true }) });
    await expect(queue.locator("article strong").filter({ hasText: `${typeId}_0001 + ${typeId}_0002` }), "the pair inside the scan was not found").toHaveCount(1);
    const [scanned, inScope, rest] = await page.evaluate(() => [(1000).toLocaleString(), (1100).toLocaleString(), (100).toLocaleString()]);
    const note = queue.getByRole("note");
    await expect(note, "the queue compared 1,000 of 1,100 objects and does not say so")
      .toHaveText(`Compared the first ${scanned} of ${inScope} objects, by id. Pairs involving the other ${rest} were not compared.`);
    await expectUnclipped(note, "the queue's note is cut off, hiding how many objects were compared");

    await page.getByLabel("Decision object ID").fill(`${typeId}_1099`);
    await views.getByRole("button", { name: "Explain Object" }).click();
    await page.getByRole("button", { name: "Explain selected object" }).click();
    await expect(page.getByRole("status")).toHaveText("Explanation loaded");
    const badge = page.locator("h3", { hasText: "Duplicate warnings" }).locator("xpath=following-sibling::*[1]");
    await expect(badge, "an object the job never read is called clear").toHaveText("not compared");
  });

  test("an empty Candidate Review Queue says which objects it compared", async ({ page }) => {
    test.setTimeout(180_000);
    // "No candidates" claimed the whole type. With 1,002 objects and nothing to match, the
    // job compares the first 1,000 and the queue says that is where it found none.
    const typeId = await entityType(page, (id) => Array.from({ length: 1002 }, (unused, offset) => ({
      id: `${id}_${String(offset + 1).padStart(4, "0")}`, status: "RUNNING"
    })));

    await page.goto("/workspace/decision");
    await page.getByLabel("Decision object type").selectOption(typeId);
    await expect(page.getByRole("status")).toHaveText("Ontology context loaded");
    await page.getByRole("navigation", { name: "Decision intelligence views" }).getByRole("button", { name: "Entity Resolution" }).click();
    await page.getByRole("button", { name: "Find duplicates" }).click();
    await expect(page.getByRole("status")).toHaveText("Entity review queue generated", { timeout: 120_000 });

    const queue = page.locator(".panel").filter({ has: page.getByRole("heading", { name: "Candidate Review Queue", exact: true }) });
    const [scanned] = await page.evaluate(() => [(1000).toLocaleString()]);
    await expect(queue.getByText(`No candidates among the first ${scanned} objects`), "the empty queue claims the whole type").toBeVisible();
  });
});
