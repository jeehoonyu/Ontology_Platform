import { createServer } from "node:http";
import { execFileSync } from "node:child_process";
import { resolve } from "node:path";
import { expect, test, type APIResponse, type Locator, type Page } from "@playwright/test";
import { incidentIsOpen } from "../src/api/opsApi";

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

    // The pager wraps: on one line, `Next rows` ran past the narrow pane and could not be pressed.
    for (const name of ["Previous rows", "Next rows"]) {
      await expectUnclipped(lineage.getByRole("button", { name }), `at the pane's narrow width "${name}" runs past the pane`);
    }
    // A contract's names may still be cut behind an ellipsis; each carries its full text.
    const names = page.locator(".ontology-contract-row").first().locator("span").first();
    await expect(names.locator("strong"), "a contract's cut object type does not carry its full name").toHaveAttribute("title", "enlarged_counts");
    await expect(names.locator("small"), "a contract's cut node id does not carry its full text").toHaveAttribute("title", "ontology");
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

  test("Vertex's seed list says how many objects the type holds and reaches every one", async ({ page }) => {
    test.setTimeout(120_000);
    // The panel asked for 50 objects with no total and drew 24 of them as buttons. Past the
    // 24th, no object of a type could be picked from here, and nothing said the type held
    // more. Here 60 objects: three pages of 24, 24 and 12.
    const suffix = `${Date.now()}`;
    const typeId = `vertex_seeds_${suffix}`;
    const settled = async (response: APIResponse, label: string) => {
      const text = await response.text();
      expect(response.ok(), `${label}: ${text.slice(0, 500)}`).toBeTruthy();
      return JSON.parse(text || "null");
    };
    await settled(await page.request.post("/object-types", { data: {
      id: typeId, display_name: `Vertex seeds ${suffix}`, description: "Vertex seed cut", properties: { name: { type: "string" } }
    } }), "object type");
    const records = Array.from({ length: 60 }, (unused, index) => ({ id: `${typeId}_${String(index + 1).padStart(2, "0")}`, name: `Seed ${index + 1}` }));
    await settled(await page.request.post("/data-assets", { data: {
      id: `${typeId}_feed`, display_name: `Vertex seeds feed ${suffix}`, kind: "dataset", asset_schema: {}, records
    } }), "feed");
    await settled(await page.request.post("/pipelines", { data: {
      id: `${typeId}_hydrate`, display_name: `Vertex seeds hydrate ${suffix}`, input_asset_id: `${typeId}_feed`,
      steps: [{ operation: "map_to_ontology", object_type_id: typeId, object_id_field: "id", property_map: { name: "$name" }, omit_nulls: true }]
    } }), "pipeline");
    const run = await settled(await page.request.post(`/pipelines/${typeId}_hydrate/run?actor=test`), "hydrate");
    expect(run.status, JSON.stringify(run).slice(0, 500)).toBe("SUCCESS");

    await page.goto("/workspace/vertex");
    await page.getByLabel("Seed from object type").selectOption(typeId);
    const seeds = page.getByRole("button", { name: new RegExp(`^\\+ ${typeId}_`) });
    const note = page.getByRole("note").filter({ hasText: "objects" });
    const next = page.getByRole("button", { name: "Next objects" });
    const seen = new Set<string>();
    const collect = async () => { for (const label of await seeds.allTextContents()) seen.add(label.replace(/^\+\s*/, "").trim()); };

    await expect(seeds, "the panel no longer draws a full page of 24").toHaveCount(24);
    await expect(note, "the type holds 60 objects and the panel does not say so").toHaveText("Showing 1–24 of 60 objects");
    await expectUnclipped(note, "the seed note is cut off, hiding how many objects the type holds");
    await expect(page.getByRole("button", { name: "Previous objects" })).toBeDisabled();
    await collect();
    // The note must change with the objects, not ahead of them: while a page loads, the
    // buttons are still the last page's, so a note counted from the page asked for would
    // name objects that are not the ones listed.
    let firstOnPage = await seeds.first().textContent();
    // Hold the next page back, so the screen can be read while it loads.
    let release: () => void = () => undefined;
    const held = new Promise<void>((resolve) => { release = resolve; });
    await page.route("**/object-sets/search", async (route) => { await held; await route.continue(); }, { times: 1 });
    await next.click();
    await expect(next, "Next objects stays enabled while its page loads").toBeDisabled();
    await expect(note, "the note names the next page while the last page is still listed").toHaveText("Showing 1–24 of 60 objects");
    release();
    await expect(seeds.first(), "the next page's objects never arrived").not.toHaveText(firstOnPage || "");
    await expect(note).toHaveText("Showing 25–48 of 60 objects");
    await expect(seeds).toHaveCount(24);
    await collect();
    firstOnPage = await seeds.first().textContent();
    await next.click();
    await expect(seeds.first(), "the last page's objects never arrived").not.toHaveText(firstOnPage || "");
    await expect(note).toHaveText("Showing 49–60 of 60 objects");
    await expect(seeds).toHaveCount(12);
    await expect(next, "the last page still offers more").toBeDisabled();
    await collect();
    expect(seen.size, "paging did not reach every object exactly once").toBe(60);
  });

  test("the Reliability tab says what its counts cover and lists every run it loaded", async ({ page }) => {
    test.setTimeout(120_000);
    // The posture's status counts came from the latest 25 contract runs, and the table listed
    // 8 of them, with nothing said about either. Here one contract runs 26 times, so the
    // database holds more runs than the 25 the summary reads, whatever ran before.
    const suffix = `${Date.now()}`;
    const assetId = `reliability_runs_${suffix}`;
    const settled = async (response: APIResponse, label: string) => {
      const text = await response.text();
      expect(response.ok(), `${label}: ${text.slice(0, 500)}`).toBeTruthy();
      return JSON.parse(text || "null");
    };
    await settled(await page.request.post("/data-assets", { data: {
      id: assetId, display_name: `Reliability runs ${suffix}`, kind: "dataset", asset_schema: {},
      records: [{ id: 1 }, { id: 2 }, { id: 3 }]
    } }), "asset");
    const contract = await settled(await page.request.post("/reliability/data-contracts", { data: {
      display_name: `Reliability runs ${suffix}`, asset_id: assetId, checks: []
    } }), "contract") as { id: string };
    for (let run = 0; run < 26; run += 1) {
      await settled(await page.request.post(`/reliability/data-contracts/${contract.id}/run`, { data: {} }), `run ${run}`);
    }
    const summary = await settled(await page.request.get("/reliability/summary"), "summary");
    expect(typeof summary.contract_runs, "the summary does not report how many contract runs exist").toBe("number");
    const held = summary.contract_runs as number;
    expect(held, "the fixture did not reach past the 25 runs the summary reads").toBeGreaterThan(25);
    const heldText = await page.evaluate((total) => total.toLocaleString(), held);

    await page.goto("/workspace/ops");
    await page.getByRole("navigation", { name: "Operational control views" }).getByRole("button", { name: "Reliability", exact: true }).click();
    const table = page.locator(".panel").filter({ has: page.getByRole("heading", { name: "Latest Data Contract Runs", exact: true }) });
    await expect(table.locator("tbody tr"), "the table lists fewer runs than the counts came from").toHaveCount(25);
    await expect(table.getByRole("note"), "the table lists 25 of more runs and does not say so")
      .toHaveText(`Loaded the latest 25 of ${heldText} contract runs`);
    await expectUnclipped(table.getByRole("note"), "the runs note is cut off, hiding how many runs exist");
    const posture = page.locator(".panel").filter({ has: page.getByRole("heading", { name: "Reliability Posture", exact: true }) });
    await expect(posture.getByRole("note"), "the status counts cover 25 runs and read as all of them")
      .toHaveText(`Status counts cover the latest 25 of ${heldText} contract runs`);
    await expectUnclipped(posture.getByRole("note"), "the posture note is cut off, hiding how many runs exist");
  });

  test("Fetch Evidence says when the source holds more attempts than it loaded", async ({ page }) => {
    test.setTimeout(180_000);
    // The panel listed the 50 attempts the server returns and read as every attempt. Here one
    // preview through the screen, 51 more through the API, and one more through the screen:
    // 53 attempts, of which the server returns the latest 50.
    const server = createServer((request, response) => {
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({ records: [{ asset_id: "evidence-1", name: "Evidence Pump" }, { asset_id: "evidence-2", name: "Evidence Valve" }] }));
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    try {
      const address = server.address();
      if (!address || typeof address === "string") throw new Error("Could not determine connector test server port");
      const sourceId = `fetch_evidence_${Date.now()}`;
      await page.goto("/workspace/imports");
      await page.getByLabel("Source ID").fill(sourceId);
      await page.getByLabel("Base URL").fill(`http://127.0.0.1:${address.port}`);
      await page.getByRole("button", { name: "Save and Preview" }).click();
      await expect(page.getByText("Evidence Pump", { exact: true })).toBeVisible();
      for (let start = 0; start < 51; start += 10) {
        const batch = Array.from({ length: Math.min(10, 51 - start) }, () => page.request.post(`/connections/sources/${sourceId}/live-preview`, { data: { limit: 25 } }));
        for (const response of await Promise.all(batch)) expect(response.ok(), await response.text()).toBeTruthy();
      }
      await page.getByRole("button", { name: "Save and Preview" }).click();
      const panel = page.locator(".panel").filter({ has: page.getByRole("heading", { name: "Fetch Evidence", exact: true }) });
      const note = panel.getByRole("note");
      await expect(note, "the panel loaded 50 of 53 attempts and does not say so").toHaveText("Loaded the latest 50 of 53 fetch attempts");
      await expectUnclipped(note, "the fetch evidence note is cut off, hiding how many attempts there are");
      await expect(panel.locator("caption")).toContainText("of 50 rows");
    } finally {
      await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
    }
  });

  test("Data Onboarding counts every import job and says the recent list is a window", async ({ page }) => {
    test.setTimeout(120_000);
    // "Import jobs" counted the 50 jobs the summary loaded, and Recent Import Jobs listed the 50
    // newest, with nothing said. Here 51 more jobs, so the server holds more than 50 whatever
    // ran before.
    const suffix = `${Date.now()}`;
    for (let start = 0; start < 51; start += 10) {
      const batch = Array.from({ length: Math.min(10, 51 - start) }, (unused, offset) => page.request.post("/imports/csv", { data: {
        id: `import_window_${suffix}_${start + offset}`, filename: "window.csv", display_name: `Import window ${start + offset}`,
        target_dataset_id: `import_window_${suffix}_${start + offset}_dataset`, content: "asset_id,name\nwindow_1,Window Pump\n"
      } }));
      for (const response of await Promise.all(batch)) expect(response.ok(), await response.text()).toBeTruthy();
    }
    const listed = await (await page.request.get("/imports/jobs?limit=1")).json() as { total?: number };
    expect(typeof listed.total, "the import job list does not say how many jobs there are").toBe("number");
    const total = listed.total as number;
    expect(total, "the fixture did not reach past the 50 jobs the screen loads").toBeGreaterThan(50);

    await page.goto("/workspace/imports");
    const metric = page.locator(".metric-card").filter({ has: page.getByText("Import jobs", { exact: true }) });
    await expect(metric.locator("strong"), "the Import jobs metric counts only the jobs loaded").toHaveText(String(total));
    const panel = page.locator(".panel").filter({ has: page.getByRole("heading", { name: "Recent Import Jobs", exact: true }) });
    const totalText = await page.evaluate((count) => count.toLocaleString(), total);
    await expect(panel.getByRole("note"), "the recent list shows 50 of more jobs and does not say so")
      .toHaveText(`Loaded the latest 50 of ${totalText} import jobs`);
    await expectUnclipped(panel.getByRole("note"), "the import jobs note is cut off, hiding how many jobs there are");
  });

  test("an extension's run list says how many runs it has", async ({ page }) => {
    test.setTimeout(180_000);
    // The execution evidence panel listed the 50 runs the server returns and read as every run.
    // A real signed extension is registered and queued three times; its real run list is then
    // enlarged in its count only, since past fifty real sandboxed runs this is a load test.
    const suffix = `${Date.now()}`;
    const raw = execFileSync(process.env.PYTHON_BIN || "python", [resolve("../oms/build_rehearsal_plugin.py"), "--suffix", suffix], { cwd: resolve("."), encoding: "utf8" });
    const fixture = JSON.parse(raw) as { trust_key: Record<string, unknown>; register: Record<string, unknown> & { manifest: { plugin_id: string } } };
    const settled = async (response: APIResponse, label: string) => {
      const text = await response.text();
      expect(response.ok(), `${label}: ${text.slice(0, 500)}`).toBeTruthy();
      return JSON.parse(text || "null");
    };
    // The rehearsal builder signs for its own organization; the suite's projects belong to "local".
    await settled(await page.request.post("/api/v1/plugins/trust-keys", { data: { ...fixture.trust_key, organization_id: "local" } }), "trust key");
    const version = await settled(await page.request.post("/api/v1/plugins/register", { data: fixture.register }), "register") as { id: string };
    await settled(await page.request.post(`/api/v1/plugins/${version.id}/activate`), "activate");
    for (let run = 0; run < 3; run += 1) {
      await settled(await page.request.post(`/api/v1/plugins/${version.id}/invoke-async`, { data: {
        operation: "fast", input: { marker: `run-${run}` }, idempotency_key: `${suffix}-${run}`
      } }), `queue run ${run}`);
    }
    const EXTRA = 75;
    let listed = -1;
    await page.route(`**/api/v1/plugins/${version.id}/executions*`, async (route) => {
      const response = await route.fetch();
      const body = await response.json() as { executions: unknown[]; total?: number };
      listed = body.executions.length;
      await route.fulfill({ response, json: typeof body.total === "number" ? { ...body, total: body.total + EXTRA } : body });
    });

    await page.goto("/workspace/control-panel");
    await page.getByRole("button", { name: "Extensions", exact: true }).click();
    const pluginId = fixture.register.manifest.plugin_id;
    await page.getByRole("button", { name: `Runs: ${pluginId}` }).click();
    await expect.poll(() => listed, { message: "the panel never asked for the extension's runs" }).toBeGreaterThanOrEqual(3);
    const panel = page.locator(".panel").filter({ has: page.getByRole("heading", { name: `${pluginId} execution evidence`, exact: true }) });
    await expect(panel.getByRole("note"), "the panel lists the latest runs of more and does not say so")
      .toHaveText(`Loaded the latest ${listed} of ${listed + EXTRA} runs`);
    await expectUnclipped(panel.getByRole("note"), "the runs note is cut off, hiding how many runs there are");
  });

  test("the pipeline drawer previews the rows it asks for and says how many the node holds", async ({ page }) => {
    test.setTimeout(120_000);
    // The drawer asked for 50 preview rows and the server cut every node's sample to 5, so it
    // drew 5 rows of any node, with nothing said. Here an input of 60 rows.
    const suffix = `${Date.now()}`;
    const assetId = `preview_window_${suffix}`;
    const graphName = `Preview window ${suffix}`;
    const asset = await page.request.post("/data-assets", { data: {
      id: assetId, display_name: graphName, kind: "dataset", asset_schema: {},
      records: Array.from({ length: 60 }, (unused, index) => ({ row: index, label: `row ${index}` }))
    } });
    expect(asset.ok(), await asset.text()).toBeTruthy();
    const graph = await page.request.post("/pipeline-builder/graphs", { data: {
      id: `preview_window_graph_${suffix}`, display_name: graphName,
      nodes: [{ id: "input", type: "input_dataset", label: "Window input", position: { x: 80, y: 120 }, config: { asset_id: assetId } }],
      edges: []
    } });
    expect(graph.ok(), await graph.text()).toBeTruthy();

    await page.goto("/workspace/pipeline");
    await page.locator(".output-rail .resource-row").filter({ hasText: graphName }).click();
    await page.getByRole("button", { name: /Window input \d+ rows input_dataset/ }).click();
    const drawer = page.locator(".bottom-drawer");
    // The clicks are the hit test. At this viewport the panes' row pushed the drawer below the
    // page's clip, and `section.builder-main` took every click meant for it.
    await drawer.getByRole("button", { name: "preview", exact: true }).click({ timeout: 15_000 });
    await expect(drawer.getByRole("note"), "the drawer previews some of the node's rows and does not say so")
      .toHaveText("Previewing the first 50 of 60 rows");
    await expectUnclipped(drawer.getByRole("note"), "the preview note is cut off, hiding how many rows the node holds");
    const caption = drawer.locator("caption");
    await expect(caption, "the drawer did not receive the 50 rows it asked for").toContainText("of 50 rows");
    await drawer.getByRole("button", { name: "Next rows" }).click({ timeout: 15_000 });
    await expect(caption).toContainText("41–50 of 50 rows");
  });

  test("the mapping preview says it hydrates only the first rows of a larger dataset", async ({ page }) => {
    // The drawer read "Hydrated object preview · 20 rows", the length of what the server kept,
    // for a dataset of any size. Here a dataset of 25 records.
    const suffix = `${Date.now()}`;
    const assetId = `mapping_window_${suffix}`;
    const typeResponse = await page.request.post("/object-types", { data: {
      id: `mapping_window_type_${suffix}`, display_name: `Mapping window ${suffix}`, description: "Mapping preview window", properties: { name: { type: "string" } }
    } });
    expect(typeResponse.ok(), await typeResponse.text()).toBeTruthy();
    const asset = await page.request.post("/data-assets", { data: {
      id: assetId, display_name: `Mapping window ${suffix}`, kind: "dataset", asset_schema: {},
      records: Array.from({ length: 25 }, (unused, index) => ({ id: `m${index}`, name: `Mapped ${index}` }))
    } });
    expect(asset.ok(), await asset.text()).toBeTruthy();

    await page.goto("/workspace/ontology");
    const mappingPanel = page.locator(".ontology-mapping-panel");
    await mappingPanel.getByLabel("Source dataset").selectOption(assetId);
    await mappingPanel.getByRole("button", { name: "Preview objects" }).click();
    await expect(mappingPanel.locator(".mapping-preview-drawer summary"), "the preview reads its kept rows as the dataset")
      .toHaveText("Hydrated object preview · the first 20 of 25 rows");
  });

  test("a full live connector preview says it stopped at its limit", async ({ page }) => {
    // The live preview asks for 25 records and drew them with nothing said, though no adapter
    // reports how many a source holds. Here a source of 30 records.
    const server = createServer((request, response) => {
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({ records: Array.from({ length: 30 }, (unused, index) => ({ asset_id: `live-window-${index}`, name: `Live Window ${index}` })) }));
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    try {
      const address = server.address();
      if (!address || typeof address === "string") throw new Error("Could not determine connector test server port");
      await page.goto("/workspace/imports");
      await page.getByLabel("Source ID").fill(`live_window_${Date.now()}`);
      await page.getByLabel("Base URL").fill(`http://127.0.0.1:${address.port}`);
      await page.getByRole("button", { name: "Save and Preview" }).click();
      await expect(page.getByText("Live Window 0", { exact: true })).toBeVisible();
      const note = page.getByRole("note").filter({ hasText: "The preview stops at" });
      await expect(note, "a preview that filled its limit does not say so").toHaveText("Showing the first 25 records. The preview stops at 25, and this source does not say how many it holds.");
      await expectUnclipped(note, "the live preview note is cut off");
    } finally {
      await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
    }
  });

  test("an Object Explorer facet filters to the objects it counts", async ({ page }) => {
    test.setTimeout(120_000);
    // A histogram bucket sent its label as the filter, which no number equals, and a True
    // bucket sent the text "True", which no stored true equals: every such click read "No
    // matching objects". Here 23 objects, scores 0 to 110 and every other one active.
    const suffix = `${Date.now()}`;
    const typeId = `facet_filter_${suffix}`;
    const settled = async (response: APIResponse, label: string) => {
      const text = await response.text();
      expect(response.ok(), `${label}: ${text.slice(0, 500)}`).toBeTruthy();
      return JSON.parse(text || "null");
    };
    await settled(await page.request.post("/object-types", { data: {
      id: typeId, display_name: `Facet filter ${suffix}`, description: "Facet filter",
      properties: { name: { type: "string" }, score: { type: "number" }, active: { type: "boolean" } }
    } }), "object type");
    const records = Array.from({ length: 23 }, (unused, index) => ({ id: `${typeId}_${String(index).padStart(2, "0")}`, name: `f${index}`, score: index * 5, active: index % 2 === 0 }));
    await settled(await page.request.post("/data-assets", { data: { id: `${typeId}_feed`, display_name: `Facet filter feed ${suffix}`, kind: "dataset", asset_schema: {}, records } }), "feed");
    await settled(await page.request.post("/pipelines", { data: {
      id: `${typeId}_hydrate`, display_name: `Facet filter hydrate ${suffix}`, input_asset_id: `${typeId}_feed`,
      steps: [{ operation: "map_to_ontology", object_type_id: typeId, object_id_field: "id", property_map: { name: "$name", score: "$score", active: "$active" }, omit_nulls: true }]
    } }), "pipeline");
    const run = await settled(await page.request.post(`/pipelines/${typeId}_hydrate/run?actor=test`), "hydrate");
    expect(run.status, JSON.stringify(run).slice(0, 500)).toBe("SUCCESS");

    await page.goto(`/workspace/object-explorer?type=${typeId}`);
    const card = (field: string) => page.locator(".facet-card-react").filter({ has: page.locator("header strong").getByText(field, { exact: true }) });
    const rows = page.locator(".explorer-table tbody tr");
    await expect(rows).toHaveCount(23);

    const topBin = card("score").locator(":scope > button").last();
    const topCount = Number(await topBin.locator("b").textContent());
    await topBin.click();
    await expect(rows, "the top bin's filter does not return the objects the bin counts").toHaveCount(topCount);
    await expect(page.getByText("No matching objects", { exact: true })).toHaveCount(0);
    const chip = page.locator(".filter-chip-list button");
    await expect(chip, "the filter chip does not say which range it holds").toHaveText(/^score: \d+(\.\d+)? – 110$/);
    await chip.click();
    await expect(rows).toHaveCount(23);

    const trueBucket = card("active").locator(":scope > button").filter({ has: page.getByText("True", { exact: true }) });
    const trueCount = Number(await trueBucket.locator("b").textContent());
    await trueBucket.click();
    await expect(rows, "the True bucket's filter does not return the objects it counts").toHaveCount(trueCount);
  });

  test("the map says how many features a type holds, lists them all on request, and counts a geofence past its limit", async ({ page }) => {
    test.setTimeout(300_000);
    // The map loaded 2,000 features and read them as the type: the strip said "2000 features",
    // the rail listed 12 with nothing said, and a geofence counted only among the 2,000 kept.
    // Here 2,001 objects at one point, so the geofence holds every one.
    const suffix = `${Date.now()}`;
    const typeId = `map_window_${suffix}`;
    const settled = async (response: APIResponse, label: string) => {
      const text = await response.text();
      expect(response.ok(), `${label}: ${text.slice(0, 500)}`).toBeTruthy();
      return JSON.parse(text || "null");
    };
    await settled(await page.request.post("/object-types", { data: {
      id: typeId, display_name: `Map window ${suffix}`, description: "Map window",
      properties: { name: { type: "string" }, latitude: { type: "number" }, longitude: { type: "number" } }
    } }), "object type");
    const records = Array.from({ length: 2001 }, (unused, index) => ({ id: `${typeId}_${String(index).padStart(4, "0")}`, name: `Mapped ${index}`, latitude: 37.8, longitude: -122.41 }));
    await settled(await page.request.post("/data-assets", { data: { id: `${typeId}_feed`, display_name: `Map window feed ${suffix}`, kind: "dataset", asset_schema: {}, records } }), "feed");
    await settled(await page.request.post("/pipelines", { data: {
      id: `${typeId}_hydrate`, display_name: `Map window hydrate ${suffix}`, input_asset_id: `${typeId}_feed`,
      steps: [{ operation: "map_to_ontology", object_type_id: typeId, object_id_field: "id", property_map: { name: "$name", latitude: "$latitude", longitude: "$longitude" }, omit_nulls: true }]
    } }), "pipeline");
    const run = await settled(await page.request.post(`/pipelines/${typeId}_hydrate/run?actor=test`), "hydrate");
    expect(run.status, JSON.stringify(run).slice(0, 500)).toBe("SUCCESS");
    const [loaded, held] = await page.evaluate(() => [(2000).toLocaleString(), (2001).toLocaleString()]);

    await page.goto("/workspace/map");
    await page.getByLabel("Map object type").selectOption(typeId);
    await page.getByRole("button", { name: "Render" }).click();
    await expect(page.locator(".map-status-strip strong"), "the strip reads the loaded window as the type").toHaveText(`${loaded} of ${held} features`);
    const rail = page.locator(".map-layer-rail");
    // Not "Loaded": a text filter ignores case, and the list's note says "loaded features".
    const windowNote = rail.getByRole("note").filter({ hasText: "show only these" });
    await expect(windowNote, "the rail does not say the map loaded some of the features").toHaveText(`Loaded ${loaded} of ${held} features. The map and this list show only these.`);
    await expectUnclipped(windowNote, "the map's window note is cut off, hiding how many features there are");
    const list = rail.locator(".map-feature-list button");
    await expect(list).toHaveCount(12);
    const listNote = rail.getByRole("note").filter({ hasText: "Listing" });
    await expect(listNote).toHaveText(`Listing 12 of ${loaded} loaded features`);
    await expectUnclipped(listNote, "the feature list note is cut off");
    const showAll = rail.getByRole("button", { name: `Show all ${loaded} loaded features` });
    await showAll.click();
    await expect(list, "the features past the twelfth cannot be reached from the list").toHaveCount(2000);
    await expect(rail.getByRole("button", { name: "Show only the first 12" })).toHaveAttribute("aria-expanded", "true");
    await expect(listNote).toHaveCount(0);
    await rail.getByRole("button", { name: "Show only the first 12" }).click();
    await expect(list).toHaveCount(12);

    await list.first().click();
    await page.getByRole("button", { name: "Evaluate geofence" }).click();
    await expect(page.locator(".geofence-summary"), "the geofence counted only the objects the map kept").toContainText(`${held} inside`);
    await expect(page.locator(".geofence-summary")).toContainText("0 outside");
  });

  test("a map that loaded its whole type says nothing about windows", async ({ page }) => {
    const suffix = `${Date.now()}`;
    const typeId = `map_whole_${suffix}`;
    const settled = async (response: APIResponse, label: string) => {
      const text = await response.text();
      expect(response.ok(), `${label}: ${text.slice(0, 500)}`).toBeTruthy();
      return JSON.parse(text || "null");
    };
    await settled(await page.request.post("/object-types", { data: {
      id: typeId, display_name: `Map whole ${suffix}`, description: "Map whole",
      properties: { name: { type: "string" }, latitude: { type: "number" }, longitude: { type: "number" } }
    } }), "object type");
    for (let index = 0; index < 3; index += 1) {
      await settled(await page.request.post("/objects", { data: { id: `${typeId}_${index}`, object_type_id: typeId, properties: { name: `Whole ${index}`, latitude: 37.8, longitude: -122.41 } } }), `object ${index}`);
    }
    await page.goto("/workspace/map");
    await page.getByLabel("Map object type").selectOption(typeId);
    await page.getByRole("button", { name: "Render" }).click();
    await expect(page.locator(".map-status-strip strong")).toHaveText("3 features");
    await expect(page.locator(".map-layer-rail").getByRole("note"), "a whole type is not a window").toHaveCount(0);
    await expect(page.locator(".map-layer-rail").getByRole("button", { name: /^Show all/ })).toHaveCount(0);
  });

  test("the platform graph says which kinds it loaded only part of", async ({ page }) => {
    test.setTimeout(240_000);
    // The graph asked for 500 of each kind and read what came back as the platform: the kind
    // chips counted loaded nodes, and nothing said a kind had more. Here 501 objects of a new
    // type, so the objects reach the limit whatever else the database holds.
    const suffix = `${Date.now()}`;
    const typeId = `graph_window_${suffix}`;
    const settled = async (response: APIResponse, label: string) => {
      const text = await response.text();
      expect(response.ok(), `${label}: ${text.slice(0, 500)}`).toBeTruthy();
      return JSON.parse(text || "null");
    };
    await settled(await page.request.post("/object-types", { data: { id: typeId, display_name: `Graph window ${suffix}`, description: "Graph window", properties: { name: { type: "string" } } } }), "object type");
    const records = Array.from({ length: 501 }, (unused, index) => ({ id: `${typeId}_${String(index).padStart(3, "0")}`, name: `Graph ${index}` }));
    await settled(await page.request.post("/data-assets", { data: { id: `${typeId}_feed`, display_name: `Graph window feed ${suffix}`, kind: "dataset", asset_schema: {}, records } }), "feed");
    await settled(await page.request.post("/pipelines", { data: {
      id: `${typeId}_hydrate`, display_name: `Graph window hydrate ${suffix}`, input_asset_id: `${typeId}_feed`,
      steps: [{ operation: "map_to_ontology", object_type_id: typeId, object_id_field: "id", property_map: { name: "$name" }, omit_nulls: true }]
    } }), "pipeline");
    const run = await settled(await page.request.post(`/pipelines/${typeId}_hydrate/run?actor=test`), "hydrate");
    expect(run.status, JSON.stringify(run).slice(0, 500)).toBe("SUCCESS");

    const overview = page.waitForResponse((response) => response.url().includes("/graph/overview"));
    await page.goto("/workspace/graph");
    const body = await (await overview).json() as { limit: number; totals: Record<string, number>; loaded: Record<string, number>; edges: unknown[]; edge_count: number };
    expect(body.loaded.object).toBe(500);
    expect(body.totals.object).toBeGreaterThanOrEqual(501);
    expect(body.edges.length, "the graph cut its edges").toBe(body.edge_count);
    const nouns: Record<string, string> = { object_type: "object types", object: "objects", object_link: "links", data_asset: "data assets", pipeline: "pipelines", incident: "incidents" };
    const expected = await page.evaluate(([totals, loaded, names]) => Object.entries(totals).filter(([kind, total]) => total > (loaded[kind] ?? total))
      .map(([kind, total]) => `${(loaded[kind] ?? 0).toLocaleString()} of ${total.toLocaleString()} ${names[kind] || kind}`).join(", "), [body.totals, body.loaded, nouns] as const);
    const note = page.getByRole("note").filter({ hasText: "cover only what was loaded" });
    await expect(note, "the graph loaded part of a kind and does not say so")
      .toHaveText(`Loaded ${expected}. The canvas, type counts, search and connections cover only what was loaded.`);
    await expectUnclipped(note, "the graph's note is cut off, hiding how many resources there are");
    const objectTotal = await page.evaluate((total) => total.toLocaleString(), body.totals.object);
    await expect(page.getByRole("group", { name: "Resource type filters" }).getByRole("button", { name: `object 500 of ${objectTotal}` }),
      "the object chip counts the loaded nodes as all of them").toBeVisible();

    await page.locator(".platform-graph-node").first().click();
    await page.getByRole("button", { name: "Neighbors" }).click();
    await expect(page.getByRole("button", { name: "Show all loaded nodes" }), "the toggle says Show all while the graph is partial").toBeVisible();
  });

  test("a platform graph that loaded every resource says nothing about windows", async ({ page }) => {
    // A resource of its own, so there are kind chips to read on a database no other test has filled:
    // run alone, this test found an empty graph and never reached its note.
    const suffix = `${Date.now()}`;
    const created = await page.request.post("/object-types", { data: { id: `graph_whole_${suffix}`, display_name: `Graph whole ${suffix}`, description: "Graph whole", properties: { name: { type: "string" } } } });
    expect(created.ok(), await created.text()).toBeTruthy();
    // The real reply, with each kind's total set to what was loaded.
    await page.route((url) => url.pathname === "/graph/overview", async (route) => {
      const response = await route.fetch();
      const body = await response.json() as { totals?: Record<string, number>; loaded?: Record<string, number> };
      await route.fulfill({ response, json: { ...body, totals: { ...(body.loaded || {}) } } });
    });
    await page.goto("/workspace/graph");
    await expect(page.locator(".platform-graph-kinds button").first()).toBeVisible();
    await expect(page.getByRole("note").filter({ hasText: "cover only what was loaded" }), "a whole graph is not a window").toHaveCount(0);
    await expect(page.locator(".platform-graph-kinds small").filter({ hasText: " of " })).toHaveCount(0);
  });

  test("the Command Center counts every open alert, approval and incident, and says its panel shows the newest approval", async ({ page }) => {
    test.setTimeout(120_000);
    // Open alerts, Open approvals and the section cards' incident counts were the lengths of the 20
    // newest rows the scenario loads, so none read past 20. Here 21 more open alerts, pending
    // approvals and open incidents, so every count passes 20 whatever ran before.
    const suffix = `${Date.now()}`;
    const source = `cc_counts_${suffix}`;
    const settled = async (response: APIResponse, label: string) => {
      const text = await response.text();
      expect(response.ok(), `${label}: ${text.slice(0, 500)}`).toBeTruthy();
      return JSON.parse(text || "null");
    };
    await settled(await page.request.post("/ops/alert-rules", { data: {
      id: `${source}_rule`, display_name: `Command Center counts ${suffix}`, source, min_severity: "high"
    } }), "alert rule");
    await settled(await page.request.post("/action-types", { data: {
      id: `${source}_escalate`, display_name: `Command Center counts ${suffix}`, parameters: {}, rules: { requires_approval: true }
    } }), "action type");
    for (let index = 0; index < 21; index += 1) {
      await settled(await page.request.post("/ops/events/ingest", { data: {
        source, event_type: "fixture.alert", severity: "high", title: `Counts alert ${index}`
      } }), `alert ${index}`);
      const staged = await settled(await page.request.post("/actions/execute", { data: {
        action_type_id: `${source}_escalate`, parameters: {}, idempotency_key: `${source}_${index}`
      } }), `approval ${index}`) as { status: string };
      expect(staged.status, `approval ${index} was not staged`).toBe("REQUIRES_APPROVAL");
      await settled(await page.request.post("/ops/incidents", { data: {
        display_name: `Counts incident ${suffix} ${index}`, severity: "medium"
      } }), `incident ${index}`);
    }
    // The routes that list every row, so the true counts are known whatever ran before.
    const openAlerts = (await settled(await page.request.get("/ops/alerts?status=OPEN"), "open alerts") as unknown[]).length;
    const openApprovals = (await settled(await page.request.get("/approvals?status=PENDING"), "pending approvals") as unknown[]).length;
    const incidents = await settled(await page.request.get("/ops/incidents"), "incidents") as Array<{ status: string }>;
    const openIncidents = incidents.filter((incident) => incidentIsOpen(incident.status)).length;
    for (const [label, count] of [["alerts", openAlerts], ["approvals", openApprovals], ["incidents", openIncidents]] as const) {
      expect(count, `the fixture did not reach past the 20 ${label} the scenario loads`).toBeGreaterThan(20);
    }

    // An earlier test may have run the industrial workflow on this project, and its latest approval
    // then takes the panel. This test reads the scenario's own panel, so that workflow reads as unset.
    await page.route((url) => url.pathname === "/api/v1/industrial/workflows/asset-reliability/workflow-state", (route) =>
      route.fulfill({ json: { project_id: "default", status: "NOT_CONFIGURED", steps: [], evidence_links: [], summary: { object_count: 0 } } }));
    const loaded = page.waitForResponse((response) => new URL(response.url()).pathname === "/ui-state/command-center");
    await page.goto("/workspace/command-center");
    const state = await (await loaded).json() as { workflow: { summary: Record<string, unknown[]> } };

    const metric = (label: string) => page.locator(".grid.metrics .metric-card")
      .filter({ has: page.locator("span", { hasText: new RegExp(`^${label}$`) }) }).locator("strong");
    await expect(metric("Open alerts"), "Open alerts counts only the 20 alerts the scenario loads").toHaveText(String(openAlerts));
    await expect(metric("Open approvals"), "Open approvals counts only the 20 approvals the scenario loads").toHaveText(String(openApprovals));
    const card = (title: string, key: string) => page.locator(".section-card").filter({ has: page.locator("strong", { hasText: title }) })
      .locator(".kv-grid > div").filter({ has: page.locator("dt", { hasText: new RegExp(`^${key}$`) }) }).locator("dd");
    await expect(card("Approval and action", "open approvals"), "the approval card counts only the 20 approvals loaded").toHaveText(String(openApprovals));
    await expect(card("Approval and action", "open incidents"), "the approval card counts open incidents among the 20 loaded").toHaveText(String(openIncidents));
    await expect(card("Incident and report", "incident count"), "the report card counts only the 20 incidents loaded").toHaveText(String(incidents.length));

    const panel = page.locator(".panel").filter({ has: page.getByRole("heading", { name: "Governed Approval and Action", exact: true }) });
    const approvalsText = await page.evaluate((count) => count.toLocaleString(), openApprovals);
    await expect(panel.getByRole("note"), "the panel shows one of many open approvals and does not say so")
      .toHaveText(`Showing the newest of ${approvalsText} open approvals`);
    await expectUnclipped(panel.getByRole("note"), "the approvals note is cut off, hiding how many approvals are open");
    for (const key of ["alerts", "approvals", "incidents"]) {
      expect(state.workflow.summary[key], `the scenario no longer loads the 20 newest ${key}`).toHaveLength(20);
    }
  });

  test("the Governed Approval panel says nothing about other approvals when only one is open", async ({ page }) => {
    // The scenario's own reply, with its approvals set to one and its count to one, so the panel shows
    // every open approval there is. The industrial workflow reads as unset, as in the test above.
    await page.route((url) => url.pathname === "/api/v1/industrial/workflows/asset-reliability/workflow-state", (route) =>
      route.fulfill({ json: { project_id: "default", status: "NOT_CONFIGURED", steps: [], evidence_links: [], summary: { object_count: 0 } } }));
    await page.route((url) => url.pathname === "/ui-state/command-center", async (route) => {
      const response = await route.fetch();
      const body = await response.json() as { workflow: { summary: { kpis?: Record<string, unknown>; approvals?: unknown[] } } };
      body.workflow.summary.approvals = [{ id: "cc_counts_only", action_type_id: "cc_counts_only", requester: "fixture", parameters: {}, status: "PENDING", created_at: 1 }];
      body.workflow.summary.kpis = { ...(body.workflow.summary.kpis || {}), open_approvals: 1 };
      await route.fulfill({ response, json: body });
    });
    await page.goto("/workspace/command-center");
    const panel = page.locator(".panel").filter({ has: page.getByRole("heading", { name: "Governed Approval and Action", exact: true }) });
    await expect(panel.getByText("cc_counts_only", { exact: true }), "the panel does not show the only open approval").toBeVisible();
    await expect(panel.getByRole("note"), "one open approval is said to be one of many").toHaveCount(0);
  });

  test("Latest incidents lists the most recently updated and says how many are open", async ({ page }) => {
    // The summary read its open incidents in no order, so its ten were whichever the database
    // returned first, and the panel listed them with nothing said. Twelve more open incidents keep
    // the count past ten whatever ran before. One written in the middle is then updated, so it is
    // the most recently updated: not the first written, which a read in no order returns first,
    // nor the last, which an order by creation puts first.
    const suffix = `${Date.now()}`;
    const settled = async (response: APIResponse, label: string) => {
      const text = await response.text();
      expect(response.ok(), `${label}: ${text.slice(0, 500)}`).toBeTruthy();
      return JSON.parse(text || "null");
    };
    const created: Array<{ id: string }> = [];
    for (let index = 0; index < 12; index += 1) {
      created.push(await settled(await page.request.post("/ops/incidents", { data: {
        display_name: `Latest incident ${suffix} ${index}`, severity: "medium"
      } }), `incident ${index}`));
    }
    // `updated_at` is held in seconds, so the update waits for the next one.
    await page.waitForTimeout(1_100);
    await settled(await page.request.patch(`/ops/incidents/${encodeURIComponent(created[5].id)}`, { data: { owner: `latest-${suffix}` } }), "update one in the middle");

    const loaded = page.waitForResponse((response) => new URL(response.url()).pathname === "/ops/summary");
    await page.goto("/workspace/ops");
    const summary = await (await loaded).json() as { open_incidents: number; latest_incidents: unknown[] };
    expect(summary.open_incidents, "the fixture did not reach past the ten the panel lists").toBeGreaterThan(10);
    const panel = page.locator(".panel").filter({ has: page.getByRole("heading", { name: "Current Severity", exact: true }) });
    const listed = panel.locator(".ops-compact-list article");
    await expect(listed).toHaveCount(10);
    await expect(listed.first(), "Latest incidents does not start with the most recently updated").toContainText(`Latest incident ${suffix} 5`);
    const openText = await page.evaluate((count) => count.toLocaleString(), summary.open_incidents);
    await expect(panel.getByRole("note"), "Latest incidents lists ten of many open incidents and does not say so")
      .toHaveText(`Showing the 10 most recently updated of ${openText} open incidents. The Incidents tab lists every one.`);
    await expectUnclipped(panel.getByRole("note"), "the note is cut off, hiding how many incidents are open");
  });

  test("Latest incidents says nothing more when it lists every open incident", async ({ page }) => {
    const incident = (index: number) => ({
      id: `stub_latest_${index}`, display_name: `Stub latest ${index}`, severity: "medium", status: "OPEN", owner: null,
      linked_objects: [], alert_ids: [], approval_ids: [], runbook_execution_ids: [], timeline: [], created_at: 1, updated_at: 1
    });
    await page.route((url) => url.pathname === "/ops/summary", async (route) => {
      const response = await route.fetch();
      const body = await response.json() as Record<string, unknown>;
      await route.fulfill({ response, json: { ...body, open_incidents: 2, latest_incidents: [incident(0), incident(1)] } });
    });
    await page.goto("/workspace/ops");
    const panel = page.locator(".panel").filter({ has: page.getByRole("heading", { name: "Current Severity", exact: true }) });
    await expect(panel.locator(".ops-compact-list article")).toHaveCount(2);
    await expect(panel.getByRole("note"), "a list of every open incident is said to be part of more").toHaveCount(0);
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

  test("the Candidate Review Queue compares the first 1,000 in full, pairs every object on an exact value, and says so", async ({ page }) => {
    test.setTimeout(240_000);
    // A job compares every pair among the first 1,000 objects by id, and pairs every object of the
    // type that shares an exact name or serial number, ignoring case and punctuation. Here 1,100
    // objects: a pair at 1 and 2 inside the scan; an exact pair at 1,099 and 1,100 past it, which
    // only the exact pass reaches; a near pair at 1,097 and 1,098 past it, which nothing compares;
    // and 51 objects from 1,001 sharing one name, more than a shared value is paired for. The rest
    // carry no name or serial number, so their pairs score nothing and write no candidate.
    const fixed: Record<number, Record<string, string>> = {
      1: { name: "Kestrel Valve", serial_number: "KV-1" }, 2: { name: "Kestrel Valve", serial_number: "KV-1" },
      1097: { name: "Heron Gate", serial_number: "HG-1" }, 1098: { name: "Heron Gates", serial_number: "HG-2" },
      1099: { name: "Osprey Pump", serial_number: "OP-9" }, 1100: { name: "osprey pump", serial_number: "op 9" }
    };
    const crowd = (index: number): Record<string, string> => (index >= 1001 && index <= 1051 ? { name: "Crowded Tank" } : {});
    const typeId = await entityType(page, (id) => Array.from({ length: 1100 }, (unused, offset) => {
      const index = offset + 1;
      return { id: `${id}_${String(index).padStart(4, "0")}`, status: "RUNNING", ...crowd(index), ...(fixed[index] ?? {}) };
    }));

    await page.goto("/workspace/decision");
    await page.getByLabel("Decision object type").selectOption(typeId);
    await expect(page.getByRole("status")).toHaveText("Ontology context loaded");
    const views = page.getByRole("navigation", { name: "Decision intelligence views" });
    await views.getByRole("button", { name: "Entity Resolution" }).click();
    await page.getByRole("button", { name: "Find duplicates" }).click();
    await expect(page.getByRole("status")).toHaveText("Entity review queue generated", { timeout: 180_000 });

    const queue = page.locator(".panel").filter({ has: page.getByRole("heading", { name: "Candidate Review Queue", exact: true }) });
    const pair = (left: number, right: number) => queue.locator("article strong").filter({ hasText: `${typeId}_${String(left).padStart(4, "0")} + ${typeId}_${String(right).padStart(4, "0")}` });
    await expect(pair(1, 2), "the pair inside the scan was not found").toHaveCount(1);
    await expect(pair(1099, 1100), "the exact pair past the scan was not reached").toHaveCount(1);
    await expect(pair(1097, 1098), "a near pair past the scan was compared, though the note says only shared values were").toHaveCount(0);
    const [scanned, inScope, rest] = await page.evaluate(() => [(1000).toLocaleString(), (1100).toLocaleString(), (100).toLocaleString()]);
    const note = queue.getByRole("note");
    await expect(note, "the queue does not say what it compared, what it paired, and what it left")
      .toHaveText(`Compared every pair among the first ${scanned} of ${inScope} objects, by id, and paired all ${inScope} on an exact name or serial_number, ignoring case and punctuation. Pairs involving the other ${rest} were compared only where they share such a value. 1 shared value held by more than 50 objects was not paired.`);
    await expectUnclipped(note, "the queue's note is cut off, hiding how many objects were compared");

    const badge = page.locator("h3", { hasText: "Duplicate warnings" }).locator("xpath=following-sibling::*[1]");
    await page.getByLabel("Decision object ID").fill(`${typeId}_1010`);
    await views.getByRole("button", { name: "Explain Object" }).click();
    await page.getByRole("button", { name: "Explain selected object" }).click();
    await expect(page.getByRole("status")).toHaveText("Explanation loaded");
    await expect(badge, "an object whose shared value was left unpaired is called clear, or said to have no exact match").toHaveText("not compared");
    await page.getByLabel("Decision object ID").fill(`${typeId}_1099`);
    await page.getByRole("button", { name: "Explain selected object" }).click();
    await expect(badge, "the exact pair's object does not carry its warning").toHaveText("1 warnings");
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
    const [scanned, all] = await page.evaluate(() => [(1000).toLocaleString(), (1002).toLocaleString()]);
    await expect(queue.getByText(`No candidates among the first ${scanned} objects, or from an exact name or serial_number match across all ${all}`),
      "the empty queue claims the whole type, or leaves out the exact pass").toBeVisible();

    // Past the scan, with nothing shared and nothing left unpaired: the exact pass read it and paired it with nothing.
    await page.getByLabel("Decision object ID").fill(`${typeId}_1002`);
    await page.getByRole("navigation", { name: "Decision intelligence views" }).getByRole("button", { name: "Explain Object" }).click();
    await page.getByRole("button", { name: "Explain selected object" }).click();
    await expect(page.getByRole("status")).toHaveText("Explanation loaded");
    const badge = page.locator("h3", { hasText: "Duplicate warnings" }).locator("xpath=following-sibling::*[1]");
    await expect(badge, "an object the exact pass read and paired with nothing is called clear, or not compared").toHaveText("no exact-match candidate");
  });
});
