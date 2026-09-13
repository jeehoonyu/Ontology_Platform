import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Locator, type Page } from "@playwright/test";

/**
 * The records grid sorts, hides, widens, reorders and pins columns.
 *
 * N7a and N7b of `GOAL_HONEST_UI_2026-09-11.md`. The data-media records table is
 * the first `DataGrid`. What it kept from `DataTable` -- every column, the
 * true-count caption, every row reachable -- is held by `data-table.spec.ts`,
 * which reads the same panel. What it gained is here.
 *
 * N7b asks for each operation from a control that is not a drag (WCAG 2.5.7), so
 * every test below uses a select, a button or a checkbox, and none drags.
 */
async function createDataset(page: Page, name: string, records: Array<Record<string, string>>) {
  const created = await page.request.post("/data-assets", { data: {
    id: `grid_${Date.now()}_${Math.round(Math.random() * 1e6)}`,
    project_id: "default",
    display_name: name,
    kind: "dataset",
    asset_schema: { name: "string" },
    records
  } });
  expect(created.ok(), await created.text()).toBeTruthy();
}

function recordsPanel(page: Page, name: string) {
  return page.locator(".panel").filter({ has: page.getByRole("heading", { name: `Records — ${name}` }) });
}

async function openDataset(page: Page, name: string, records: Array<Record<string, string>>) {
  await createDataset(page, name, records);
  await page.goto("/workspace/data-media");
  const row = page.getByRole("button", { name });
  await row.click();
  await expect(row).toHaveClass(/selected/);
  const panel = recordsPanel(page, name);
  await expect(panel.locator("table")).toBeVisible();
  return panel;
}

const headerTexts = (table: Locator) => table.locator("thead .grid-sort").evaluateAll((buttons) =>
  buttons.map((button) => (button.textContent || "").replace(/[▲▼]/g, "").trim()));
const headerCell = (table: Locator, name: string) =>
  table.locator("thead th").filter({ has: table.page().getByRole("button", { name, exact: true }) });
const firstRowCells = (table: Locator) => table.locator("tbody tr").first().locator("td").allTextContents();
const xInWrap = (cell: Locator) => cell.evaluate((element) =>
  element.getBoundingClientRect().left - element.closest(".table-wrap")!.getBoundingClientRect().left);
// Which header a person hitting the middle of this one would actually hit.
const hitAtCentre = (cell: Locator) => cell.evaluate((element) => {
  element.scrollIntoView({ block: "center", inline: "nearest" });
  const box = element.getBoundingClientRect();
  return document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2)
    ?.closest("th")?.textContent?.replace(/[▲▼]/g, "").trim();
});
// The same, without scrolling first: for asking what is on top where the cell is now.
const hitWhereItIs = (cell: Locator) => cell.evaluate((element) => {
  const box = element.getBoundingClientRect();
  return document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2)
    ?.closest("th")?.textContent?.replace(/[▲▼]/g, "").trim();
});
const scrollWrap = (panel: Locator, left: number | "end") => panel.locator(".table-wrap").evaluate((element, to) => {
  element.scrollLeft = to === "end" ? element.scrollWidth : to;
}, left);

const wideRecords = Array.from({ length: 45 }, (unused, row) => ({
  id: `r${row}`,
  ...Object.fromEntries(Array.from({ length: 10 }, (alsoUnused, index) => [`field_${index + 1}`, `v${row}-${index + 1}`]))
}));

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
    // Exact: since N7b, "note" is also inside "Width of note", "Move note earlier" and "Pin note".
    await control.getByLabel("note", { exact: true }).uncheck();

    await expect(panel.locator("table thead th").filter({ hasText: "note" }),
                 "the hidden column is still drawn").toHaveCount(0);
    await expect(control.locator("summary"),
                 "hiding a column is not counted, so the narrower grid reads as a dataset with fewer fields")
      .toHaveText("Columns · 2 of 3 shown");
  });
});

test.describe("the records grid resizes, reorders and pins columns without a drag", () => {
  test.beforeEach(async ({}, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-1280", "Runs once; the fixtures are stateful.");
  });

  test("a column widens from a select, with a single pointer and no drag", async ({ page }) => {
    const panel = await openDataset(page, `Width fixture ${Date.now()}`, [
      { name: "alpha", note: "first", rank: "1" }, { name: "beta", note: "second", rank: "2" }
    ]);
    const table = panel.locator("table");
    const control = panel.locator("details.grid-columns");
    await control.locator("summary").click();
    const width = control.getByRole("combobox", { name: "Width of note" });
    await expect(width, "there is no way to resize a column without dragging").toHaveCount(1);

    await width.selectOption("280");
    const noteWidth = () => headerCell(table, "note").evaluate((element) => Math.round(element.getBoundingClientRect().width));
    await expect.poll(noteWidth, { message: "choosing a width did not resize the column" }).toBe(280);
    const noteIndex = (await headerTexts(table)).indexOf("note");
    expect(await table.locator("tbody tr").first().locator("td").nth(noteIndex)
      .evaluate((element) => Math.round(element.getBoundingClientRect().width)), "the header widened and its cells did not").toBe(280);
    await expect(width).toHaveValue("280");
    await expect(control.getByRole("status")).toHaveText("note is Wide · 280px");

    await headerCell(table, "rank").getByRole("button").click();
    await expect(headerCell(table, "rank")).toHaveAttribute("aria-sort", "ascending");
    await expect.poll(noteWidth, { message: "a width did not survive a sort" }).toBe(280);
  });

  test("a column moves earlier and later with buttons, its values move with it, and focus stays on the button", async ({ page }) => {
    const panel = await openDataset(page, `Order fixture ${Date.now()}`, [
      { name: "alpha", note: "first", rank: "1" }, { name: "beta", note: "second", rank: "2" }
    ]);
    const table = panel.locator("table");
    const control = panel.locator("details.grid-columns");
    const status = control.getByRole("status");
    await control.locator("summary").click();
    const later = control.getByRole("button", { name: "Move name later" });

    await later.focus();
    await page.keyboard.press("Enter");
    await expect.poll(() => headerTexts(table), { message: "the header did not move" }).toEqual(["note", "name", "rank"]);
    expect(await firstRowCells(table), "the header moved and its values did not").toEqual(["first", "alpha", "1"]);
    await expect(status).toHaveText("name moved, column 2 of 3");
    // React moves the `name` row here, which is the case that loses focus.
    await expect(later, "moving the column threw keyboard focus away").toBeFocused();

    await page.keyboard.press("Enter");
    await expect.poll(() => headerTexts(table)).toEqual(["note", "rank", "name"]);
    await expect(later).toHaveAttribute("aria-disabled", "true");
    await expect(later, "the button at the edge dropped focus").toBeFocused();

    await page.keyboard.press("Enter");
    await expect(status).toHaveText("name is already the last unpinned column");
    expect(await headerTexts(table)).toEqual(["note", "rank", "name"]);
    // A polite live region does not re-read text that did not change, so a second
    // press at the edge has to put a new node there to be heard at all.
    await status.locator("span").evaluate((element) => element.setAttribute("data-announced", "once"));
    await page.keyboard.press("Enter");
    await expect(status.locator("span[data-announced]"), "a second press at the edge changed nothing, so it is announced to no one")
      .toHaveCount(0);
    await expect(status).toHaveText("name is already the last unpinned column");

    await control.getByRole("button", { name: "Move name earlier" }).click();
    await control.getByRole("button", { name: "Move name earlier" }).click();
    await expect.poll(() => headerTexts(table)).toEqual(["name", "note", "rank"]);
    await expect(status).toHaveText("name moved, column 1 of 3");

    await control.getByLabel("note", { exact: true }).uncheck();
    await expect(status, "hiding a column rewrote the last move's announcement instead of saying what happened")
      .toHaveText("note hidden, 2 of 3 columns shown");
    await later.click();
    await expect.poll(() => headerTexts(table), { message: "a move swapped with a hidden column, so nothing visible moved" })
      .toEqual(["rank", "name"]);
    await expect(status).toHaveText("name moved, column 2 of 2");
  });

  test("a pinned column stays in view while the grid scrolls sideways, over its own values, and the caption stays readable", async ({ page }) => {
    const panel = await openDataset(page, `Pin fixture ${Date.now()}`, wideRecords);
    const table = panel.locator("table");
    const wrap = panel.locator(".table-wrap");
    const control = panel.locator("details.grid-columns");
    const summary = control.locator("summary");
    const status = control.getByRole("status");
    await summary.click();
    await control.getByRole("combobox", { name: "Width of field_7" }).selectOption("100");
    await control.getByRole("combobox", { name: "Width of field_3" }).selectOption("100");
    const room = await wrap.evaluate((element) => ({ overflow: element.scrollWidth > element.clientWidth, width: element.clientWidth }));
    expect(room.overflow && room.width >= 380, `the grid does not overflow, so pinning proves nothing: ${JSON.stringify(room)}`).toBeTruthy();

    await control.getByRole("checkbox", { name: "Pin field_7" }).check();
    await expect(summary, "a pin moved a column to the front and the grid did not say so")
      .toHaveText("Columns · 11 of 11 shown · 1 pinned");
    expect((await headerTexts(table))[0]).toBe("field_7");
    expect((await firstRowCells(table))[0], "the pinned header sits over another column's values").toBe("v0-7");

    await scrollWrap(panel, 900);
    expect(await xInWrap(headerCell(table, "id")), "the grid did not scroll, so this proves nothing").toBeLessThan(0);
    await expect.poll(() => xInWrap(headerCell(table, "field_7")), { message: "the pinned column scrolled out of view with the rest" })
      .toBeGreaterThanOrEqual(0);
    expect(await xInWrap(headerCell(table, "field_7"))).toBeLessThanOrEqual(2);
    const pinnedCell = table.locator("tbody tr").first().locator("td").first();
    expect(await xInWrap(pinnedCell), "the pinned column's values scrolled away from its header").toBeLessThanOrEqual(2);
    expect(await xInWrap(pinnedCell)).toBeGreaterThanOrEqual(0);
    const caption = await xInWrap(table.locator("caption > span"));
    expect(caption >= 0 && caption <= 10, `the true-count caption scrolled out of view with the columns: ${caption}`).toBeTruthy();
    const backgrounds = await Promise.all([headerCell(table, "field_7"), pinnedCell].map((cell) =>
      cell.evaluate((element) => getComputedStyle(element).backgroundColor)));
    expect(backgrounds.filter((colour) => colour === "rgba(0, 0, 0, 0)" || colour === "transparent"),
           "pinned cells are see-through, so the columns scrolling under them show through").toEqual([]);

    await control.getByRole("checkbox", { name: "Pin field_3" }).check();
    await expect.poll(() => xInWrap(headerCell(table, "field_3")), { message: "the second pinned column is drawn over the first" })
      .toBeGreaterThanOrEqual(100);
    expect(await xInWrap(headerCell(table, "field_3"))).toBeLessThanOrEqual(102);

    await scrollWrap(panel, "end");
    expect(await hitAtCentre(headerCell(table, "field_10")), "the pinned columns cover the columns beside them").toBe("field_10");

    // Moving among the pinned columns writes the pin order, not the column order.
    const earlier3 = control.getByRole("button", { name: "Move field_3 earlier" });
    await earlier3.focus();
    await page.keyboard.press("Enter");
    await expect.poll(async () => (await headerTexts(table)).slice(0, 2), { message: "a pinned column did not move among the pinned columns" })
      .toEqual(["field_3", "field_7"]);
    expect((await firstRowCells(table)).slice(0, 2), "the pinned header moved and its values did not").toEqual(["v0-3", "v0-7"]);
    await expect(status).toHaveText("field_3 moved, column 1 of 11");
    await expect(earlier3).toBeFocused();
    await expect(earlier3).toHaveAttribute("aria-disabled", "true");
    await page.keyboard.press("Enter");
    await expect(status).toHaveText("field_3 is already the first pinned column");

    const pin7 = control.getByRole("checkbox", { name: "Pin field_7" });
    await pin7.focus();
    await page.keyboard.press("Space");
    await expect(pin7).not.toBeChecked();
    await expect(pin7, "unpinning moved the row and threw keyboard focus away").toBeFocused();
    await control.getByRole("checkbox", { name: "Pin field_3" }).uncheck();
    await expect.poll(async () => (await headerTexts(table)).indexOf("field_7"),
                      { message: "unpinning did not put the column back where it was" }).toBe(7);
    expect(await headerTexts(table)).toEqual(["id", ...Array.from({ length: 10 }, (unused, index) => `field_${index + 1}`)]);
    await expect(summary).toHaveText("Columns · 11 of 11 shown");

    // A hidden column can be pinned, and has nothing on screen to keep in view.
    await control.getByRole("checkbox", { name: "Pin field_5" }).check();
    await control.getByLabel("field_1", { exact: true }).uncheck();
    await control.getByRole("checkbox", { name: "Pin field_1", exact: true }).check();
    await expect(status, "a hidden column was announced as staying in view").toHaveText("field_1 pinned, hidden");
  });

  test("a header focused under the pinned columns is scrolled clear of them", async ({ page }) => {
    const panel = await openDataset(page, `Focus fixture ${Date.now()}`, wideRecords);
    const table = panel.locator("table");
    const control = panel.locator("details.grid-columns");
    await control.locator("summary").click();
    for (const id of ["field_7", "field_3"]) {
      await control.getByRole("combobox", { name: `Width of ${id}` }).selectOption("100");
      await control.getByRole("checkbox", { name: `Pin ${id}` }).check();
    }
    await expect(headerCell(table, "field_7")).toHaveCSS("position", "sticky");
    await table.locator("thead").evaluate((element) => element.scrollIntoView({ block: "center" }));
    // `id` is the first unpinned column, drawn from 200px. Scrolled 200px, it sits
    // wholly under the two 100px pins.
    await scrollWrap(panel, 200);
    expect(await hitWhereItIs(headerCell(table, "id")), "the header is not under the pins, so this proves nothing").not.toBe("id");

    await headerCell(table, "id").getByRole("button").focus();
    await expect.poll(() => hitWhereItIs(headerCell(table, "id")), { message: "focus landed on a header the pinned columns hide" })
      .toBe("id");
  });

  test("pinned columns that would leave no room scroll with the grid, and say so", async ({ page }) => {
    const panel = await openDataset(page, `Wide pin fixture ${Date.now()}`, wideRecords);
    const table = panel.locator("table");
    const wrap = panel.locator(".table-wrap");
    const control = panel.locator("details.grid-columns");
    await control.locator("summary").click();
    for (const id of ["field_2", "field_3"]) {
      await control.getByRole("combobox", { name: `Width of ${id}` }).selectOption("400");
      await control.getByRole("checkbox", { name: `Pin ${id}` }).check();
    }
    expect(800 + 180 > await wrap.evaluate((element) => element.clientWidth), "the pins fit, so this proves nothing").toBeTruthy();
    const note = panel.locator(".grid-pin-note");
    await expect(note, "the grid did not say why its pinned columns scroll").toBeVisible();
    await expect(headerCell(table, "field_2")).toHaveCSS("position", "static");
    await scrollWrap(panel, "end");
    expect(await hitAtCentre(headerCell(table, "field_10")), "the pinned columns cover the columns beside them").toBe("field_10");

    // A pin that fits at 1280 and not at a phone's width, reached by resizing the
    // window alone: the grid has to notice its own width change, not only a column's.
    await control.getByRole("checkbox", { name: "Pin field_3" }).uncheck();
    await control.getByRole("combobox", { name: "Width of field_2" }).selectOption("180");
    const wide = await wrap.evaluate((element) => element.clientWidth);
    expect(180 + 180 <= wide, `one default pin does not fit at 1280 (${wide}px), so this proves nothing`).toBeTruthy();
    await expect(note).toHaveCount(0);
    await expect(headerCell(table, "field_2")).toHaveCSS("position", "sticky");
    // Pinned again at this width, the announcement says it stays in view. It is the
    // one sentence that depends on the window, so it is the one a resize could rewrite.
    const status = control.getByRole("status");
    const pin2 = control.getByRole("checkbox", { name: "Pin field_2" });
    await pin2.uncheck();
    await pin2.check();
    const pinnedText = "field_2 pinned, column 1 of 11; it stays in view when the grid scrolls sideways";
    await expect(status).toHaveText(pinnedText);

    await page.setViewportSize({ width: 375, height: 812 });
    await expect.poll(() => wrap.evaluate((element) => element.clientWidth), { message: "the window narrowed and the grid did not" })
      .toBeLessThan(360);
    await expect(note, "the window narrowed past the pin, the grid did not notice, and the pin now covers it").toBeVisible();
    await expect(status, "a narrower window rewrote the pin's announcement, so a screen reader read it out again")
      .toHaveText(pinnedText);
    await expect(headerCell(table, "field_2")).toHaveCSS("position", "static");
    await scrollWrap(panel, "end");
    expect(await hitAtCentre(headerCell(table, "field_10")), "the pinned column covers the columns beside it at 375px").toBe("field_10");
  });

  test("Reset columns puts back width, place, pin and visibility, and leaves the sort alone", async ({ page }) => {
    const panel = await openDataset(page, `Reset fixture ${Date.now()}`, [
      { name: "alpha", note: "first", rank: "10" }, { name: "beta", note: "second", rank: "2" }
    ]);
    const table = panel.locator("table");
    const control = panel.locator("details.grid-columns");
    const summary = control.locator("summary");
    const status = control.getByRole("status");
    await summary.click();
    const reset = control.getByRole("button", { name: "Reset columns" });

    await expect(reset).toHaveAttribute("aria-disabled", "true");
    // From the keyboard: Playwright will not click an aria-disabled element, though a
    // browser delivers the click, and this button stays focusable on purpose.
    await reset.focus();
    await page.keyboard.press("Enter");
    await expect(status).toHaveText("Nothing to reset: every column is shown, unpinned, at the default width, in the dataset's order.");

    await control.getByRole("button", { name: "Move rank earlier" }).click();
    await control.getByRole("button", { name: "Move rank later" }).click();
    await expect.poll(() => headerTexts(table)).toEqual(["name", "note", "rank"]);
    await expect(reset, "Reset offers to undo a change that was taken back").toHaveAttribute("aria-disabled", "true");

    await headerCell(table, "rank").getByRole("button").click();
    await expect(headerCell(table, "rank")).toHaveAttribute("aria-sort", "ascending");
    await control.getByLabel("note", { exact: true }).uncheck();
    await control.getByRole("combobox", { name: "Width of name" }).selectOption("280");
    await control.getByRole("button", { name: "Move rank earlier" }).click();
    await control.getByRole("checkbox", { name: "Pin rank" }).check();
    await expect(summary).toHaveText("Columns · 2 of 3 shown · 1 pinned");

    await reset.click();
    await expect(summary, "Reset columns left a column hidden or pinned").toHaveText("Columns · 3 of 3 shown");
    await expect.poll(() => headerTexts(table), { message: "Reset columns did not put the columns back in the dataset's order" })
      .toEqual(["name", "note", "rank"]);
    expect(await headerCell(table, "name").evaluate((element) => Math.round(element.getBoundingClientRect().width))).toBe(180);
    await expect(headerCell(table, "rank"), "Reset columns also reset the sort, which its name does not claim")
      .toHaveAttribute("aria-sort", "ascending");
    await expect(reset).toHaveAttribute("aria-disabled", "true");
    await expect(status).toHaveText("Columns reset: every column shown, unpinned, at the default width, in the dataset's order. Sorting is unchanged.");
  });

  test("a column arrangement follows a replacement file's fields", async ({ page }) => {
    // The grid stays mounted when its own dataset reloads, so what it holds has to
    // make sense for fields that arrive in a different order, or not at all.
    const name = `Upload fixture ${Date.now()}`;
    const panel = await openDataset(page, name, [{ name: "a", note: "x", rank: "1" }]);
    const table = panel.locator("table");
    const control = panel.locator("details.grid-columns");
    const summary = control.locator("summary");
    await summary.click();
    // Moved and moved back: there is nothing to reset, so nothing may be held over.
    await control.getByRole("button", { name: "Move rank earlier" }).click();
    await control.getByRole("button", { name: "Move rank later" }).click();
    await control.getByRole("checkbox", { name: "Pin note" }).check();
    await expect(summary).toHaveText("Columns · 3 of 3 shown · 1 pinned");

    const file = page.locator(".panel").filter({ has: page.getByRole("heading", { name: "Upload File" }) }).locator('input[type="file"]');
    await file.setInputFiles({ name: "replacement.csv", mimeType: "text/csv", buffer: Buffer.from("rank,name\n2,b\n") });
    await expect.poll(() => headerTexts(table), { message: "a move taken back kept the old order over the file's" })
      .toEqual(["rank", "name"]);
    await expect(summary).toHaveText("Columns · 2 of 2 shown");
    await expect(control.getByRole("button", { name: "Reset columns" }),
                 "a pin on a field the file no longer has keeps Reset offering to undo it").toHaveAttribute("aria-disabled", "true");

    await file.setInputFiles({ name: "again.csv", mimeType: "text/csv", buffer: Buffer.from("note,rank,name\ny,3,c\n") });
    await expect.poll(() => headerTexts(table)).toEqual(["note", "rank", "name"]);
    await expect(summary, "a pin on a field that went away came back with it").toHaveText("Columns · 3 of 3 shown");
  });

  test("a column arrangement stays with the dataset it was made on", async ({ page }) => {
    const stamp = Date.now();
    await createDataset(page, `Layout B ${stamp}`, [{ name: "b", rank: "1" }]);
    const panelA = await openDataset(page, `Layout A ${stamp}`, [{ name: "a", rank: "1" }]);
    const controlA = panelA.locator("details.grid-columns");
    await controlA.locator("summary").click();
    await controlA.getByRole("checkbox", { name: "Pin rank" }).check();
    await expect(controlA.locator("summary")).toHaveText("Columns · 2 of 2 shown · 1 pinned");

    const rowB = page.getByRole("button", { name: `Layout B ${stamp}` });
    await rowB.click();
    await expect(rowB).toHaveClass(/selected/);
    const panelB = recordsPanel(page, `Layout B ${stamp}`);
    await expect(panelB.locator("table")).toBeVisible();
    await expect(panelB.locator("details.grid-columns summary"), "a pin made on another dataset reordered this one")
      .toHaveText("Columns · 2 of 2 shown");
    expect((await headerTexts(panelB.locator("table")))[0]).toBe("name");
  });

  test("the column controls are named, announced, and pass axe", async ({ page }) => {
    const panel = await openDataset(page, `Named fixture ${Date.now()}`, [
      { name: "alpha", note: "first", rank: "1" }, { name: "beta", note: "second", rank: "2" }
    ]);
    const control = panel.locator("details.grid-columns");
    await expect(control.locator('[role="status"]'),
                 "the live region appears with its first message, which is not announced").toHaveCount(1);

    await control.locator("summary").click();
    for (const id of ["name", "note", "rank"]) {
      await expect(control.getByLabel(id, { exact: true })).toHaveCount(1);
      await expect(control.getByRole("combobox", { name: `Width of ${id}` })).toHaveCount(1);
      await expect(control.getByRole("button", { name: `Move ${id} earlier` })).toHaveCount(1);
      await expect(control.getByRole("button", { name: `Move ${id} later` })).toHaveCount(1);
      await expect(control.getByRole("checkbox", { name: `Pin ${id}` })).toHaveCount(1);
    }
    // evaluator.spec.ts's axe sweep has no data-media route, so nothing else ever
    // runs axe over the grid.
    const results = await new AxeBuilder({ page })
      .include("details.grid-columns")
      .include(".table-wrap")
      .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
      .analyze();
    expect(results.violations.map((violation) => violation.id), "a column control is unnamed or unreachable").toEqual([]);
  });
});
