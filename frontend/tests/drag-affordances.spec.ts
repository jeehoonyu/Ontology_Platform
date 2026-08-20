import { expect, test } from "@playwright/test";

/**
 * Every drag in the product, reached without a mouse.
 *
 * Four of these were native HTML5 `draggable` and a fifth was hand-rolled on raw
 * pointer events. All five now run on `@dnd-kit` through `components/dnd/DragKit`,
 * and `oms/audit_drag_affordances.py` refuses anything that leaves that path, so
 * the list here cannot quietly fall behind the source.
 *
 * Two different claims are proven below, and they are not interchangeable.
 *
 * **A control beside the drag.** A select beside each mapping target, `Up`/`Down`
 * on each property row, a library entry that is also a button. Those already
 * existed and nothing operated them, so a tidy-up could have deleted one and left
 * a workspace mouse-only with the suite green. These are `locator.tap()` on a
 * touch viewport -- never a drag, never a mouse click, and never
 * `page.touchscreen.tap(x, y)`, which dispatches touch without the click a
 * browser synthesises from it and so fails against a working button.
 *
 * **The drag itself, from a keyboard.** New, and the reason the migration was
 * worth doing. A pipeline node's position had no second control at all. The first
 * version of that test asserted on the node's bounding box and passed against a
 * build with the keyboard wiring *removed* -- an arrow key scrolls a container,
 * which moves the box without moving the node. It reads the committed position
 * now, and running it against that same broken build is what then exposed a
 * second bug: the shared sensors were passing `sortableKeyboardCoordinates` to
 * every context, and outside a `SortableContext` it returns nothing, so keyboard
 * dragging on both canvases was inert while every pointer drag worked.
 */
test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

test.describe("a drag is never the only way", () => {
  test.beforeEach(async ({}, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-1280",
              "Runs once; this file sets its own viewport and touch emulation.");
  });

  test("a source field maps onto a property without a drag", async ({ page }) => {
    const bootstrap = await page.request.post("/scenarios/asset-reliability/bootstrap",
                                              { data: {} });
    expect(bootstrap.ok(), "the scenario that provides datasets did not bootstrap").toBeTruthy();

    await page.goto("/workspace/ontology");
    const panel = page.locator(".ontology-mapping-panel");
    await expect(panel.getByRole("heading", { name: "Dataset to Ontology Mapping" }))
      .toBeVisible();

    // The instruction beside the field list must name the reachable path too. A
    // screen that says only "drag this" is a dead end for the reader holding a
    // phone, even when the select is right there.
    await panel.getByLabel("Source dataset").selectOption({ index: 1 });
    await panel.getByRole("button", { name: "Preview objects" }).tap();
    await expect(panel.getByText(/or pick it from that property's list/)).toBeVisible();

    const target = panel.locator(".mapping-target").first();
    await expect(target).toBeVisible();

    // The preview comes back with mappings the server already inferred, so this
    // asserts a *change* rather than a first mapping: pick an option the
    // property does not currently hold. The select is controlled from
    // `mappings`, so it can only end up holding the new field if `mapField` ran
    // -- the same function the drop handler calls. Had the tap done nothing, the
    // control would snap back to what it showed before.
    const chooser = target.locator("select");
    const current = await chooser.inputValue();
    const options = await chooser.locator("option").allTextContents();
    const field = options.find((value) => value !== "Not mapped" && value !== current);
    expect(field, "the property offers no second source field to move to").toBeTruthy();

    await chooser.selectOption({ label: field as string });
    await expect(chooser, "choosing a source field did not map the property")
      .toHaveValue(field as string);
    await expect(target).toHaveClass(/mapped/);
  });

  test("a property row reorders without a drag", async ({ page }) => {
    const suffix = Date.now();
    const displayName = `Reachable Asset ${suffix}`;
    const created = await page.request.post("/object-types", { data: {
      id: `reachable_asset_${suffix}`,
      display_name: displayName,
      description: "Browser evidence that reordering does not require a pointer drag",
      properties: {
        alpha_reading: { type: "string", required: true },
        beta_reading: { type: "string" },
        gamma_reading: { type: "string" }
      }
    } });
    expect(created.ok(), await created.text()).toBeTruthy();

    await page.goto("/workspace/ontology");
    await page.locator(".manager-resource-nav .resource-row")
      .filter({ hasText: displayName }).tap();
    // The rows are read-only until the editor is opened; the table above it
    // shows the order but offers no control that changes it.
    await page.getByRole("button", { name: "Edit fields" }).tap();

    const rows = page.locator(".property-field-list .property-field-row");
    await expect(rows.first()).toBeVisible();

    const names = async () => rows.evaluateAll((articles) =>
      articles.map((article) => article.querySelector("input")?.value || ""));
    const before = await names();
    expect(before.length, "the object type rendered no property rows")
      .toBeGreaterThanOrEqual(2);

    // The drag handle says "Drag to reorder". These buttons are the other way,
    // and until now nothing checked that they move anything.
    await page.getByRole("button", { name: `Move ${before[0]} down` }).tap();
    await expect
      .poll(names, { message: "Down did not move the first property past the second" })
      .toEqual([before[1], before[0], ...before.slice(2)]);
  });

  test("a library node reaches the canvas without a drag", async ({ page }) => {
    await page.goto("/workspace/workshop");

    // Wait for the workspace to settle before deciding which of the two states
    // it is in. Asking too early reads the loading state as "no draft button",
    // and the run then waits ten seconds for a library that was never coming.
    const draft = page.getByRole("button", { name: "Create draft" });
    const shell = page.locator(".visual-builder-shell");
    await expect(draft.or(shell).first()).toBeVisible();
    if (await draft.isVisible()) {
      await draft.tap();
    }
    const library = page.locator(".node-library-list button");
    await expect(library.first()).toBeVisible();

    const canvas = page.locator(".visual-flow-canvas");
    const before = await canvas.locator(".visual-node").count();

    await library.first().tap();

    await expect(canvas.locator(".visual-node"),
                 "tapping a library entry placed no node, so the canvas is drag-only")
      .toHaveCount(before + 1);
  });

  test("a pipeline node moves with the keyboard", async ({ page, browser }) => {
    // The capability the migration bought, and the reason it was worth doing.
    // Node positions were moved by `onPointerDown` and `setPointerCapture` --
    // hand-rolled, counted by no census, and with no other control anywhere. The
    // layout of a pipeline could not be changed without a mouse or a finger.
    //
    // A keyboard is not touch, so this one runs in its own desktop context
    // rather than the touch viewport this file otherwise uses.
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    const desktop = await context.newPage();
    try {
      await desktop.goto("/workspace/pipeline");
      await desktop.getByRole("button", { name: "New pipeline" }).click();
      await expect(desktop.getByText(/Pipeline draft created/)).toBeVisible();

      const canvas = desktop.locator(".pipeline-canvas");
      await desktop.getByRole("button", { name: "Input Dataset input" }).click();
      await canvas.getByRole("button", { name: /^Add / }).click();

      const node = canvas.locator(".pipeline-node").first();
      await expect(node).toBeVisible();
      // Creating the node is a server round-trip that bumps a refresh key, and
      // the workspace polls readiness besides. Starting the drag while either is
      // in flight loses the focus the keyboard sensor needs -- which is why this
      // passed alone and failed after other specs had put rows in the database.
      await desktop.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {});
      // The committed position, not the viewport box: an arrow key can scroll a
      // container, which moves the box without moving the node.
      const left = async () => Number.parseFloat(
        (await node.evaluate((element) => (element as HTMLElement).style.left)) || "0");
      const before = await left();

      // Focus the node, pick it up, walk it right, put it down. dnd-kit's
      // keyboard sensor activates on Space and moves in fixed steps.
      await node.focus();
      // Assert the focus rather than assume it. If a re-render steals it the
      // failure should say so, not report a node that did not move.
      await expect(node, "the node lost focus before the drag could start")
        .toBeFocused();
      await desktop.keyboard.press("Space");

      // Wait for the drag to have actually started before moving it. Sleeping
      // instead of synchronising is what made the first version of this flaky:
      // it passed alone and failed inside a full suite, because pressing arrows
      // before the sensor had picked the node up loses them entirely.
      //
      // dnd-kit announces each phase into a live region, so this is both the
      // synchronisation point and a check that a screen reader is told what
      // happened -- which the hand-rolled pointer drag never did.
      // Target dnd-kit's own region by id: the workspace has `role="status"`
      // strips of its own. And match any announcement rather than the pick-up
      // one specifically -- the node starts already over the canvas droppable,
      // so "Picked up" is replaced by "was moved over" before this can read it.
      const announcement = desktop.locator("[id^='DndLiveRegion']");
      await expect(announcement, "no live-region announcement, so the drag never started")
        .toContainText(/draggable item/i);

      for (let step = 0; step < 4; step += 1) {
        await desktop.keyboard.press("ArrowRight");
      }
      await desktop.keyboard.press("Space");
      await expect(announcement, "no drop was announced").toContainText(/dropped/i);

      await expect
        .poll(left, { message: "the node did not move, so its position is still mouse-only" })
        .toBeGreaterThan(before + 20);
    } finally {
      await context.close();
    }
  });

  test("the sortable field list reorders from touch", async ({ page }) => {
    // The one drag backed by a library rather than by hand. `@dnd-kit`'s pointer
    // sensor is supposed to make this work from a finger, and it did not: the
    // grip carried no `touch-action: none`, so the browser spent the gesture on
    // scrolling before the sensor saw a move. Measured, fixed in one line, and
    // now measured again -- the library being capable is not the same claim as
    // the product working.
    await page.goto("/workspace/workshop");
    const draft = page.getByRole("button", { name: "Create draft" });
    const shell = page.locator(".visual-builder-shell");
    await expect(draft.or(shell).first()).toBeVisible();
    if (await draft.isVisible()) {
      await draft.tap();
    }

    await page.locator(".node-library-list button").first().tap();
    const inspector = page.locator(".node-inspector-form");
    await expect(inspector).toBeVisible();

    const rows = inspector.locator(".config-field-row");
    while (await rows.count() < 2) {
      await inspector.getByRole("button", { name: "Add" }).tap();
    }
    // Every added row is labelled "Custom field", so the rows are told apart by
    // the value they hold rather than by their name.
    const valueOf = (index: number) =>
      rows.nth(index).locator("input, select, textarea").last();
    await valueOf(0).fill("first-before-the-drag");
    await valueOf(1).fill("second-before-the-drag");

    const grip = rows.nth(0).locator(".drag-grip");
    const from = await grip.boundingBox();
    const onto = await rows.nth(1).boundingBox();
    expect(from && onto, "the field rows have no layout to drag across").toBeTruthy();

    // `page.touchscreen` taps and does nothing else, so the gesture is dispatched
    // through CDP. These are real touch points: Chrome synthesises the pointer
    // events the sensor listens for, which a hand-fired `touchmove` would not.
    const cdp = await page.context().newCDPSession(page);
    const touch = (type: string, y?: number) => cdp.send("Input.dispatchTouchEvent", {
      type,
      touchPoints: y === undefined ? [] : [{ x: from!.x + from!.width / 2, y }],
    } as never);

    const startY = from!.y + from!.height / 2;
    const endY = onto!.y + onto!.height * 0.75;
    await touch("touchStart", startY);
    for (let step = 1; step <= 10; step += 1) {
      await touch("touchMove", startY + ((endY - startY) * step) / 10);
      await page.waitForTimeout(20);
    }
    await touch("touchEnd");

    await expect
      .poll(() => valueOf(0).inputValue(),
            { message: "a touch drag on the grip moved nothing; check `touch-action` on it" })
      .toBe("second-before-the-drag");
  });
});
