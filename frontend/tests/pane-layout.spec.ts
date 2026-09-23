import { expect, test, type Page } from "@playwright/test";

/**
 * Panes a person can rearrange, operated the way a person without a mouse would.
 *
 * M2 of `GOAL_PANES_2026-09-11.md`. Before this, `oms/audit_pane_layout.py`
 * counted 21 pane regions across 13 screens and **0** that could be moved,
 * collapsed or hidden by the person using them: every one was a fixed CSS grid
 * track decided at build time.
 *
 * Everything below is `locator.tap()` and native selects on a 390×844 touch
 * viewport. Never a drag. The grip exists and is tested by the drag gate; what
 * is proven here is the other half, which is the half that decides whether the
 * feature exists for anyone not holding a mouse.
 */
test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

const SCREEN = "/workspace/pipeline";
const LIBRARY = "Add data / transforms";

test.describe("panes rearrange without a drag", () => {
  test.beforeEach(async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-1280",
              "Runs once; this file sets its own viewport and touch emulation.");
    await page.goto(SCREEN);
    // Each test starts from the declared layout rather than whatever the last
    // one stored, because a layout that survives is the point and would
    // otherwise leak between tests.
    await page.getByRole("button", { name: "Reset panes" }).tap();
  });

  test("a pane moves to another slot without a drag", async ({ page }) => {
    const pane = page.locator(".pane").filter({ hasText: LIBRARY }).first();
    await expect(pane).toBeVisible();
    const slotOf = () => pane.evaluate((el) =>
      el.closest(".pane-slot")?.getAttribute("data-slot") || "");
    expect(await slotOf(), "the library does not start on the left").toBe("left");

    await page.getByLabel(`Move ${LIBRARY} to`).selectOption("right");

    await expect.poll(slotOf, { message: "choosing a slot did not move the pane" })
      .toBe("right");
  });

  test("a moved pane is still there after a reload", async ({ page }) => {
    await page.getByLabel(`Move ${LIBRARY} to`).selectOption("bottom");
    const slotOf = () => page.locator(".pane").filter({ hasText: LIBRARY }).first()
      .evaluate((el) => el.closest(".pane-slot")?.getAttribute("data-slot") || "");
    await expect.poll(slotOf).toBe("bottom");

    await page.reload();

    await expect.poll(slotOf, { message: "the layout did not survive a reload" })
      .toBe("bottom");
  });

  test("a hidden pane can always be brought back", async ({ page }) => {
    const pane = page.locator(".pane").filter({ hasText: LIBRARY });
    await expect(pane).toHaveCount(1);

    await page.getByRole("button", { name: `Hide ${LIBRARY}` }).tap();
    await expect(pane, "the pane did not go away").toHaveCount(0);

    // Nothing can be lost: the Panes menu lists what is hidden, so a pane put
    // away is always one control from coming back. A hide with no way back is
    // how a person loses a feature permanently by tapping once.
    const menu = page.getByLabel("Panes");
    await expect(menu).toContainText("1 hidden");
    await menu.selectOption({ label: `Show ${LIBRARY}` });
    await expect(pane, "the Panes menu did not bring it back").toHaveCount(1);
  });

  test("the anchored canvas offers no way to hide itself", async ({ page }) => {
    // A pipeline builder with the pipeline put away is not a layout, it is a
    // dead end. The canvas is anchored: it may be collapsed and resized around,
    // never moved or hidden, and the controls that would do either are absent
    // rather than disabled.
    await expect(page.locator(".pane").filter({ hasText: "Pipeline" }).first()).toBeVisible();
    await expect(page.getByRole("button", { name: "Hide Pipeline" })).toHaveCount(0);
    await expect(page.getByLabel("Move Pipeline to")).toHaveCount(0);
    await expect(page.getByRole("button", { name: /Collapse Pipeline/ })).toHaveCount(1);
  });

  test("a pane resizes from the keyboard and survives a reload", async ({ browser }) => {
    // A desktop context of its own. Below 700px the slots stack and the splitter
    // is `display: none` -- there is no boundary to drag when panes are in one
    // column -- so it is absent from the accessibility tree at this file's touch
    // viewport, which is correct and is why this test does not use it.
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    const page = await context.newPage();
    try {
    await page.goto(SCREEN);
    await page.getByRole("button", { name: "Reset panes" }).click();

    // Asserting on the stored size, not on a bounding box. `GOAL_DRAG` L8 is the
    // reason: a keyboard test there read a node's bounding box, an arrow key
    // scrolled the container rather than moving the node, and the test passed
    // against a build with its own wiring deleted. A box is what the layout
    // engine did; the stored number is what the control changed.
    const splitter = page.getByRole("separator", { name: "Resize left pane" });
    await expect(splitter).toHaveCount(1);
    const before = Number(await splitter.getAttribute("aria-valuenow"));
    expect(before, "the splitter reports no width").toBeGreaterThan(0);

    await splitter.focus();
    await expect(splitter).toBeFocused();
    for (let step = 0; step < 3; step += 1) {
      await page.keyboard.press("ArrowRight");
      await page.waitForTimeout(40);
    }

    const widened = Number(await splitter.getAttribute("aria-valuenow"));
    expect(widened, "arrow keys did not resize the pane").toBeGreaterThan(before);

    const stored = async () => {
      const raw = await page.evaluate(() =>
        window.localStorage.getItem("ontology.panes.pipeline"));
      return raw ? (JSON.parse(raw).sizes || {}).left : undefined;
    };
    expect(await stored(), "the size was not written to the layout").toBe(widened);

    await page.reload();
    await expect
      .poll(async () => Number(await page.getByRole("separator", { name: "Resize left pane" })
        .getAttribute("aria-valuenow")),
        { message: "the resized pane did not come back the same width" })
      .toBe(widened);
    } finally {
      await context.close();
    }
  });

  test("a resized pane is put back by Reset panes", async ({ browser }) => {
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    const page = await context.newPage();
    try {
      await page.goto(SCREEN);
      const splitter = page.getByRole("separator", { name: "Resize left pane" });
      await splitter.focus();
      await page.keyboard.press("End");
      await expect.poll(async () => Number(await splitter.getAttribute("aria-valuenow")))
        .toBeGreaterThan(500);

      await page.getByRole("button", { name: "Reset panes" }).click();

      await expect
        .poll(async () => Number(await splitter.getAttribute("aria-valuenow")),
              { message: "Reset panes left the slot at the width it was dragged to" })
        .toBeLessThan(500);
    } finally {
      await context.close();
    }
  });

  test("Reset panes puts every pane back where it was declared", async ({ page }) => {
    await page.getByLabel(`Move ${LIBRARY} to`).selectOption("right");
    const slotOf = () => page.locator(".pane").filter({ hasText: LIBRARY }).first()
      .evaluate((el) => el.closest(".pane-slot")?.getAttribute("data-slot") || "");
    await expect.poll(slotOf).toBe("right");

    await page.getByRole("button", { name: "Reset panes" }).tap();

    await expect.poll(slotOf, { message: "Reset panes left the pane where it was moved" })
      .toBe("left");
  });
});

/**
 * The artifact canvases on panes. M7 of `GOAL_PANES_2026-09-11.md`: Workshop, AIP
 * Logic, Investigations and Entity Resolution share one screen component, which
 * was a fixed three-column grid. Same touch viewport as the rest of this file, and
 * the same rule: operated without a drag.
 */
test.describe("an artifact canvas's panes rearrange without a drag", () => {
  const LIBRARY_PANE = "Node library";

  test.beforeEach(async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-1280",
              "Runs once; this file sets its own viewport and touch emulation.");
    await page.goto("/workspace/workshop");
    const draft = page.getByRole("button", { name: "Create draft" });
    await expect(draft.or(page.locator(".visual-builder-shell")).first()).toBeVisible();
    if (await draft.isVisible()) await draft.tap();
    await expect(page.locator(".node-library-list button").first()).toBeVisible();
    await page.getByRole("button", { name: "Reset panes" }).tap();
  });

  test("the node library moves to another slot and is still there after a reload", async ({ page }) => {
    const slotOf = () => page.locator(".pane").filter({ has: page.getByLabel("Search node library") }).first()
      .evaluate((el) => el.closest(".pane-slot")?.getAttribute("data-slot") || "");
    expect(await slotOf(), "the node library does not start on the left").toBe("left");

    await page.getByLabel(`Move ${LIBRARY_PANE} to`).selectOption("right");
    await expect.poll(slotOf, { message: "choosing a slot did not move the library" }).toBe("right");

    await page.reload();
    await expect(page.locator(".node-library-list button").first()).toBeVisible();
    await expect.poll(slotOf, { message: "the artifact canvas layout did not survive a reload" }).toBe("right");
  });

  test("the artifact canvas is anchored and offers no way to hide itself", async ({ page }) => {
    await expect(page.locator(".visual-flow-canvas"), "the canvas is not drawn inside its pane").toBeVisible();
    await expect(page.getByRole("button", { name: "Hide Canvas" })).toHaveCount(0);
    await expect(page.getByLabel("Move Canvas to")).toHaveCount(0);
  });
});

/**
 * The ontology manager on panes: the second half of M7. It was a fixed grid of a
 * walkthrough rail, a resource list and the object type surface.
 */
test.describe("the ontology manager's panes rearrange without a drag", () => {
  test.beforeEach(async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-1280",
              "Runs once; this file sets its own viewport and touch emulation.");
    await page.goto("/workspace/ontology");
    await expect(page.locator(".manager-resource-nav")).toBeVisible();
    await page.getByRole("button", { name: "Reset panes" }).tap();
  });

  test("the resources pane moves to another slot and is still there after a reload", async ({ page }) => {
    const slotOf = () => page.locator(".pane").filter({ has: page.locator(".manager-resource-nav") }).first()
      .evaluate((el) => el.closest(".pane-slot")?.getAttribute("data-slot") || "");
    expect(await slotOf(), "the resource list does not start on the left").toBe("left");

    await page.getByLabel("Move Resources to").selectOption("right");
    await expect.poll(slotOf, { message: "choosing a slot did not move the resource list" }).toBe("right");

    await page.reload();
    await expect(page.locator(".manager-resource-nav")).toBeVisible();
    await expect.poll(slotOf, { message: "the ontology manager's layout did not survive a reload" }).toBe("right");
  });

  test("the object type surface is anchored and offers no way to hide itself", async ({ page }) => {
    await expect(page.locator(".manager-surface")).toBeVisible();
    await expect(page.getByRole("button", { name: "Hide Object type" })).toHaveCount(0);
    await expect(page.getByLabel("Move Object type to")).toHaveCount(0);
  });
});

test.describe("an empty side slot gives its width back", () => {
  test.beforeEach(async ({}, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-1280",
              "Runs once; needs the side-by-side layout, so it opens its own desktop context.");
  });

  test("moving the only pane out of a side slot widens the canvas", async ({ browser }) => {
    // Desktop, because below 700px the slots stack and have no width to give.
    // Measured before this: the ontology manager's empty right slot kept 228px
    // and the relationship designer clipped two of its six object types.
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    const page = await context.newPage();
    try {
      await page.goto("/workspace/pipeline");
      await page.getByRole("button", { name: "Reset panes" }).click();
      const canvasWidth = () => page.locator(".pane-slot-center").evaluate((el) => el.getBoundingClientRect().width);
      const before = await canvasWidth();

      // At 220px the Outputs pane keeps its controls behind `⋯` (S4 of GOAL_SHELL).
      await page.getByRole("button", { name: "Pane actions for Outputs" }).click();
      await page.getByLabel("Move Outputs to").selectOption("bottom");
      await expect.poll(() => page.locator(".pane-slot-right .pane").count()).toBe(0);

      const rightWidth = await page.locator(".pane-slot-right").evaluate((el) => el.getBoundingClientRect().width);
      expect(rightWidth, "the empty right slot still holds a column's width").toBeLessThan(30);
      await expect.poll(canvasWidth, { message: "the canvas did not get the empty slot's width back" })
        .toBeGreaterThan(before + 150);
    } finally {
      await context.close();
    }
  });
});

/**
 * A pane too narrow for its title and its controls. S4 of `GOAL_SHELL_2026-09-23.md`.
 *
 * At 220px the pipeline library's header held a grip, a collapse button, a
 * `Move to…` select and a hide button, and left `Add data / transforms` 51 of the
 * 125 pixels it needs. The three controls now sit behind one `⋯` button there,
 * and the grip stays outside it, because the grip is the drag.
 *
 * A tablet in landscape, touch and 1024 wide, because that is where a side pane is
 * narrow and a finger is what reaches for it. At 390x844, the viewport the rest of
 * this file uses, the panes stack full width and every title fits beside its
 * controls, so there is no menu there to tap.
 */
test.describe("a narrow pane's controls are one tap away", () => {
  test.use({ viewport: { width: 1024, height: 768 }, hasTouch: true, isMobile: false });
  const menu = (page: Page) => page.getByRole("button", { name: `Pane actions for ${LIBRARY}` });
  const slotOf = (page: Page) => page.locator(".pane").filter({ hasText: LIBRARY }).first()
    .evaluate((el) => el.closest(".pane-slot")?.getAttribute("data-slot") || "");

  test.beforeEach(async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-1280",
              "Runs once; this block sets its own tablet viewport and touch emulation.");
    await page.goto(SCREEN);
    await page.getByRole("button", { name: "Reset panes" }).tap();
  });

  test("a narrow pane's menu opens with a tap and moves the pane", async ({ page }) => {
    const title = page.locator(".pane").filter({ hasText: LIBRARY }).first().locator(".pane-header strong");
    await expect(title).toHaveText(LIBRARY);
    expect(await title.evaluate((el) => el.scrollWidth - el.clientWidth),
           "the title is still clipped beside its controls").toBe(0);
    // Behind the menu, not beside the title: the select is not on the page until
    // the menu opens, so it cannot be the thing squeezing the title.
    await expect(page.getByLabel(`Move ${LIBRARY} to`)).toHaveCount(0);
    await expect(page.getByRole("button", { name: `Reorder ${LIBRARY}` }),
                 "the grip went into the menu; it is the drag and stays in the header").toBeVisible();

    await menu(page).tap();
    await expect(menu(page)).toHaveAttribute("aria-expanded", "true");
    await page.getByLabel(`Move ${LIBRARY} to`).selectOption("right");

    await expect.poll(() => slotOf(page), { message: "moving the pane from its menu did not move it" })
      .toBe("right");
  });

  test("a narrow pane's menu is reached and left from the keyboard", async ({ page }) => {
    await menu(page).focus();
    await page.keyboard.press("Enter");
    const group = page.getByRole("group", { name: `${LIBRARY} pane actions` });
    await expect(group, "Enter on the menu button did not open it").toBeVisible();

    await page.keyboard.press("Tab");
    await expect(page.getByRole("button", { name: `Collapse ${LIBRARY}` }),
                 "the menu's first control is not the next stop after its button").toBeFocused();

    await page.keyboard.press("Escape");
    await expect(group, "Escape did not close the menu").toHaveCount(0);
    await expect(menu(page), "closing the menu lost the focus").toBeFocused();
    await expect(menu(page)).toHaveAttribute("aria-expanded", "false");
  });

  test("a pane its title crowds keeps its menu open, and the title whole", async ({ page }) => {
    // At 320 the library pane is 287px: over the 280 line, and still too narrow for
    // its title beside three controls. It takes the menu for the second reason, and
    // an open menu changes the pane's height, which measures it again. Measured
    // from the menu button alone, the controls would seem to fit, the menu would
    // close itself and the title would be clipped again.
    await page.setViewportSize({ width: 320, height: 700 });
    await page.reload();
    await expect(menu(page), "a crowded pane at 320 offers no menu").toBeVisible();
    await menu(page).tap();
    await expect(page.getByRole("group", { name: `${LIBRARY} pane actions` }),
                 "the menu closed itself when it opened").toBeVisible();
    await page.waitForTimeout(300);
    await expect(page.getByRole("group", { name: `${LIBRARY} pane actions` })).toBeVisible();
    const title = page.locator(".pane").filter({ hasText: LIBRARY }).first().locator(".pane-header strong");
    expect(await title.evaluate((el) => el.scrollWidth - el.clientWidth),
           "the title is clipped while the menu is open").toBe(0);
  });

  test("a narrow pane hides from its menu and the Panes list brings it back", async ({ page }) => {
    await menu(page).tap();
    await page.getByRole("button", { name: `Hide ${LIBRARY}` }).tap();
    await expect(page.locator(".pane").filter({ hasText: LIBRARY }), "hiding from the menu did nothing")
      .toHaveCount(0);
    await page.getByLabel("Panes").selectOption({ label: `Show ${LIBRARY}` });
    await expect(page.locator(".pane").filter({ hasText: LIBRARY })).toHaveCount(1);
  });
});
