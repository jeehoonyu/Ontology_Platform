import { expect, test } from "@playwright/test";

/**
 * Controls that used to render and do nothing.
 *
 * N2 of `GOAL_HONEST_UI_2026-09-11.md`. `oms/audit_inert_controls.py` counted
 * **17 of 335** `<button>` and `<a>` elements in the frontend with no handler,
 * no `href`, no `type="submit"`, no spread that could supply one, and no
 * `disabled` to say they were unavailable. Fourteen of the seventeen had nothing
 * behind them and were deleted; the audit is the evidence for those, because a
 * deleted control cannot be tested.
 *
 * The three that had behaviour are here. The pipeline canvas drew `+`, `-` and
 * `Fit` over the graph, wired to nothing, while a working copy of the same three
 * sat in the document action row beside Deploy and Delete node -- so the obvious
 * place to zoom was the dead one and the working one was somewhere a person
 * looks for Save. Zoom is a viewport control and now lives on the viewport.
 *
 * This reads the stage's own transform rather than a node's bounding box.
 * `GOAL_DRAG` L8 is why: a box is what the layout engine did, and a test that
 * reads one passed against a build with its own wiring deleted. The transform is
 * the value the control writes.
 */
const SCREEN = "/workspace/pipeline";

const scaleOf = (page: import("@playwright/test").Page) =>
  page.locator(".canvas-stage").first().evaluate((element) => {
    const transform = (element as HTMLElement).style.transform;
    return Number(/scale\(([\d.]+)\)/.exec(transform)?.[1] ?? NaN);
  });

test.describe("every visible control acts", () => {
  test.beforeEach(async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-1280",
              "Runs once; the canvas controls are absent from the stacked layout.");
    await page.goto(SCREEN);
  });

  test("the canvas zoom controls change the canvas", async ({ page }) => {
    const stage = page.locator(".canvas-stage").first();
    await expect(stage).toBeVisible();
    const start = await scaleOf(page);
    expect(start, "the stage reports no scale to change").toBeGreaterThan(0);

    await page.getByRole("button", { name: "Zoom in" }).click();
    const zoomedIn = await scaleOf(page);
    expect(zoomedIn, "Zoom in did not change the canvas").toBeGreaterThan(start);

    await page.getByRole("button", { name: "Zoom out" }).click();
    await page.getByRole("button", { name: "Zoom out" }).click();
    const zoomedOut = await scaleOf(page);
    expect(zoomedOut, "Zoom out did not change the canvas").toBeLessThan(zoomedIn);

    await page.getByRole("button", { name: "Fit to view" }).click();
    await expect.poll(() => scaleOf(page),
                      { message: "Fit to view did not return the canvas to its start" })
      .toBe(start);
  });

  test("zoom reaches its bounds and stops there", async ({ page }) => {
    // Asserting the bound is *reached*, not merely respected. The first version
    // of this said `toBeGreaterThanOrEqual(0.55)` and passed against a build
    // with the handlers deleted, because a canvas that never zooms never
    // exceeds a bound either. That is the same shape as the `GOAL_DRAG` L8 bug
    // and it survived one build cycle before the negative run found it.
    const zoomOut = page.getByRole("button", { name: "Zoom out" });
    for (let press = 0; press < 12; press += 1) await zoomOut.click();
    expect(await scaleOf(page), "zooming out did not reach the floor and stop there")
      .toBeCloseTo(0.55, 5);

    const zoomIn = page.getByRole("button", { name: "Zoom in" });
    for (let press = 0; press < 20; press += 1) await zoomIn.click();
    expect(await scaleOf(page), "zooming in did not reach the ceiling and stop there")
      .toBeCloseTo(1.35, 5);
  });

  test("the pipeline header offers no tab that goes nowhere", async ({ page }) => {
    // Three names -- Graph, Proposals, History -- rendered as buttons with one
    // drawn as selected, and none of them switched anything. Two of the three
    // name surfaces that exist elsewhere with real tabs, which is what made the
    // strip readable as working. It is gone; the assertion is that it stays gone.
    const header = page.locator(".workspace-header").first();
    await expect(header).toBeVisible();
    await expect(header.getByRole("button", { name: "Proposals", exact: true })).toHaveCount(0);
    await expect(header.getByRole("button", { name: "History", exact: true })).toHaveCount(0);
  });
});
