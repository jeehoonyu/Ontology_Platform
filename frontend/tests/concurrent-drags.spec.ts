import { expect, test } from "@playwright/test";

/**
 * Three kinds of drag on one screen, and none of them steals another's.
 *
 * M4 of `GOAL_PANES_2026-09-11.md`. The pipeline builder carries a pane that
 * moves between slots, a node that moves around a canvas, and a palette entry
 * that lands on that canvas — all inside **one** `DndContext`, because M2 found
 * that separate contexts break the palette outright and that nesting cannot fix
 * it: grips and palette entries are intermixed across panes, so whichever
 * context is nearer captures both.
 *
 * One context means three separate things have to tell a pane drag from
 * everything else, and each is its own way to get it wrong:
 *
 *   which droppables it may land on   `slotAwareCollision`
 *   what its drop means               `usePaneLayout.handleDragEnd`
 *   how an arrow key moves it         `slotKeyboardCoordinates`
 *
 * The first two arrived during M2, because the palette could not be made to work
 * without them. The third is this condition's own work, and it is the one that
 * cannot be seen without a test: a coordinate getter reaching a draggable it was
 * not written for is silent, leaves every pointer drag working, and is exactly
 * the bug `GOAL_DRAG` L8 records.
 */
const SCREEN = "/workspace/pipeline";
const LIBRARY = "Add data / transforms";

const slotOfPane = (page: import("@playwright/test").Page, title: string) =>
  page.locator(".pane").filter({ hasText: title }).first()
    .evaluate((element) => element.closest(".pane-slot")?.getAttribute("data-slot") || "");

test.describe("a pane, a node and a palette entry share one context", () => {
  test.beforeEach(async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-1280",
              "Runs once; below 700px the slots stack and there is no second slot to cross.");
    await page.goto(SCREEN);
    await page.getByRole("button", { name: "Reset panes" }).click();
  });

  test("one arrow key carries a pane to the next slot", async ({ page }) => {
    expect(await slotOfPane(page, LIBRARY), "the library does not start on the left")
      .toBe("left");

    // dnd-kit's default getter moves a keyboard drag 25px a press, so on a
    // 1280px screen a build without `slotKeyboardCoordinates` needs roughly
    // forty presses to cross a slot and this single press moves nothing at all.
    // Let the layout settle before starting. `Reset panes` writes state, the
    // workspace polls, and a re-render between the pick-up and the arrow key
    // takes dnd-kit's document listener with it -- which shows up as the
    // coordinate getter never being called at all.
    await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {});
    const grip = page.getByRole("button", { name: `Reorder ${LIBRARY}` });
    await grip.focus();
    await expect(grip, "the grip lost focus before the drag could start").toBeFocused();
    await page.keyboard.press("Space");

    // Synchronise on dnd-kit's live region rather than sleeping. An arrow key
    // pressed before the sensor has picked the pane up is lost entirely, which
    // is what made the first version of this report "the getter did nothing"
    // when the getter had never been asked.
    const announcement = page.locator("[id^='DndLiveRegion']").filter({ hasText: /pane:/ });
    await expect(announcement, "no announcement, so the pane drag never started")
      .toContainText(/draggable item/i);

    await page.keyboard.press("ArrowRight");
    await page.waitForTimeout(60);
    await expect(announcement, "the arrow key did not move the drag off its own slot")
      .toContainText(/moved over droppable area slot:(?!left)/);
    await page.keyboard.press("Space");
    await expect(announcement, "no drop was announced").toContainText(/dropped/i);

    // dnd-kit names the droppable it dropped over, so a failure here says which
    // slot won rather than only that the pane did not move.
    const said = (await announcement.first().textContent()) || "";
    await expect.poll(() => slotOfPane(page, LIBRARY),
                      { message: `one arrow key did not carry the pane to the next slot; `
                                 + `dnd-kit announced: ${said.trim()}` })
      .not.toBe("left");
  });

  test("a node under a pane still moves by pixels, not by slots", async ({ page }) => {
    // The same context, the same keyboard sensor, the same coordinate getter.
    // A node is not a pane, so its arrow keys must still move it the way they
    // did before panes existed. Both failure directions are asserted: the slot
    // getter swallowing the keys so the node does not move, and the slot getter
    // answering so the node jumps a slot's width.
    await page.getByRole("button", { name: "New pipeline" }).click();
    await expect(page.getByText(/Pipeline draft created/)).toBeVisible();
    const canvas = page.locator(".pipeline-canvas");
    await page.getByRole("button", { name: "Input Dataset input" }).click();
    await canvas.getByRole("button", { name: /^Add / }).click();

    const node = canvas.locator(".pipeline-node").first();
    await expect(node).toBeVisible();
    // Creating the node is a server round-trip that bumps a refresh key, and
    // starting the drag mid-flight loses the focus the keyboard sensor needs.
    await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {});

    // The committed position, never the bounding box: an arrow key can scroll a
    // container, which moves the box without moving the node, and a test that
    // read the box once passed against a build with its own wiring deleted.
    const left = async () => Number.parseFloat(
      (await node.evaluate((element) => (element as HTMLElement).style.left)) || "0");
    const before = await left();

    await node.focus();
    await expect(node, "the node lost focus before the drag could start").toBeFocused();
    await page.keyboard.press("Space");
    const announcement = page.locator("[id^='DndLiveRegion']").filter({ hasText: /node:/ });
    await expect(announcement, "no announcement, so the node drag never started")
      .toContainText(/draggable item/i);

    // Four presses, paced, matching `drag-affordances.spec.ts`. dnd-kit moves a
    // keyboard drag once per render and scrolls the container as it goes, so a
    // short burst can land as a net *leftward* few pixels -- measured at 120 to
    // 107.2 with two presses, which reads as "the getter took the keys" and is
    // not that at all.
    for (let step = 0; step < 4; step += 1) {
      await page.keyboard.press("ArrowRight");
      await page.waitForTimeout(60);
    }
    await page.keyboard.press("Space");
    await expect(announcement, "no drop was announced").toContainText(/dropped/i);

    await expect.poll(left,
                      { message: "the node did not move, so the pane getter took its keys" })
      .toBeGreaterThan(before);
    const after = await left();
    expect(after - before,
           "the node crossed a slot's width, so the pane getter answered for it")
      .toBeLessThan(200);
  });

  test("dragging the pane's own text does not move the pane", async ({ page }) => {
    // What grip-only activation actually buys, which is not what M4 assumed.
    //
    // The condition was written expecting the grip to be what stops a pane
    // stealing a node's pointer. It is not: dnd-kit refuses a second activation
    // while one is live, and a nested draggable's listener fires before its
    // ancestor's, so the palette and the canvas nodes are safe with or without
    // it. Measured, by spreading the pane's listeners onto the whole section and
    // watching every palette and node test stay green.
    //
    // What the grip protects is everything in a pane that is *not* a draggable:
    // prose a person is selecting, a list they are scrolling. With listeners on
    // the section, a drag begun anywhere in the body carries the pane off. This
    // is the assertion that fails against that build.
    const pane = page.locator(".pane").filter({ hasText: LIBRARY }).first();
    const prose = pane.locator(".pane-body p").first();
    await expect(prose).toBeVisible();
    const box = await prose.boundingBox();
    if (!box) throw new Error("the library pane has no prose to drag from");

    await page.mouse.move(box.x + 8, box.y + box.height / 2);
    await page.mouse.down();
    // Well past the 8px activation distance, and far enough to cross a slot.
    for (const step of [40, 160, 320]) {
      await page.mouse.move(box.x + 8 + step, box.y + box.height / 2, { steps: 4 });
    }
    await page.mouse.up();

    await expect.poll(() => slotOfPane(page, LIBRARY),
                      { message: "a drag begun on the pane's own text carried the pane "
                                 + "to another slot; the listeners are not grip-only" })
      .toBe("left");
  });

  test("a click on a palette entry under a pane grip is still a click", async ({ page }) => {
    // A guard rather than a proof: this passes with the grip wiring removed too,
    // because the 8px activation distance is what keeps a click a click. It is
    // here because that distance is easy to lose and this says so immediately.
    // The palette entry sits in a pane whose header carries a drag grip, and
    // both are draggables in one context with an 8px activation distance. A
    // click read as a zero-length drag, or a grip that captured the pointer for
    // its whole pane, would both show up here as the entry never arming.
    const entry = page.locator(".node-library button").first();
    await expect(entry).toBeVisible();
    await expect(entry, "an entry is armed before anything was clicked")
      .not.toHaveClass(/selected/);

    await entry.click();

    await expect(entry, "clicking a palette entry under a pane grip armed nothing")
      .toHaveClass(/selected/);
  });
});
