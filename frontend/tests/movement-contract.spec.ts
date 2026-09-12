import { expect, test, type Page } from "@playwright/test";

/**
 * Cancel and recover, operated against drags that are proven to be live.
 *
 * `GOAL_MOVEMENT_2026-09-12.md`. The research's interaction contract says Escape
 * restores the exact starting arrangement and one Undo reverses one completed
 * move. `oms/audit_movement_contract.py` counts every movement surface against
 * those stages and refuses a stage claimed as met without a test here to hold it.
 *
 * **Every cancel test first proves the drag was live.** The census probe that
 * preceded this file read two drags as "restored by Escape" that had never
 * started -- one was aimed at a node scrolled out of the canvas, so the pointer
 * landed on the sidebar and nothing was picked up. A drag that never began
 * restores perfectly. So each test asserts the state only a live drag has --
 * dnd-kit's `dragging` class, the transform it writes, the announcement it makes
 * -- before it presses Escape, and a failure there says the drag did not start
 * rather than that the cancel worked.
 */
const LIBRARY = "Add data / transforms";

const slotOf = (page: Page, title: string) => page.locator(".pane").filter({ hasText: title }).first()
  .evaluate((element) => element.closest(".pane-slot")?.getAttribute("data-slot") || "");

test.describe("a cancelled drag leaves everything where it was", () => {
  test.beforeEach(async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-1280", "Runs once; a pointer drag across slots needs the side-by-side layout.");
    await page.goto("/workspace/pipeline");
    await page.getByRole("button", { name: "Reset layout" }).click();
    await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {});
  });

  test("Escape during a pane drag leaves the pane in its slot", async ({ page }) => {
    expect(await slotOf(page, LIBRARY), "the library does not start on the left").toBe("left");
    const pane = page.locator(".pane").filter({ hasText: LIBRARY }).first();
    const grip = page.getByRole("button", { name: `Reorder ${LIBRARY}` });
    const from = await grip.boundingBox();
    const onto = await page.locator(".pane-slot-right").boundingBox();
    expect(from && onto, "the grip or the right slot has no layout").toBeTruthy();

    await page.mouse.move(from!.x + from!.width / 2, from!.y + from!.height / 2);
    await page.mouse.down();
    const targetX = onto!.x + onto!.width / 2;
    const targetY = onto!.y + 80;
    for (let step = 1; step <= 12; step += 1) {
      await page.mouse.move(from!.x + ((targetX - from!.x) * step) / 12, from!.y + ((targetY - from!.y) * step) / 12);
      await page.waitForTimeout(16);
    }

    // Live: the pane carries the drag's transform and dnd-kit has announced it
    // over another slot. Without both, Escape below would be tested against nothing.
    await expect.poll(() => pane.evaluate((element) => (element as HTMLElement).style.transform),
                      { message: "the pane drag never started" }).toContain("translate3d");
    await expect(page.locator("[id^='DndLiveRegion']").filter({ hasText: /pane:/ }),
                 "the drag was not over another slot when Escape was pressed")
      .toContainText(/moved over droppable area slot:(?!left)/);
    const stored = await page.evaluate(() => window.localStorage.getItem("ontology.panes.pipeline"));

    await page.keyboard.press("Escape");
    await page.mouse.up();

    await expect.poll(() => slotOf(page, LIBRARY),
                      { message: "Escape did not cancel the pane drag; the pane moved on release" })
      .toBe("left");
    expect(await page.evaluate(() => window.localStorage.getItem("ontology.panes.pipeline")),
           "a cancelled pane drag wrote the layout")
      .toBe(stored);
  });

  test("Escape during a pipeline node drag restores it and saves nothing", async ({ page }) => {
    await page.getByRole("button", { name: "New pipeline" }).click();
    await expect(page.getByText(/Pipeline draft created/)).toBeVisible();
    const canvas = page.locator(".pipeline-canvas");
    await page.getByRole("button", { name: "Input Dataset input" }).click();
    await canvas.getByRole("button", { name: /^Add / }).click();
    const node = canvas.locator(".pipeline-node").first();
    await expect(node).toBeVisible();
    await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {});
    // A new node can sit outside the canvas's scrolled viewport. Without this the
    // pointer lands on whatever is visible at those coordinates -- the sidebar, in
    // the probe -- and the drag never starts.
    await node.scrollIntoViewIfNeeded();
    await page.waitForTimeout(200);

    const left = async () => (await node.evaluate((element) => (element as HTMLElement).style.left)) || "";
    const before = await left();
    const writes: string[] = [];
    page.on("request", (request) => {
      if (request.method() !== "GET") writes.push(`${request.method()} ${new URL(request.url()).pathname}`);
    });

    const box = await node.boundingBox();
    const x = box!.x + box!.width / 2;
    const y = box!.y + box!.height / 2;
    await page.mouse.move(x, y);
    await page.mouse.down();
    for (let step = 1; step <= 10; step += 1) {
      await page.mouse.move(x + step * 12, y + step * 3);
      await page.waitForTimeout(30);
    }
    await expect(node, "the node drag never started").toHaveClass(/\bdragging\b/);

    await page.keyboard.press("Escape");
    await page.mouse.up();
    await page.waitForTimeout(800);

    expect(await left(), "Escape did not cancel the node drag; the node moved on release").toBe(before);
    expect(writes, "a cancelled node drag sent a write to the server").toEqual([]);
  });
});
