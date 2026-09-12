import { expect, test } from "@playwright/test";

/**
 * The shared table, and the rows and columns it used to drop in silence.
 *
 * N3 of `GOAL_HONEST_UI_2026-09-11.md`. `DataTable` is the product's table --
 * 75 call sites across 16 files -- and it truncated three ways without saying
 * any of them:
 *
 *   safeRows.slice(0, 40)                       rows past the fortieth
 *   for (const row of safeRows.slice(0, 10))    columns from a ten-row sample
 *   Object.keys(row).slice(0, 8)                eight keys per sampled row
 *
 * The fixture below is built to separate them. Sixty records, of which the
 * forty-fifth carries a field none of the first forty-four has, and every
 * record carries eleven fields. So a build with the old component renders forty
 * rows with no caption and eight columns, and a build with the new one renders
 * forty rows under a caption naming sixty and a column for a field it can only
 * have found by reading past row ten.
 *
 * The second of the three was the worst and the least visible. Forty rows with
 * three fields missing look exactly like forty complete rows: nothing is cut
 * off, nothing scrolls, and the absent field is absent from the ten rows that
 * were sampled too. A person would have to already know the field existed.
 */
const ROWS = 60;
const LATE_FIELD = "late_only_field";

/** Eleven fields, so the old eight-key cap is exceeded by every record. */
function record(index: number) {
  const row: Record<string, string | number> = { id: `row-${String(index).padStart(3, "0")}` };
  for (let field = 1; field <= 10; field += 1) row[`field_${field}`] = `v${index}-${field}`;
  return row;
}

/** The Records panel's table for one named dataset, never the Schema panel's. */
function recordsTable(page: import("@playwright/test").Page, name: string) {
  return page.locator(".panel")
    .filter({ has: page.getByRole("heading", { name: `Records — ${name}` }) })
    .locator("table")
    .first();
}

test.describe("a table says what it is not showing", () => {
  test.beforeEach(async ({}, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-1280", "Runs once.");
  });

  test("a truncated table names the rows it left out", async ({ page }) => {
    const stamp = Date.now();
    const assetId = `table_truncation_${stamp}`;
    const name = `Truncation fixture ${stamp}`;
    const records = Array.from({ length: ROWS }, (unused, index) => record(index));
    // The forty-fifth record, which is past both the forty-row render limit and
    // the ten-row column sample the component used to take.
    records[44][LATE_FIELD] = "only here";

    const created = await page.request.post("/data-assets", { data: {
      id: assetId,
      project_id: "default",
      display_name: name,
      kind: "dataset",
      asset_schema: { id: "string" },
      records
    } });
    expect(created.ok(), await created.text()).toBeTruthy();

    await page.goto("/workspace/data-media");
    // Wait for the row to report itself selected before reading the table. The
    // list re-renders as assets load, so a click that lands mid-render selects
    // whatever moved under the pointer, and the table then answers about the
    // wrong dataset -- which reads as a failure of the thing being tested.
    const row = page.getByRole("button", { name });
    await row.click();
    await expect(row).toHaveClass(/selected/);

    // Scoped to the Records panel by the fixture's own name in its heading.
    // `.table-wrap table` first() picked up the Schema panel's table whenever
    // the records had not landed yet, and then reported about the wrong data.
    const table = recordsTable(page, name);
    await expect(table).toBeVisible();

    // The caption, which is the whole point: a limit a person can see is a
    // limit, and a limit a person cannot see is a wrong answer.
    await expect(table.locator("caption"),
                 "the table renders fewer rows than it was given and does not say so")
      .toHaveText(`Showing 40 of ${ROWS} rows`);
    await expect(table.locator("tbody tr")).toHaveCount(40);

    // And the column that only row forty-five could have supplied. Asserting on
    // the header rather than on a cell on purpose: the cell is not rendered,
    // because the row it belongs to is past the limit. The column is the claim
    // -- this dataset has such a field -- and the claim is what was missing.
    await expect(table.locator("thead th").filter({ hasText: LATE_FIELD }),
                 "a field that first appears in row 45 has no column, so its value is "
                 + "invisible in every row including the ones that are rendered")
      .toHaveCount(1);
    await expect(table.locator("thead th").filter({ hasText: "field_10" }),
                 "the eleventh key of every row is missing, so the eight-key cap is still on")
      .toHaveCount(1);
  });

  test("a table showing everything it was given says nothing", async ({ page }) => {
    // The caption is for a truncation, not a decoration. A three-row table that
    // announces "Showing 3 of 3 rows" trains a person to stop reading captions,
    // which costs exactly the thing the caption above buys.
    const stamp = Date.now();
    const assetId = `table_complete_${stamp}`;
    const name = `Complete fixture ${stamp}`;
    const created = await page.request.post("/data-assets", { data: {
      id: assetId,
      project_id: "default",
      display_name: name,
      kind: "dataset",
      asset_schema: { id: "string" },
      records: [record(1), record(2), record(3)]
    } });
    expect(created.ok(), await created.text()).toBeTruthy();

    await page.goto("/workspace/data-media");
    const row = page.getByRole("button", { name });
    await row.click();
    await expect(row).toHaveClass(/selected/);

    const table = recordsTable(page, name);
    await expect(table.locator("tbody tr")).toHaveCount(3);
    await expect(table.locator("caption"),
                 "a complete table is announcing a truncation that did not happen")
      .toHaveCount(0);
  });
});
