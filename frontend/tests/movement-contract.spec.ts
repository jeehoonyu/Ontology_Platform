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

/**
 * The splitter, which is the one movement control not on dnd-kit, so it gets no
 * cancel for free. V2 and V3 of the goal. Measured before either: 220 → 382 during
 * a live resize, 382 after Escape, and 382 already in `localStorage`.
 */
test.describe("a resize can be taken back, and done without a drag", () => {
  const STORE = "ontology.panes.pipeline";
  const stored = (page: Page) => page.evaluate((key) => window.localStorage.getItem(key), STORE);
  const width = async (page: Page) =>
    Number(await page.getByRole("separator", { name: "Resize left pane" }).getAttribute("aria-valuenow"));

  test.beforeEach(async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-1280", "Runs once; below 700px the slots stack and there is no width.");
    await page.goto("/workspace/pipeline");
    await page.getByRole("button", { name: "Reset layout" }).click();
    await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {});
  });

  async function startResize(page: Page, distance: number) {
    const splitter = page.getByRole("separator", { name: "Resize left pane" });
    const box = await splitter.boundingBox();
    expect(box, "the left splitter has no layout").toBeTruthy();
    const x = box!.x + box!.width / 2;
    const y = box!.y + Math.min(100, box!.height / 2);
    await page.mouse.move(x, y);
    await page.mouse.down();
    for (let step = 1; step <= 10; step += 1) {
      await page.mouse.move(x + (distance * step) / 10, y);
      await page.waitForTimeout(16);
    }
  }

  test("Escape during a splitter resize restores the width and writes nothing", async ({ page }) => {
    const before = await width(page);
    const storedBefore = await stored(page);

    await startResize(page, 150);
    // Live: the separator reports a width the resize reached. Without this the
    // restore below could be a resize that never began.
    await expect.poll(() => width(page), { message: "the resize never started" }).toBeGreaterThan(before + 50);

    await page.keyboard.press("Escape");
    await page.mouse.up();

    await expect.poll(() => width(page), { message: "Escape did not restore the width the resize started from" })
      .toBe(before);
    expect(await stored(page), "a cancelled resize wrote the layout").toBe(storedBefore);
  });

  test("a pointer the system cancels leaves the width where it started", async ({ page }) => {
    const before = await width(page);
    const storedBefore = await stored(page);

    await startResize(page, 150);
    await expect.poll(() => width(page), { message: "the resize never started" }).toBeGreaterThan(before + 50);
    // What a touch taken over by a scroll or a system gesture delivers.
    await page.evaluate(() => window.dispatchEvent(new PointerEvent("pointercancel")));
    await page.mouse.up();

    await expect.poll(() => width(page), { message: "pointercancel left the resize applied" }).toBe(before);
    expect(await stored(page), "a cancelled resize wrote the layout").toBe(storedBefore);
  });

  test("a released pointer resize is kept and survives a reload", async ({ page }) => {
    // The guard on the other side of the change: a resize that previews until
    // release must still be stored on release, or cancelling became the only
    // thing a pointer could do.
    const before = await width(page);
    await startResize(page, 150);
    await page.mouse.up();

    await expect.poll(() => width(page)).toBeGreaterThan(before + 50);
    const kept = await width(page);
    expect(JSON.parse((await stored(page)) || "{}").sizes?.left, "the released width was not stored").toBe(kept);

    await page.reload();
    await expect.poll(() => width(page), { message: "the released width did not survive a reload" }).toBe(kept);
  });

  test("a slot resizes with a single pointer and no drag", async ({ page }) => {
    // WCAG 2.5.7: a single pointer, no drag. A native select is chosen with
    // clicks; nothing here holds a button down or moves while it is held.
    const choice = page.getByLabel("Width of left pane");
    // Named, so a build without the control fails here and says so rather than
    // as a 45-second `selectOption` timeout -- which is how the negative run
    // reported it before this line existed.
    await expect(choice, "there is no way to resize the slot without dragging").toHaveCount(1);
    await choice.selectOption("400");

    await expect.poll(() => width(page), { message: "choosing a width did not resize the slot" }).toBe(400);
    expect(JSON.parse((await stored(page)) || "{}").sizes?.left, "the chosen width was not stored").toBe(400);
  });
});
