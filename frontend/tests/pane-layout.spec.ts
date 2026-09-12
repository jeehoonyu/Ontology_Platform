import { expect, test } from "@playwright/test";

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
    await page.getByRole("button", { name: "Reset layout" }).tap();
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
    await page.getByRole("button", { name: "Reset layout" }).click();

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

  test("a resized pane is put back by Reset layout", async ({ browser }) => {
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    const page = await context.newPage();
    try {
      await page.goto(SCREEN);
      const splitter = page.getByRole("separator", { name: "Resize left pane" });
      await splitter.focus();
      await page.keyboard.press("End");
      await expect.poll(async () => Number(await splitter.getAttribute("aria-valuenow")))
        .toBeGreaterThan(500);

      await page.getByRole("button", { name: "Reset layout" }).click();

      await expect
        .poll(async () => Number(await splitter.getAttribute("aria-valuenow")),
              { message: "Reset layout left the slot at the width it was dragged to" })
        .toBeLessThan(500);
    } finally {
      await context.close();
    }
  });

  test("Reset layout puts every pane back where it was declared", async ({ page }) => {
    await page.getByLabel(`Move ${LIBRARY} to`).selectOption("right");
    const slotOf = () => page.locator(".pane").filter({ hasText: LIBRARY }).first()
      .evaluate((el) => el.closest(".pane-slot")?.getAttribute("data-slot") || "");
    await expect.poll(slotOf).toBe("right");

    await page.getByRole("button", { name: "Reset layout" }).tap();

    await expect.poll(slotOf, { message: "Reset layout left the pane where it was moved" })
      .toBe("left");
  });
});
