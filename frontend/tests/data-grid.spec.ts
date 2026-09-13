import { expect, test, type Page } from "@playwright/test";

/**
 * The records grid sorts and hides columns. N7a of `GOAL_HONEST_UI_2026-09-11.md`.
 *
 * The data-media records table is the first `DataGrid`. What it kept from
 * `DataTable` -- every column, the true-count caption, every row reachable -- is
 * held by `data-table.spec.ts`, which reads the same panel. What it gained is here.
 */
async function openDataset(page: Page, name: string, records: Array<Record<string, string>>) {
  const created = await page.request.post("/data-assets", { data: {
    id: `grid_${Date.now()}_${Math.round(Math.random() * 1e6)}`,
    project_id: "default",
    display_name: name,
    kind: "dataset",
    asset_schema: { name: "string" },
    records
  } });
  expect(created.ok(), await created.text()).toBeTruthy();
  await page.goto("/workspace/data-media");
  const row = page.getByRole("button", { name });
  await row.click();
  await expect(row).toHaveClass(/selected/);
  const panel = page.locator(".panel").filter({ has: page.getByRole("heading", { name: `Records — ${name}` }) });
  await expect(panel.locator("table")).toBeVisible();
  return panel;
}

test.describe("the records grid sorts and hides columns", () => {
  test.beforeEach(async ({}, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-1280", "Runs once; the fixtures are stateful.");
  });

  test("clicking a column header sorts the grid by it, and says which way", async ({ page }) => {
    // Ranks chosen so that text order and natural order disagree: "10" and "22"
    // sort before "2" as text, after it as numbers read by eye.
    const panel = await openDataset(page, `Sort fixture ${Date.now()}`, [
      { name: "c", rank: "3" }, { name: "a", rank: "10" }, { name: "e", rank: "1" },
      { name: "b", rank: "22" }, { name: "d", rank: "2" }
    ]);
    const table = panel.locator("table");
    const rankHeader = table.locator("thead th").filter({ hasText: "rank" });
    const rankIndex = await table.locator("thead th").evaluateAll((cells) =>
      cells.findIndex((cell) => (cell.textContent || "").includes("rank")));
    const ranks = () => table.locator("tbody tr").evaluateAll((rows, index) =>
      rows.map((row) => row.children[index]?.textContent || ""), rankIndex);

    await expect(rankHeader, "an unsorted column claims an order").toHaveAttribute("aria-sort", "none");
    await rankHeader.getByRole("button").click();
    await expect(rankHeader).toHaveAttribute("aria-sort", "ascending");
    await expect.poll(ranks, { message: "the header click did not sort ascending, in natural order" })
      .toEqual(["1", "2", "3", "10", "22"]);

    await rankHeader.getByRole("button").click();
    await expect(rankHeader).toHaveAttribute("aria-sort", "descending");
    await expect.poll(ranks, { message: "a second click did not reverse the order" })
      .toEqual(["22", "10", "3", "2", "1"]);
  });

  test("a hidden column leaves the grid, and the grid says how many it is showing", async ({ page }) => {
    const panel = await openDataset(page, `Hide fixture ${Date.now()}`, [
      { name: "alpha", note: "first", rank: "1" }, { name: "beta", note: "second", rank: "2" }
    ]);
    const control = panel.locator("details.grid-columns");
    await expect(control.locator("summary"), "the grid does not count its columns").toHaveText("Columns · 3 of 3 shown");

    await control.locator("summary").click();
    await control.getByLabel("note").uncheck();

    await expect(panel.locator("table thead th").filter({ hasText: "note" }),
                 "the hidden column is still drawn").toHaveCount(0);
    await expect(control.locator("summary"),
                 "hiding a column is not counted, so the narrower grid reads as a dataset with fewer fields")
      .toHaveText("Columns · 2 of 3 shown");
  });
});
