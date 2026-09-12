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
