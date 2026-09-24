import { expect, test, type Page } from "@playwright/test";

/**
 * More than one node in one drag. M5 of `GOAL_PANES_2026-09-11.md`.
 *
 * Click selects a node, Shift-click adds one, and dragging any node of a
 * multi-node selection carries all of them by the same delta and commits once.
 * The test reads committed positions -- `style.left`, never a bounding box, for
 * the reason `GOAL_DRAG` L8 records -- and counts the layout requests, because
 * "moved together" and "saved once" are separate claims and a build can make the
 * first true with three requests.
 */
const leftOf = (page: Page, index: number) => page.locator(".pipeline-canvas .pipeline-node").nth(index)
  .evaluate((element) => Number.parseFloat((element as HTMLElement).style.left) || 0);

test("three selected nodes move together and commit once", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-1280", "Runs once; the fixtures are stateful.");
  await page.goto("/workspace/pipeline");
  await page.getByRole("button", { name: "Reset panes" }).click();
  await page.getByRole("button", { name: "New pipeline" }).click();
  await expect(page.getByText(/Pipeline draft created/)).toBeVisible();

  const canvas = page.locator(".pipeline-canvas");
  const nodes = canvas.locator(".pipeline-node");
  await page.getByRole("button", { name: "Input Dataset input" }).click();
  await canvas.getByRole("button", { name: /^Add / }).click();
  await expect(nodes).toHaveCount(1);

  // Two more through the selected node's own menu, which inserts after it.
  for (const count of [2, 3]) {
    const insert = canvas.locator(".node-context-menu button:not(.context-action-delete)").first();
    await expect(insert, "the selected node offers nothing to insert after it").toBeVisible();
    await insert.click();
    await expect(nodes).toHaveCount(count);
  }
  await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {});
  await canvas.evaluate((element) => { element.scrollLeft = 0; });

  await nodes.nth(0).click();
  await nodes.nth(1).click({ modifiers: ["Shift"] });
  await nodes.nth(2).click({ modifiers: ["Shift"] });
  await expect(canvas.locator(".pipeline-node.selected"), "Shift-click did not build a selection of three")
    .toHaveCount(3);
  await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {});

  const before = [await leftOf(page, 0), await leftOf(page, 1), await leftOf(page, 2)];
  const saves: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "PATCH" && request.url().includes("/layout")) saves.push(request.postData() || "");
  });

  await nodes.nth(0).focus();
  const announcement = page.locator("[id^='DndLiveRegion']").filter({ hasText: /node:/ });
  await page.keyboard.press("Space");
  await expect(announcement, "the node drag never started").toContainText(/draggable item/i);
  for (let step = 0; step < 4; step += 1) {
    await page.keyboard.press("ArrowRight");
    await page.waitForTimeout(60);
  }
  // Live: the nodes not being dragged already carry the drag, so the selection
  // moves as one rather than two nodes jumping into place on release.
  for (const index of [1, 2]) {
    await expect.poll(() => nodes.nth(index).evaluate((element) => (element as HTMLElement).style.transform),
                      { message: `selected node ${index + 1} did not move with the drag while it was live` })
      .toContain("translate3d");
  }
  await page.keyboard.press("Space");
  await expect(page.getByText(/Saved positions of 3 nodes\./), "the move was not committed as one").toBeVisible();

  const after = [await leftOf(page, 0), await leftOf(page, 1), await leftOf(page, 2)];
  const deltas = after.map((value, index) => value - before[index]);
  expect(deltas[0], "the dragged node did not move").toBeGreaterThan(20);
  for (const index of [1, 2]) {
    expect(Math.abs(deltas[index] - deltas[0]),
           `selected node ${index + 1} moved ${deltas[index].toFixed(1)} while the dragged one moved ${deltas[0].toFixed(1)}`)
      .toBeLessThanOrEqual(0.5);
  }
  expect(saves.length, "one drag of three nodes sent more than one layout request").toBe(1);

  // One drag, one history entry: one `Undo move` puts all three back with one more save,
  // and leaves nothing of the drag to take back.
  await page.getByRole("button", { name: "Undo move" }).click();
  for (const index of [0, 1, 2]) {
    await expect.poll(() => leftOf(page, index), { message: `one Undo did not put selected node ${index + 1} back` })
      .toBeCloseTo(before[index], 0);
  }
  await expect(page.getByRole("button", { name: "Undo move" }), "one drag left more than one Undo behind").toBeDisabled();
  expect(saves.length, "one Undo of a three-node drag sent more than one layout request").toBe(2);

  // Escape clears the selection, leaving only the primary node highlighted.
  await page.locator(".workbench-status-strip").click();
  await page.keyboard.press("Escape");
  await expect(canvas.locator(".pipeline-node.selected"), "Escape did not clear the selection")
    .toHaveCount(1);
});
