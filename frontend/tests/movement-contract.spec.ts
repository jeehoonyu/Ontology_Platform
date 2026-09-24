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

/**
 * A pane too narrow for its title and its controls keeps Collapse, `Move to…` and
 * Hide behind one `⋯` button (S4 of `GOAL_SHELL_2026-09-23.md`). Opens it when the
 * pane has one, so a test reaches the same select whatever width the pane is.
 */
async function paneControls(page: Page, title: string) {
  const menu = page.getByRole("button", { name: `Pane actions for ${title}` });
  if (await menu.count()) await menu.click();
}

const slotOf = (page: Page, title: string) => page.locator(".pane").filter({ hasText: title }).first()
  .evaluate((element) => element.closest(".pane-slot")?.getAttribute("data-slot") || "");

test.describe("a cancelled drag leaves everything where it was", () => {
  test.beforeEach(async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-1280", "Runs once; a pointer drag across slots needs the side-by-side layout.");
    await page.goto("/workspace/pipeline");
    await page.getByRole("button", { name: "Reset panes" }).click();
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

  test("Escape during a palette drag onto the pipeline canvas adds no node and writes nothing", async ({ page }) => {
    // V11. The palette rides the pipeline node's sensor on a different draggable, and
    // its drop is a server write: `addNodeAtDrop` posts the node the moment it lands.
    await page.getByRole("button", { name: "New pipeline" }).click();
    await expect(page.getByText(/Pipeline draft created/)).toBeVisible();
    const canvas = page.locator(".pipeline-canvas");
    await expect(canvas.locator(".pipeline-node"), "a new pipeline did not start empty").toHaveCount(0);
    await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {});

    const entry = page.getByRole("button", { name: "Input Dataset input" });
    const from = await entry.boundingBox();
    const onto = await canvas.boundingBox();
    expect(from && onto, "the palette entry or the canvas has no layout").toBeTruthy();
    const writes: string[] = [];
    page.on("request", (request) => {
      if (request.method() !== "GET") writes.push(`${request.method()} ${new URL(request.url()).pathname}`);
    });

    // Across to the middle of the canvas and a third of the way down, where the palette
    // drop in `evaluator.spec.ts` aims, in real steps: dnd-kit waits for 8px of movement.
    const x = from!.x + from!.width / 2;
    const y = from!.y + from!.height / 2;
    const targetX = onto!.x + onto!.width / 2;
    const targetY = onto!.y + onto!.height / 3;
    await page.mouse.move(x, y);
    await page.mouse.down();
    for (let step = 1; step <= 12; step += 1) {
      await page.mouse.move(x + ((targetX - x) * step) / 12, y + ((targetY - y) * step) / 12);
      await page.waitForTimeout(16);
    }
    // Live, and over the canvas: the entry carries dnd-kit's `dragging` class and the
    // canvas marks itself as the drop target. Released here instead, this adds a node.
    await expect(entry, "the palette drag never started").toHaveClass(/\bdragging\b/);
    await expect(canvas, "the palette drag was not over the canvas when Escape was pressed")
      .toHaveClass(/\bdrag-active\b/);

    await page.keyboard.press("Escape");
    await page.mouse.up();
    await page.waitForTimeout(800);

    // The requests first: a drop posts the node at once and draws it only when the
    // server answers, so the request is the witness that cannot arrive late.
    expect(writes, "a cancelled palette drag sent a write to the server").toEqual([]);
    await expect(canvas.locator(".pipeline-node"), "Escape did not cancel the palette drag; a node was added on release")
      .toHaveCount(0);
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
    await page.getByRole("button", { name: "Reset panes" }).click();
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

/**
 * A node on an artifact canvas -- Workshop, AIP Logic, Investigations, Entity
 * Resolution -- which moves on xyflow rather than dnd-kit, so neither its history
 * nor its cancel came with the drag library. V4 and V5 of the goal. Measured
 * before either: one drag took eight Undo presses to reverse, and Escape left
 * the node where the pointer had taken it.
 */
test.describe("a graph node move is one entry, and Escape takes it back", () => {
  const nodes = (page: Page) => page.locator(".visual-flow-canvas .react-flow__node");
  const position = (page: Page, index: number) =>
    nodes(page).nth(index).evaluate((element) => (element as HTMLElement).style.transform);

  test.beforeEach(async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-1280", "Runs once; the canvas drag is a desktop pointer gesture.");
    await page.goto("/workspace/workshop");
    const draft = page.getByRole("button", { name: "Create draft" });
    await expect(draft.or(page.locator(".visual-builder-shell")).first()).toBeVisible();
    if (await draft.isVisible()) await draft.click();
    await expect(page.locator(".node-library-list button").first()).toBeVisible();
  });

  /** Adds a node from the library and returns its index on the canvas. */
  async function addNode(page: Page) {
    const before = await nodes(page).count();
    await page.locator(".node-library-list button").first().click();
    await expect(nodes(page)).toHaveCount(before + 1);
    await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {});
    return before;
  }

  /** Picks the node up and carries it, leaving the pointer held. Asserts it is live. */
  async function carry(page: Page, index: number) {
    const box = await nodes(page).nth(index).boundingBox();
    expect(box, "the node has no layout").toBeTruthy();
    const x = box!.x + box!.width / 2;
    const y = box!.y + box!.height / 2;
    await page.mouse.move(x, y);
    await page.mouse.down();
    await page.waitForTimeout(50);
    for (let step = 1; step <= 20; step += 1) {
      await page.mouse.move(x + step * 8, y + step * 3);
      await page.waitForTimeout(20);
    }
    await expect(nodes(page).nth(index), "the node drag never started").toHaveClass(/\bdragging\b/);
  }

  test("one drag on an artifact canvas is taken back by one Undo", async ({ page }) => {
    const index = await addNode(page);
    const start = await position(page, index);

    await carry(page, index);
    await page.mouse.up();
    await expect.poll(() => position(page, index), { message: "the drag did not move the node" }).not.toBe(start);

    await page.getByRole("button", { name: "Undo" }).click();

    await expect.poll(() => position(page, index),
                      { message: "one Undo did not take back one drag; the move was recorded as many entries" })
      .toBe(start);
    await expect(nodes(page), "one Undo took back more than the drag").toHaveCount(index + 1);
  });

  test("Escape during an artifact canvas drag restores the node and records nothing", async ({ page }) => {
    const index = await addNode(page);
    const start = await position(page, index);

    await carry(page, index);
    await expect.poll(() => position(page, index), { message: "the live drag had not moved the node" }).not.toBe(start);
    await page.keyboard.press("Escape");
    // The pointer is still held after Escape, and xyflow still reports the drag;
    // one more move proves those reports are discarded rather than applied.
    await page.mouse.move(40, 40);
    await page.mouse.up();

    await expect.poll(() => position(page, index), { message: "Escape did not restore the node" }).toBe(start);
    // The most recent entry must still be the add: a cancelled drag that left an
    // entry behind would make this Undo put the node back instead of removing it.
    await page.getByRole("button", { name: "Undo" }).click();
    await expect(nodes(page), "the cancelled drag left a history entry behind").toHaveCount(index);
  });

  // V11. Two more DragKit drags on this screen, neither of which needed product code:
  // dnd-kit answers Escape with `onDragCancel` and neither context has one, a library
  // entry's click and its drop both go through `addNode`, and a field reorder goes
  // through `updateSelected`; each records one history entry. The census had all four
  // stages as not measured, and a stage nobody has operated is not one that works.
  const ids = (page: Page) => nodes(page).evaluateAll((elements) =>
    elements.map((element) => element.getAttribute("data-id") || "").sort());
  const labels = (page: Page) =>
    page.locator(".node-inspector-form .config-field-row .config-field-label strong").allTextContents();

  /** Carries the first library entry over the canvas, leaving the pointer held. Asserts it is live. */
  async function carryFromLibrary(page: Page) {
    const entry = page.locator(".node-library-list button").first();
    const canvas = page.locator(".visual-flow-canvas");
    const from = await entry.boundingBox();
    const onto = await canvas.boundingBox();
    expect(from && onto, "the library entry or the canvas has no layout").toBeTruthy();
    const x = from!.x + from!.width / 2;
    const y = from!.y + from!.height / 2;
    const targetX = onto!.x + onto!.width / 2;
    const targetY = onto!.y + onto!.height / 3;
    await page.mouse.move(x, y);
    await page.mouse.down();
    await page.waitForTimeout(50);
    for (let step = 1; step <= 12; step += 1) {
      await page.mouse.move(x + ((targetX - x) * step) / 12, y + ((targetY - y) * step) / 12);
      await page.waitForTimeout(20);
    }
    // Live, and over the canvas: the drop target marks itself. Released here, this adds a node.
    await expect(canvas, "the library drag never reached the canvas").toHaveClass(/\bdrag-active\b/);
  }

  /**
   * Adds a node whose configuration has fields, and returns its index and the fields' labels.
   * The builder catalog carries the fields; the library drawn before it arrives has none.
   */
  async function nodeWithFields(page: Page) {
    await expect(page.locator(".node-library-list button").first(),
                 "the builder catalog, which carries each node's fields, has not loaded").toContainText("·");
    const index = await addNode(page);
    await expect(page.locator(".node-inspector-form"), "the new node's settings are not showing").toBeVisible();
    const before = await labels(page);
    expect(before.length, "the new node has fewer than two fields to reorder").toBeGreaterThanOrEqual(2);
    expect(before[0], "the first two fields cannot be told apart").not.toBe(before[1]);
    return { index, before };
  }

  /** Picks the first field up by its grip and carries it over the second, leaving the pointer held. */
  async function carryField(page: Page) {
    const rows = page.locator(".node-inspector-form .config-field-row");
    // Centred, so the pointer stays clear of the edges where dnd-kit scrolls the pane under it.
    await rows.nth(1).evaluate((element) => element.scrollIntoView({ block: "center" }));
    await page.waitForTimeout(200);
    const first = await rows.nth(0).boundingBox();
    const grip = await rows.nth(0).locator(".drag-grip").boundingBox();
    const second = await rows.nth(1).boundingBox();
    expect(first && grip && second, "the field rows have no layout to drag across").toBeTruthy();
    const x = grip!.x + grip!.width / 2;
    const y = grip!.y + grip!.height / 2;
    // The first row's centre carried a quarter of a row past the second's, so the second
    // is the nearest and the third is not.
    const distance = second!.y + second!.height * 0.75 - (first!.y + first!.height / 2);
    await page.mouse.move(x, y);
    await page.mouse.down();
    await page.waitForTimeout(50);
    for (let step = 1; step <= 10; step += 1) {
      await page.mouse.move(x, y + (distance * step) / 10);
      await page.waitForTimeout(20);
    }
    // Live, and over the second field: that row has moved up to make room, which it does
    // only while a drag holding the first is over it.
    await expect.poll(() => rows.nth(1).evaluate((element) => (element as HTMLElement).style.transform),
                      { message: "the field drag never reached the second field" })
      .toMatch(/translate3d\(0px, -/);
  }

  test("Escape during a library drag onto an artifact canvas adds no node and records nothing", async ({ page }) => {
    // A node added by click first, so the most recent history entry is known.
    const index = await addNode(page);
    const kept = await ids(page);

    await carryFromLibrary(page);
    await page.keyboard.press("Escape");
    await page.mouse.up();
    await page.waitForTimeout(500);

    expect(await ids(page), "Escape did not cancel the library drag; a node was added on release").toEqual(kept);
    // Records nothing, proven as V5 proves it: the add's autosave can land during the
    // drag, so a request count says nothing here and the history does. One Undo must
    // still take back the add.
    await page.getByRole("button", { name: "Undo" }).click();
    await expect(nodes(page), "the cancelled library drag left a history entry behind").toHaveCount(index);
  });

  test("one Undo takes back a node dropped from the library", async ({ page }) => {
    // An earlier entry first, so an Undo that took back more than the drop would show.
    await addNode(page);
    const kept = await ids(page);

    await carryFromLibrary(page);
    await page.mouse.up();
    // dnd-kit swallows the click that follows a drop: it stops the click's propagation until its
    // listeners detach, 50 ms after the drag ends (@dnd-kit/core, core.esm.js:1479, 1506). An Undo
    // pressed sooner never runs, which no person does and a test does without this.
    await page.waitForTimeout(150);
    await expect(nodes(page), "the drop placed no node").toHaveCount(kept.length + 1);

    const undo = page.getByRole("button", { name: "Undo" });
    await expect(undo, "the dropped node left nothing to undo").toBeEnabled();
    await undo.click();
    await expect.poll(() => ids(page), { message: "one Undo did not take back exactly the dropped node" })
      .toEqual(kept);
  });

  test("Escape during a field reorder keeps the order and records nothing", async ({ page }) => {
    const { index, before } = await nodeWithFields(page);

    await carryField(page);
    await page.keyboard.press("Escape");
    await page.mouse.up();
    await page.waitForTimeout(300);

    expect(await labels(page), "Escape did not cancel the field drag; the order changed on release").toEqual(before);
    // The most recent entry must still be the node's addition.
    await page.getByRole("button", { name: "Undo" }).click();
    await expect(nodes(page), "the cancelled field drag left a history entry behind").toHaveCount(index);
  });

  test("one Undo takes back one field reorder", async ({ page }) => {
    const { index, before } = await nodeWithFields(page);

    await carryField(page);
    await page.mouse.up();
    // dnd-kit swallows the click that follows a drop: it stops the click's propagation until its
    // listeners detach, 50 ms after the drag ends (@dnd-kit/core, core.esm.js:1479, 1506). An Undo
    // pressed sooner never runs, which no person does and a test does without this.
    await page.waitForTimeout(150);
    await expect.poll(() => labels(page), { message: "the drag did not reorder the fields" })
      .toEqual([before[1], before[0], ...before.slice(2)]);

    await page.getByRole("button", { name: "Undo" }).click();
    await expect.poll(() => labels(page), { message: "one Undo did not take back one reorder" }).toEqual(before);
    await expect(nodes(page), "one Undo took back more than the reorder").toHaveCount(index + 1);
  });

  test("a click on an artifact node records nothing (guard)", async ({ page }) => {
    // A guard, measured true before V4: clicking selects and must not snapshot.
    // Kept because moving the history entry to drag start is exactly the change
    // that would start recording clicks if xyflow began a drag on press.
    const index = await addNode(page);
    await nodes(page).nth(index).click();
    await page.getByRole("button", { name: "Undo" }).click();
    await expect(nodes(page), "a click on a node was recorded as an edit").toHaveCount(index);
  });
});

/**
 * A pipeline node, whose drop is saved to the server the moment it lands. V6 of
 * the goal. Before it, nothing could take a committed move back: the census
 * recorded the drop saving positions and no control of any kind reversing one.
 */
test.describe("an ontology drag that is cancelled changes nothing", () => {
  // V11. The field mapping and the property order ride the same dnd-kit sensor as the pipeline
  // and artifact drags, and neither context has an `onDragCancel`, so Escape ends the drag with
  // nothing committed. Both commit by writing -- a mapping refreshes its preview on the server and
  // a reorder saves the order -- so a request the drag sends is the witness that it committed.
  test.beforeEach(async ({}, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-1280", "Runs once; the fixtures are stateful and the drags need the side-by-side layout.");
  });

  const writesFrom = (page: Page) => {
    const writes: string[] = [];
    page.on("request", (request) => {
      if (request.method() !== "GET") writes.push(`${request.method()} ${new URL(request.url()).pathname}`);
    });
    return writes;
  };

  /** Presses on `from`'s centre and carries it to `to` in real steps: dnd-kit waits for 8px of movement. */
  async function carry(page: Page, from: { x: number; y: number; width: number; height: number }, to: { x: number; y: number }) {
    const x = from.x + from.width / 2;
    const y = from.y + from.height / 2;
    await page.mouse.move(x, y);
    await page.mouse.down();
    await page.waitForTimeout(50);
    for (let step = 1; step <= 12; step += 1) {
      await page.mouse.move(x + ((to.x - x) * step) / 12, y + ((to.y - y) * step) / 12);
      await page.waitForTimeout(20);
    }
  }

  test("Escape during a field-mapping drag maps nothing and writes nothing", async ({ page }) => {
    const bootstrap = await page.request.post("/scenarios/asset-reliability/bootstrap", { data: {} });
    expect(bootstrap.ok(), "the scenario that provides datasets did not bootstrap").toBeTruthy();
    await page.goto("/workspace/ontology");
    const panel = page.locator(".ontology-mapping-panel");
    await panel.getByLabel("Source dataset").selectOption({ index: 1 });
    await panel.getByRole("button", { name: "Preview objects" }).click();
    const target = panel.locator(".mapping-target").first();
    await expect(target).toBeVisible();
    const chooser = target.locator("select");
    await expect.poll(() => chooser.locator("option").count(), { message: "the preview offered no source fields" }).toBeGreaterThan(2);
    const held = await chooser.inputValue();
    const names = await panel.locator(".mapping-source-list button strong").allTextContents();
    const name = names.find((value) => value !== held);
    expect(name, "the dataset offers no field the first property does not already hold").toBeTruthy();
    const field = panel.locator(".mapping-source-list button").filter({ has: page.getByText(name as string, { exact: true }) }).first();
    await panel.locator(".ontology-mapping-grid").scrollIntoViewIfNeeded();
    await page.waitForTimeout(300);
    const from = await field.boundingBox();
    const onto = await target.boundingBox();
    expect(from && onto, "the field or the property has no layout").toBeTruthy();
    const writes = writesFrom(page);

    await carry(page, from!, { x: onto!.x + onto!.width / 2, y: onto!.y + onto!.height / 2 });
    // Live, and over the property: only a drag holding a field over it marks it.
    await expect(target, "the field drag was not over the property when Escape was pressed").toHaveClass(/\bdrag-active\b/);
    await page.keyboard.press("Escape");
    await page.mouse.up();
    await page.waitForTimeout(600);

    expect(writes, "a cancelled field drag sent a write to the server").toEqual([]);
    await expect(chooser, "Escape did not cancel the field drag; the property was mapped on release").toHaveValue(held);
  });

  test("Escape during a property-row drag keeps the order and writes nothing", async ({ page }) => {
    const suffix = Date.now();
    const displayName = `Cancelled Order ${suffix}`;
    const created = await page.request.post("/object-types", { data: {
      id: `cancelled_order_${suffix}`,
      display_name: displayName,
      description: "Browser evidence that Escape cancels a property reorder",
      properties: { alpha_reading: { type: "string", required: true }, beta_reading: { type: "string" }, gamma_reading: { type: "string" } }
    } });
    expect(created.ok(), await created.text()).toBeTruthy();
    await page.goto("/workspace/ontology");
    await page.locator(".manager-resource-nav .resource-row").filter({ hasText: displayName }).click();
    await page.getByRole("button", { name: "Edit fields" }).click();
    const rows = page.locator(".property-field-list .property-field-row");
    await expect(rows.nth(1)).toBeVisible();
    const names = () => rows.evaluateAll((articles) => articles.map((article) => article.querySelector("input")?.value || ""));
    const before = await names();
    expect(before.length, "the object type rendered fewer than two property rows").toBeGreaterThanOrEqual(2);
    // Centred, so the pointer stays clear of the edges where dnd-kit scrolls the pane under it.
    await rows.nth(1).evaluate((element) => element.scrollIntoView({ block: "center" }));
    await page.waitForTimeout(200);
    const grip = await rows.nth(0).locator(".drag-handle").boundingBox();
    const first = await rows.nth(0).boundingBox();
    const second = await rows.nth(1).boundingBox();
    expect(grip && first && second, "the property rows have no layout to drag across").toBeTruthy();
    const writes = writesFrom(page);

    // The first row's centre carried a quarter of a row past the second's, so the second is nearest.
    const distance = second!.y + second!.height * 0.75 - (first!.y + first!.height / 2);
    await carry(page, grip!, { x: grip!.x + grip!.width / 2, y: grip!.y + grip!.height / 2 + distance });
    // Live, and over the second row: it has moved up to make room, which it does only mid-drag.
    await expect.poll(() => rows.nth(1).evaluate((element) => (element as HTMLElement).style.transform),
                      { message: "the property drag never reached the second row" }).toMatch(/translate3d\(0px, -/);
    await page.keyboard.press("Escape");
    await page.mouse.up();
    await page.waitForTimeout(600);

    expect(writes, "a cancelled property drag sent a write to the server").toEqual([]);
    await expect.poll(names, { message: "Escape did not cancel the property drag; the order changed on release" }).toEqual(before);
  });
});

test.describe("a committed pipeline move can be taken back", () => {
  test.beforeEach(async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-1280", "Runs once; the fixtures are stateful.");
    await page.goto("/workspace/pipeline");
    await page.getByRole("button", { name: "Reset panes" }).click();
    await page.getByRole("button", { name: "New pipeline" }).click();
    await expect(page.getByText(/Pipeline draft created/)).toBeVisible();
    await page.getByRole("button", { name: "Input Dataset input" }).click();
    await page.locator(".pipeline-canvas").getByRole("button", { name: /^Add / }).click();
    await expect(page.locator(".pipeline-canvas .pipeline-node")).toHaveCount(1);
    await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {});
  });

  test("one Undo takes back a committed pipeline node move", async ({ page }) => {
    const node = page.locator(".pipeline-canvas .pipeline-node").first();
    const left = async () => Number.parseFloat((await node.evaluate((element) => (element as HTMLElement).style.left)) || "0");
    // In view first. A node outside the canvas's scrolled viewport has its arrow
    // keys spent scrolling the canvas by dnd-kit's keyboard sensor, and the move
    // lands a few pixels along -- measured at 9.3 once a header button was removed
    // and the canvas opened scrolled differently. GOAL_DRAG L8, from the other side.
    // From the canvas's own origin, unscrolled. A pipeline node picked up on a canvas
    // already scrolled sideways is displaced by that scroll offset before any key is
    // pressed, and the drop commits it: measured scrolled 103px at zoom 0.86, the
    // node jumped -119.8 stage px on pick-up, and four presses right landed it 3.5px
    // to the left. That was V10 of the goal, fixed with its own test; this one is
    // about taking a move back, and stays unscrolled so a regression of V10 fails V10. The three
    // placements tried before this -- in view, centred, at the edge -- each moved the
    // canvas and each failed differently, which is how the defect was found.
    await page.locator(".pipeline-canvas").evaluate((element) => { element.scrollLeft = 0; });
    await page.waitForTimeout(200);
    const before = await left();

    // The keyboard, so the move is a known committed drop with no bounding box
    // read; `a pipeline node moves with the keyboard` already proves the gesture.
    await node.focus();
    const announcement = page.locator("[id^='DndLiveRegion']").filter({ hasText: /node:/ });
    await page.keyboard.press("Space");
    await expect(announcement, "the node drag never started").toContainText(/draggable item/i);
    for (let step = 0; step < 4; step += 1) {
      await page.keyboard.press("ArrowRight");
      await page.waitForTimeout(60);
    }
    await page.keyboard.press("Space");
    await expect(page.getByText(/Saved .+ position\./), "the move was not committed").toBeVisible();
    await expect.poll(left, { message: "the move did not change the node's position" }).toBeGreaterThan(before + 20);

    // The Undo must reach the server, not only the screen: the layout request it
    // sends carries the position the node had before the move.
    const restores: Array<{ positions: Record<string, { x: number }> }> = [];
    page.on("request", (request) => {
      if (request.method() === "PATCH" && request.url().includes("/layout")) restores.push(request.postDataJSON());
    });
    const undo = page.getByRole("button", { name: "Undo move" });
    await expect(undo, "the committed move left nothing to undo").toBeEnabled();
    await undo.click();

    await expect.poll(left, { message: "Undo move did not put the node back" }).toBe(before);
    await expect.poll(() => restores.length, { message: "Undo move did not send the restored positions to the server" })
      .toBeGreaterThan(0);
    expect(Object.values(restores[0].positions).some((position) => position.x === before),
           `the undo sent no position matching the node's original x ${before}`)
      .toBeTruthy();
    await expect(page.getByRole("button", { name: "Undo move" }),
                 "one Undo left another move to take back").toBeDisabled();
  });

  test("a pipeline node that was only clicked leaves nothing to undo (guard)", async ({ page }) => {
    // A drop that moved nothing records nothing: `endCanvasDrag` returns before
    // committing when the delta is zero, and this holds that it stays so.
    const node = page.locator(".pipeline-canvas .pipeline-node").first();
    await node.scrollIntoViewIfNeeded();
    await node.click();
    await expect(page.getByRole("button", { name: "Undo move" }),
                 "a click on a node was recorded as a move").toBeDisabled();
  });
});

/**
 * Where a pipeline node's preview is during a drag, against where it lands. V7 of
 * the goal and the research's first evaluation scenario. Measured before it at
 * the zoom floor: dnd-kit's delta of 88 screen pixels was written as a transform
 * inside the scaled stage, so the preview had moved 48.4 pixels on screen while
 * the drop committed 160 stage pixels and landed 88 away -- the node trailed its
 * own landing and jumped on release.
 *
 * Everything is compared in stage pixels and read from the keyboard, so no
 * bounding box is involved: the pointer version of this measurement failed three
 * times because the canvas was still scrolling after the zoom presses.
 */
test.describe("a pipeline node's preview lands where its drop does", () => {
  test.beforeEach(async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-1280", "Runs once; the fixtures are stateful.");
    await page.goto("/workspace/pipeline");
    await page.getByRole("button", { name: "Reset panes" }).click();
    await page.getByRole("button", { name: "New pipeline" }).click();
    await expect(page.getByText(/Pipeline draft created/)).toBeVisible();
    await page.getByRole("button", { name: "Input Dataset input" }).click();
    await page.locator(".pipeline-canvas").getByRole("button", { name: /^Add / }).click();
    await expect(page.locator(".pipeline-canvas .pipeline-node")).toHaveCount(1);
    await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {});
  });

  const levels: Array<[string, string, number, number]> = [
    ["the zoom floor", "Zoom out", 12, 0.55],
    ["the fitted zoom", "Fit to view", 1, 0.86],
    ["the zoom ceiling", "Zoom in", 20, 1.35],
  ];

  for (const [label, control, presses, expected] of levels) {
    test(`at ${label} the drag preview and the landing agree`, async ({ page }) => {
      for (let press = 0; press < presses; press += 1) await page.getByRole("button", { name: control }).click();
      const scale = await page.locator(".canvas-stage").first()
        .evaluate((element) => Number(/scale\(([\d.]+)\)/.exec((element as HTMLElement).style.transform)?.[1] ?? NaN));
      expect(scale, `the canvas did not reach ${label}`).toBeCloseTo(expected, 5);
      await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {});

      const node = page.locator(".pipeline-canvas .pipeline-node").first();
      const left = async () => Number.parseFloat((await node.evaluate((element) => (element as HTMLElement).style.left)) || "0");
      // From the canvas's own origin, unscrolled. A pipeline node picked up on a canvas
      // already scrolled sideways is displaced by that scroll offset before any key is
      // pressed, and the drop commits it: measured scrolled 103px at zoom 0.86, the
      // node jumped -119.8 stage px on pick-up, and four presses right landed it 3.5px
      // to the left. That was V10 of the goal, fixed with its own test; this one is
      // about the preview against the landing, and stays unscrolled so a regression of V10 fails V10. The three
      // placements tried before this -- in view, centred, at the edge -- each moved the
      // canvas and each failed differently, which is how the defect was found.
      await page.locator(".pipeline-canvas").evaluate((element) => { element.scrollLeft = 0; });
      await page.waitForTimeout(200);
      const before = await left();

      await node.focus();
      const announcement = page.locator("[id^='DndLiveRegion']").filter({ hasText: /node:/ });
      await page.keyboard.press("Space");
      await expect(announcement, "the node drag never started").toContainText(/draggable item/i);
      for (let step = 0; step < 4; step += 1) {
        await page.keyboard.press("ArrowRight");
        await page.waitForTimeout(60);
      }
      await page.waitForTimeout(150);
      // The transform sits inside the scaled stage, so it is already in stage pixels.
      const preview = await node.evaluate((element) =>
        Number(/translate3d\(([-\d.]+)px/.exec((element as HTMLElement).style.transform)?.[1] ?? NaN));
      // A floor, not only a sign. If the arrow keys were spent scrolling, the preview
      // and the landing would agree at a few pixels and this test would pass having
      // measured nothing -- the V6 run showed exactly that movement, 9.3 pixels.
      expect(preview, "the drag barely moved, so the comparison below would prove nothing").toBeGreaterThan(20);

      await page.keyboard.press("Space");
      await expect(page.getByText(/Saved .+ position\./), "the move was not committed").toBeVisible();
      const landed = (await left()) - before;

      expect(Math.abs(preview - landed),
             `at zoom ${scale} the preview was ${preview.toFixed(1)} stage px along and the node landed `
             + `${landed.toFixed(1)} along, so it jumped on release`)
        .toBeLessThanOrEqual(1);
    });
  }
});

/**
 * Every save and reset names the scope it touches. V8 of the goal. The research
 * names four scopes -- personal workspace, authored artifact, saved analysis view,
 * transient work -- and asks that an action be named by the one it touches. The
 * census read three defects from the source: `Save layout` beside `Reset layout`
 * on one screen, meaning the shared artifact and a browser preference; Platform
 * Graph's `Save view` keeping positions only and saying nothing; and the ontology
 * designer inviting an arrangement and discarding every one on reload.
 */
test.describe("every save and reset names the scope it touches", () => {
  test.beforeEach(async ({}, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-1280", "Runs once; the fixtures are stateful.");
  });

  test("the pipeline screen has one control per scope", async ({ page }) => {
    // Node positions are saved by the drop itself (V6 proves the request), so a
    // button that re-sent them was a second name for the shared scope, and the
    // panes' reset was the same noun for a preference in this browser.
    await page.goto("/workspace/pipeline");
    await expect(page.getByRole("button", { name: "Save layout", exact: true }),
                 "a button re-saving positions every drop already saves is back").toHaveCount(0);
    await expect(page.getByRole("button", { name: "Reset panes", exact: true }),
                 "the panes' reset does not say it touches the panes").toHaveCount(1);
    await expect(page.getByRole("button", { name: "Reset layout", exact: true })).toHaveCount(0);
  });

  test("platform graph positions are kept on this device, and it says so", async ({ page }) => {
    expect((await page.request.post("/scenarios/asset-reliability/bootstrap", { data: {} })).ok()).toBeTruthy();
    await page.goto("/workspace/graph");
    const canvas = page.locator(".platform-graph-canvas");
    const node = canvas.locator(".react-flow__node").first();
    await expect(node).toBeVisible();
    const id = await node.getAttribute("data-id");
    const byId = canvas.locator(`.react-flow__node[data-id="${id}"]`);
    const position = () => byId.evaluate((element) => (element as HTMLElement).style.transform);
    const before = await position();

    const box = await byId.boundingBox();
    await page.mouse.move(box!.x + box!.width / 2, box!.y + box!.height / 2);
    await page.mouse.down();
    await page.mouse.move(box!.x + box!.width / 2 + 120, box!.y + box!.height / 2 + 80, { steps: 12 });
    await page.mouse.up();
    await expect.poll(position, { message: "the drag did not move the node" }).not.toBe(before);
    const moved = await position();

    await page.getByRole("button", { name: "Save positions on this device" }).click();
    await expect(page.getByRole("status").filter({ hasText: /saved in this browser/ }),
                 "saving gave no sign of what it kept")
      .toContainText("not part of it");

    await page.reload();
    await expect.poll(position, { message: "the saved positions did not come back after a reload" }).toBe(moved);
  });

  test("the ontology designer keeps an arrangement across a reload", async ({ page }) => {
    expect((await page.request.post("/scenarios/asset-reliability/bootstrap", { data: {} })).ok()).toBeTruthy();
    await page.goto("/workspace/ontology");
    const canvas = page.locator(".ontology-relationship-canvas");
    const node = canvas.locator(".react-flow__node").first();
    await expect(node).toBeVisible();
    const id = await node.getAttribute("data-id");
    const byId = canvas.locator(`.react-flow__node[data-id="${id}"]`);
    const position = () => byId.evaluate((element) => (element as HTMLElement).style.transform);
    const before = await position();

    // The designer sits below the fold, and a mouse moved to coordinates outside
    // the viewport reaches nothing -- the first run of this test dragged thin air.
    await byId.scrollIntoViewIfNeeded();
    const box = await byId.boundingBox();
    await page.mouse.move(box!.x + box!.width / 2, box!.y + box!.height / 2);
    await page.mouse.down();
    await page.mouse.move(box!.x + box!.width / 2 + 120, box!.y + box!.height / 2 + 60, { steps: 12 });
    await page.mouse.up();
    await expect.poll(position, { message: "the drag did not move the object type" }).not.toBe(before);
    const moved = await position();

    await page.reload();
    await expect.poll(position, { message: "the designer threw the arrangement away on reload" }).toBe(moved);
  });
});

/**
 * Resetting the panes touches only the panes. V9 of the goal and the research's
 * fourth evaluation scenario: move a pane, then reset, and check that the
 * artifact and anything typed but not yet sent are exactly as they were.
 */
test.describe("resetting the panes touches only the panes", () => {
  test.beforeEach(async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-1280", "Runs once; the fixtures are stateful.");
    await page.goto("/workspace/pipeline");
    await page.getByRole("button", { name: "Reset panes" }).click();
    await page.getByRole("button", { name: "New pipeline" }).click();
    await expect(page.getByText(/Pipeline draft created/)).toBeVisible();
    await page.getByRole("button", { name: "Input Dataset input" }).click();
    await page.locator(".pipeline-canvas").getByRole("button", { name: /^Add / }).click();
    await expect(page.locator(".pipeline-canvas .pipeline-node")).toHaveCount(1);
    await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {});
  });

  test("Reset panes leaves the graph and unsent input exactly as they were", async ({ page }) => {
    const node = page.locator(".pipeline-canvas .pipeline-node").first();
    await node.click();
    const label = page.locator(".pipeline-node-config").getByLabel("Node label");
    await expect(label, "the selected node's configuration is not showing").toBeVisible();
    const slotOfOutputs = () => page.locator(".pane").filter({ hasText: "Execution Policy" }).first()
      .evaluate((element) => element.closest(".pane-slot")?.getAttribute("data-slot") || "");

    // Typed first, then the pane moved. Measured before V9: a pane moved to
    // another slot is a new parent, React remounts what is inside it, and the
    // node form's local state went with it -- so a plain move lost the draft, and
    // the reset below was only the second way to lose it.
    const unsent = `Typed but not saved ${Date.now()}`;
    await label.fill(unsent);
    await paneControls(page, "Outputs");
    await page.getByLabel("Move Outputs to").selectOption("bottom");
    await expect.poll(slotOfOutputs).toBe("bottom");
    await expect(page.locator(".pipeline-node-config").getByLabel("Node label"),
                 "moving the pane threw away input that had not been sent")
      .toHaveValue(unsent);
    const positionBefore = await node.evaluate((element) => `${(element as HTMLElement).style.left},${(element as HTMLElement).style.top}`);
    const writes: string[] = [];
    page.on("request", (request) => {
      if (request.method() !== "GET") writes.push(`${request.method()} ${new URL(request.url()).pathname}`);
    });

    await page.getByRole("button", { name: "Reset panes" }).click();

    await expect.poll(slotOfOutputs, { message: "Reset panes did not put the Outputs pane back" })
      .toBe("right");
    await expect(page.locator(".pipeline-node-config").getByLabel("Node label"),
                 "resetting the panes threw away input that had not been sent")
      .toHaveValue(unsent);
    expect(await node.evaluate((element) => `${(element as HTMLElement).style.left},${(element as HTMLElement).style.top}`),
           "resetting the panes moved a node in the graph")
      .toBe(positionBefore);
    expect(writes, "resetting the panes sent a write to the server").toEqual([]);
  });
});

/**
 * A pane that moves keeps what was typed into it. V12 of the goal. V9 kept the
 * pipeline node form's draft above the panes and recorded that any other component
 * holding unsaved state in a pane would lose it on a move the same way: a pane moved
 * to another slot is a new parent, and React remounts what it holds. The census of
 * the three pane screens found three more -- the ontology manager's package form, the
 * artifact review compose boxes and the AIP Logic agent runtime -- and two search
 * boxes wired to nothing.
 */
test.describe("a pane that moves keeps what was typed into it", () => {
  test.beforeEach(async ({}, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-1280", "Runs once; the fixtures are stateful.");
  });

  const settled = async (response: { ok(): boolean; text(): Promise<string> }, label: string) => {
    const text = await response.text();
    expect(response.ok(), `${label}: ${text.slice(0, 500)}`).toBeTruthy();
    return JSON.parse(text || "null");
  };

  const slotHolding = (page: Page, inside: string) => page.locator(".pane").filter({ has: page.locator(inside) }).first()
    .evaluate((element) => element.closest(".pane-slot")?.getAttribute("data-slot") || "");

  /**
   * Two published packages in the default project, so the install form shows. With
   * nothing chosen the panel selects the first package the list returns, so the test
   * picks the other one: a choice that survived is then told apart from a default
   * that happened to agree with it.
   */
  async function packageFixture(page: Page) {
    const suffix = Date.now();
    const typeId = `moved_pane_type_${suffix}`;
    await settled(await page.request.post("/object-types", { data: {
      id: typeId, display_name: `Moved pane type ${suffix}`, description: "V12 package fixture",
      properties: { asset_id: { type: "string", required: true } }
    } }), "object type");
    const { project } = await settled(await page.request.post("/tenancy/bootstrap", { data: {} }), "tenancy bootstrap");
    const ids = [`moved_pane_a_${suffix}`, `moved_pane_b_${suffix}`];
    for (const id of ids) {
      await settled(await page.request.post("/ontology-packages", { data: {
        id, organization_id: project.organization_id, owning_project_id: project.id, display_name: id
      } }), `package ${id}`);
      const captured = await settled(await page.request.post(`/ontology-packages/${id}/versions/capture`, { data: {
        version: "1.0.0", object_type_ids: [typeId]
      } }), `capture ${id}`);
      await settled(await page.request.post(`/ontology-packages/${id}/versions/1.0.0/publish`, { data: {
        expected_checksum: captured.checksum
      } }), `publish ${id}`);
    }
    const listed: Array<{ id: string }> = await settled(await page.request.get("/ontology-packages"), "package list");
    const picked = ids.find((id) => id !== listed[0]?.id) as string;
    return { picked, suffix };
  }

  /** Opens the ontology manager, picks the package and types into its form. */
  async function typeIntoPackageForm(page: Page, picked: string, namespace: string) {
    await page.goto("/workspace/ontology");
    await page.getByRole("button", { name: "Reset panes" }).click();
    const panel = page.locator(".ontology-package-panel");
    await panel.getByLabel("Package").selectOption(picked);
    await expect(panel.getByLabel("Namespace"), "the picked package's install form did not load").toBeVisible();
    await panel.getByLabel("New version").fill("2.7.1");
    await panel.getByLabel("Namespace").fill(namespace);
    return panel;
  }

  test("the package form keeps its choices and typing when the Resources pane moves", async ({ page }) => {
    const { picked, suffix } = await packageFixture(page);
    const panel = await typeIntoPackageForm(page, picked, `moved_${suffix}`);

    // `Move to…`, the single-pointer way to move a pane.
    await paneControls(page, "Resources");
    await page.getByLabel("Move Resources to").selectOption("right");
    await expect.poll(() => slotHolding(page, ".ontology-package-panel")).toBe("right");
    // The selects render only once the remounted panel's reload has landed, so every
    // value below is read after any default that reload would have put back.
    await expect(panel.getByLabel("New version"), "moving the pane threw away a version that had not been sent")
      .toHaveValue("2.7.1");
    await expect(panel.getByLabel("Namespace"), "moving the pane threw away a namespace that had not been sent")
      .toHaveValue(`moved_${suffix}`);
    await expect(panel.getByLabel("Package"), "moving the pane put back the default package")
      .toHaveValue(picked);

    // `Create a package` is the empty string and a real choice. A reload after the
    // remount must not read it as no choice and select the first package again.
    await panel.getByLabel("Package").selectOption("");
    await paneControls(page, "Resources");
    await page.getByLabel("Move Resources to").selectOption("left");
    await expect.poll(() => slotHolding(page, ".ontology-package-panel")).toBe("left");
    await expect(panel.getByLabel("Package"), "moving the pane took back the choice to create a package")
      .toHaveValue("");
    await expect(panel.getByRole("button", { name: "Create from selected type" })).toBeVisible();
  });

  test("the package form keeps its typing when the Resources pane is dragged to another slot", async ({ page }) => {
    const { picked, suffix } = await packageFixture(page);
    const panel = await typeIntoPackageForm(page, picked, `dragged_${suffix}`);

    // A real drag by the grip onto the centre slot, proven over it before release.
    // Not the right slot: empty, it is a 14px strip flush with `.workspace`'s right
    // edge, inside dnd-kit's auto-scroll zone (the outer 20% of the scroll container).
    // Carried that far, the pane's transform overflows `.workspace`, the workspace
    // scrolls right under a still pointer, and dnd-kit's scroll-adjusted slot rects
    // leave the pointer within a few ticks -- the drop lands on nothing.
    const grip = page.getByRole("button", { name: "Reorder Resources", exact: true });
    await grip.scrollIntoViewIfNeeded();
    const from = await grip.boundingBox();
    const onto = await page.locator(".pane-slot-center").boundingBox();
    expect(from && onto, "the grip or the centre slot has no layout").toBeTruthy();
    const startX = from!.x + from!.width / 2;
    const startY = from!.y + from!.height / 2;
    const targetX = onto!.x + onto!.width / 2;
    const targetY = Math.min(Math.max(startY + 40, onto!.y + 20, 240), onto!.y + onto!.height - 20);
    await page.mouse.move(startX, startY);
    await page.mouse.down();
    for (let step = 1; step <= 12; step += 1) {
      await page.mouse.move(startX + ((targetX - startX) * step) / 12, startY + ((targetY - startY) * step) / 12);
      await page.waitForTimeout(16);
    }
    await expect(page.locator("[id^='DndLiveRegion']").filter({ hasText: /pane:/ }),
                 "the drag was not over the centre slot when it was released")
      .toContainText(/moved over droppable area slot:center/);
    await page.mouse.up();

    await expect.poll(() => slotHolding(page, ".ontology-package-panel"), { message: "the drag did not move the pane" })
      .toBe("center");
    await expect(panel.getByLabel("New version"), "dragging the pane threw away a version that had not been sent")
      .toHaveValue("2.7.1");
    await expect(panel.getByLabel("Namespace"), "dragging the pane threw away a namespace that had not been sent")
      .toHaveValue(`dragged_${suffix}`);
    await expect(panel.getByLabel("Package"), "dragging the pane put back the default package")
      .toHaveValue(picked);
  });

  test("an unsent review comment and proposal title survive the Inspector moving", async ({ page }) => {
    await page.goto("/workspace/workshop");
    const create = page.getByRole("button", { name: "Create draft" });
    await expect(create.or(page.locator(".visual-builder-shell")).first()).toBeVisible();
    if (await create.isVisible()) await create.click();
    const review = page.locator(".artifact-review-panel");
    await expect(review, "the Inspector's review panel did not render").toBeVisible();
    await page.getByRole("button", { name: "Reset panes" }).click();
    const suffix = Date.now();
    await review.getByPlaceholder("Add review context or a question").fill(`Unsent comment ${suffix}`);
    await review.getByRole("tab", { name: /Proposals/ }).click();
    await review.getByPlaceholder("Proposal title").fill(`Unsent proposal ${suffix}`);

    await paneControls(page, "Inspector");
    await page.getByLabel("Move Inspector to").selectOption("bottom");
    await expect.poll(() => slotHolding(page, ".artifact-review-panel")).toBe("bottom");

    // The tab is where the person was looking, and starts again on Comments; what was
    // written under each tab does not.
    await review.getByRole("tab", { name: /Proposals/ }).click();
    await expect(review.getByPlaceholder("Proposal title"), "moving the pane threw away a proposal title that had not been sent")
      .toHaveValue(`Unsent proposal ${suffix}`);
    await review.getByRole("tab", { name: /Comments/ }).click();
    await expect(review.getByPlaceholder("Add review context or a question"), "moving the pane threw away a comment that had not been sent")
      .toHaveValue(`Unsent comment ${suffix}`);
  });

  test("an unsent agent instruction and its parameters survive Run results moving", async ({ page }) => {
    const suffix = Date.now();
    const agentId = `moved_pane_agent_${suffix}`;
    await settled(await page.request.post("/agents", { data: { id: agentId, display_name: `Moved pane agent ${suffix}` } }), "agent");
    await page.goto("/workspace/aip");
    const create = page.getByRole("button", { name: "Create draft" });
    await expect(create.or(page.locator(".visual-builder-shell")).first()).toBeVisible();
    if (await create.isVisible()) await create.click();
    const runtime = page.locator(".agent-runtime-panel");
    await expect(runtime, "the agent runtime did not render in Run results").toBeVisible();
    await page.getByRole("button", { name: "Reset panes" }).click();
    await runtime.getByLabel("Agent", { exact: true }).selectOption(agentId);
    await runtime.getByLabel("Execution mode").selectOption("single");
    await runtime.getByLabel("Instruction").fill(`Unsent instruction ${suffix}`);
    await runtime.getByRole("button", { name: "Add parameter" }).click();
    await runtime.getByLabel("Parameter 1 name").fill("incident_id");
    await runtime.getByLabel("Parameter 1 value").fill(`incident_${suffix}`);

    await paneControls(page, "Run results");
    await page.getByLabel("Move Run results to").selectOption("right");
    await expect.poll(() => slotHolding(page, ".agent-runtime-panel")).toBe("right");
    await expect(runtime.getByLabel("Instruction"), "moving the pane threw away an instruction that had not been run")
      .toHaveValue(`Unsent instruction ${suffix}`);
    await expect(runtime.getByLabel("Parameter 1 value"), "moving the pane threw away a parameter that had not been run")
      .toHaveValue(`incident_${suffix}`);
    await expect(runtime.getByLabel("Execution mode"), "moving the pane put back the default execution mode")
      .toHaveValue("single");
    await expect(runtime.getByLabel("Agent", { exact: true }), "moving the pane put back the default agent")
      .toHaveValue(agentId);
  });

  test("an agent run in flight lands in Run results after it moves, and its answer survives the next move", async ({ page }) => {
    // The run lived in the panel: the job, its stages, the result and whether it was running.
    // A move remounted the panel empty, and a run still in flight finished into the panel that
    // had gone. The worker's request is held here so the move happens mid-run, not after.
    const suffix = Date.now();
    const agentId = `moved_run_agent_${suffix}`;
    await settled(await page.request.post("/agents", { data: { id: agentId, display_name: `Moved run agent ${suffix}` } }), "agent");
    let release!: () => void;
    const held = new Promise<void>((resolve) => { release = resolve; });
    await page.route((url) => url.pathname === "/aip/agents/workers/run-next", async (route) => {
      await held;
      await route.continue();
    });
    await page.goto("/workspace/aip");
    const create = page.getByRole("button", { name: "Create draft" });
    await expect(create.or(page.locator(".visual-builder-shell")).first()).toBeVisible();
    if (await create.isVisible()) await create.click();
    const runtime = page.locator(".agent-runtime-panel");
    await expect(runtime, "the agent runtime did not render in Run results").toBeVisible();
    await page.getByRole("button", { name: "Reset panes" }).click();
    await runtime.getByLabel("Agent", { exact: true }).selectOption(agentId);
    await runtime.getByLabel("Execution mode").selectOption("single");
    await runtime.getByLabel("Instruction").fill(`Moved run ${suffix}`);
    await runtime.getByRole("button", { name: "Run agent" }).click();
    await expect(runtime.getByRole("button", { name: "Running" }), "the run did not start").toBeVisible();

    await paneControls(page, "Run results");
    await page.getByLabel("Move Run results to").selectOption("right");
    await expect.poll(() => slotHolding(page, ".agent-runtime-panel")).toBe("right");
    await expect(runtime.getByRole("button", { name: "Running" }), "moving the pane forgot a run that was still going")
      .toBeVisible();
    await expect(runtime.locator(".agent-job-state"), "moving the pane dropped the running job's state").toBeVisible();

    release();
    const answer = runtime.locator(".agent-run-evidence .agent-answer p");
    await expect(answer, "the run finished into the panel the move replaced, and the moved pane never showed it")
      .not.toBeEmpty({ timeout: 20_000 });
    const said = await answer.textContent();
    await expect(runtime.getByRole("button", { name: "Run agent" })).toBeVisible();

    await paneControls(page, "Run results");
    await page.getByLabel("Move Run results to").selectOption("left");
    await expect.poll(() => slotHolding(page, ".agent-runtime-panel")).toBe("left");
    await expect(answer, "moving the pane threw away a finished run's answer").toHaveText(said || "");
    await expect(runtime.locator(".agent-job-state"), "moving the pane threw away a finished run's job").toBeVisible();
  });

  test("the object type search narrows the Resources list, and says when nothing matches", async ({ page }) => {
    // Discover lists every object type the person can see, uncapped. The box above it
    // had no value, no handler and no form: it took text and did nothing with it.
    const suffix = Date.now();
    for (const [id, name] of [[`searchable_type_${suffix}`, `Searchable ${suffix}`], [`unrelated_type_${suffix}`, `Unrelated ${suffix}`]]) {
      await settled(await page.request.post("/object-types", { data: {
        id, display_name: name, properties: { name: { type: "string" } }
      } }), `object type ${id}`);
    }
    await page.goto("/workspace/ontology");
    const discover = page.locator(".manager-resource-nav .panel")
      .filter({ has: page.getByRole("heading", { name: "Discover", exact: true }) });
    const rows = discover.locator(".resource-row");
    await expect(rows.filter({ hasText: `Searchable ${suffix}` })).toHaveCount(1);
    await expect(rows.filter({ hasText: `Unrelated ${suffix}` })).toHaveCount(1);
    const search = page.getByLabel("Search object types");

    await search.fill(`Searchable ${suffix}`);
    await expect(rows, "the search did not narrow the object types to the one that matches").toHaveCount(1);
    await expect(rows.first()).toContainText(`Searchable ${suffix}`);
    await expect(discover.getByRole("note"), "a narrowed list reads as every object type")
      .toHaveText(/^Showing 1 of [\d,]+ object types$/);

    await search.fill(`unrelated_type_${suffix}`);
    await expect(rows, "the search did not match an object type by its id").toHaveCount(1);
    await expect(rows.first()).toContainText(`Unrelated ${suffix}`);

    await search.fill(`No such type ${suffix}`);
    await expect(rows, "a search that matches nothing still lists object types").toHaveCount(0);
    await expect(discover, "a search that matched nothing left the list empty without saying so")
      .toContainText(`No object type matches "No such type ${suffix}"`);
  });

  test("the Outputs pane holds no search box wired to nothing", async ({ page }) => {
    // Pipeline Outputs lists the graph's output nodes and the five builds the canvas
    // loads, so a search there would read as a search of every build. It searched
    // nothing, and lost its text whenever the pane moved.
    await page.goto("/workspace/pipeline");
    const outputs = page.locator(".output-rail");
    await expect(outputs, "the Outputs pane did not render").toBeVisible();
    await expect(outputs.locator("input[placeholder^='Search']"), "a search box wired to nothing is back in the Outputs pane")
      .toHaveCount(0);
  });
});

/**
 * A collapsed pane keeps what it holds. V13 of the goal. V12 recorded that a collapse
 * unmounted a pane's contents the way a move does, so an expand mounted them afresh and
 * anything a component kept for itself started again. The review panel's tab is such a
 * thing: V12 left it to start again on a move, because it is where a person was looking.
 * A collapse is not a move -- the pane has not gone anywhere -- and now keeps it.
 */
test.describe("a collapsed pane keeps what it holds", () => {
  test.beforeEach(async ({}, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-1280", "Runs once; one layout is enough to hold a collapse.");
  });

  test("the review panel's tab survives the Inspector collapsing and expanding", async ({ page }) => {
    await page.goto("/workspace/workshop");
    const create = page.getByRole("button", { name: "Create draft" });
    await expect(create.or(page.locator(".visual-builder-shell")).first()).toBeVisible();
    if (await create.isVisible()) await create.click();
    const review = page.locator(".artifact-review-panel");
    await expect(review, "the Inspector's review panel did not render").toBeVisible();
    await page.getByRole("button", { name: "Reset panes" }).click();
    const proposals = review.getByRole("tab", { name: /Proposals/ });
    await proposals.click();
    await expect(proposals).toHaveAttribute("aria-selected", "true");

    await paneControls(page, "Inspector");
    const collapse = page.getByRole("button", { name: "Collapse Inspector" });
    await expect(collapse, "the collapse control does not say its pane is open").toHaveAttribute("aria-expanded", "true");
    await collapse.click();
    await expect(review, "a collapsed pane still shows what it holds").toBeHidden();
    await expect(page.getByRole("tab", { name: /Proposals/ }), "a collapsed pane's contents are still in the accessibility tree")
      .toHaveCount(0);

    await paneControls(page, "Inspector");
    const expand = page.getByRole("button", { name: "Expand Inspector" });
    await expect(expand, "the expand control does not say its pane is closed").toHaveAttribute("aria-expanded", "false");
    await expand.click();
    await expect(review).toBeVisible();
    await expect(proposals, "expanding the pane mounted the review panel afresh, back on Comments")
      .toHaveAttribute("aria-selected", "true");
  });
});

/**
 * A pipeline node picked up on a canvas already scrolled sideways. V10 of the goal,
 * found while V8 was verified: the node was displaced by the canvas's scroll
 * offset before any key was pressed, and the drop committed it -- scrolled 103px
 * at zoom 0.86, a pick-up and four presses right landed the node 3.5px to the left.
 */
test.describe("a node picked up on a scrolled canvas stays where it was", () => {
  test.beforeEach(async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-1280", "Runs once; the fixtures are stateful.");
    await page.goto("/workspace/pipeline");
    await page.getByRole("button", { name: "Reset panes" }).click();
    await page.getByRole("button", { name: "New pipeline" }).click();
    await expect(page.getByText(/Pipeline draft created/)).toBeVisible();
    await page.getByRole("button", { name: "Input Dataset input" }).click();
    await page.locator(".pipeline-canvas").getByRole("button", { name: /^Add / }).click();
    await expect(page.locator(".pipeline-canvas .pipeline-node")).toHaveCount(1);
    await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {});
  });

  async function scrollCanvas(page: Page, px: number) {
    const canvas = page.locator(".pipeline-canvas");
    await canvas.evaluate((element, left) => { element.scrollLeft = left; }, px);
    await expect.poll(() => canvas.evaluate((element) => element.scrollLeft),
                      { message: "the canvas could not be scrolled sideways" }).toBeGreaterThanOrEqual(px - 1);
    await page.waitForTimeout(200);
  }

  const leftOf = (page: Page) => page.locator(".pipeline-canvas .pipeline-node").first()
    .evaluate((element) => Number.parseFloat((element as HTMLElement).style.left) || 0);

  test("a pick-up and drop with no movement on a scrolled canvas leaves the node in place", async ({ page }) => {
    await scrollCanvas(page, 100);
    const node = page.locator(".pipeline-canvas .pipeline-node").first();
    const before = await leftOf(page);
    const writes: string[] = [];
    page.on("request", (request) => {
      if (request.method() !== "GET") writes.push(`${request.method()} ${new URL(request.url()).pathname}`);
    });

    await node.focus();
    const announcement = page.locator("[id^='DndLiveRegion']").filter({ hasText: /node:/ });
    await page.keyboard.press("Space");
    await expect(announcement, "the node drag never started").toContainText(/draggable item/i);
    await page.waitForTimeout(200);
    const onPickUp = await node.evaluate((element) => (element as HTMLElement).style.transform);
    await page.keyboard.press("Space");
    await page.waitForTimeout(800);

    expect(await leftOf(page),
           `picking the node up and putting it straight down moved it; its transform on pick-up was "${onPickUp}"`)
      .toBe(before);
    expect(writes, "a drop that moved nothing saved a position").toEqual([]);
  });

  test("an arrow key to the right on a scrolled canvas moves the node right", async ({ page }) => {
    await scrollCanvas(page, 100);
    const node = page.locator(".pipeline-canvas .pipeline-node").first();
    const before = await leftOf(page);

    await node.focus();
    const announcement = page.locator("[id^='DndLiveRegion']").filter({ hasText: /node:/ });
    await page.keyboard.press("Space");
    await expect(announcement, "the node drag never started").toContainText(/draggable item/i);
    await page.keyboard.press("ArrowRight");
    await page.waitForTimeout(150);
    await page.keyboard.press("Space");
    await expect(page.getByText(/Saved .+ position\./), "the move was not committed").toBeVisible();

    expect(await leftOf(page) - before, "one arrow key to the right did not move the node to the right")
      .toBeGreaterThan(10);
  });
});
