import { expect, test } from "@playwright/test";

/**
 * A touch user can add the first node to a pipeline.
 *
 * Before this existed, they could not. `PipelineBuilder` places nodes with
 * native HTML5 drag-and-drop, which does not fire from touch input, and the `+`
 * control that inserts a node renders at the midpoint of an existing *edge* --
 * so a new pipeline, which starts with zero nodes and zero edges, offered no
 * control a finger could reach. Measured on a 390x844 viewport with `hasTouch`:
 * palette and canvas both visible, and neither a tap nor a touch-drag produced a
 * node. The screen rendered and could not be used.
 *
 * Everything below is `locator.tap()`, never a drag, and never a mouse click.
 * `page.touchscreen.tap(x, y)` is deliberately not used: it dispatches touch
 * events without the click a browser synthesises from them, so it fails against
 * a working button and reads like a broken product.
 */
test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

test("a touch user can add the first node to a pipeline", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-1280",
            "Runs once; this file sets its own viewport and touch emulation.");

  await page.goto("/workspace/pipeline");
  await page.getByRole("button", { name: "New pipeline" }).tap();
  await expect(page.getByText(/Pipeline draft created/)).toBeVisible();

  const canvas = page.locator(".pipeline-canvas");
  await expect(canvas.locator(".pipeline-node")).toHaveCount(0);

  // Choose a node type from the palette by tapping it.
  await page.getByRole("button", { name: "Input Dataset input" }).tap();

  // The empty canvas offers a control that is not a drag.
  const add = canvas.getByRole("button", { name: /^Add / });
  await expect(add, "an empty canvas must offer a non-drag affordance").toBeVisible();
  await add.tap();

  await expect(canvas.locator(".pipeline-node")).toHaveCount(1);
  // Once a node exists the affordance retires and leaves the canvas to the graph.
  await expect(add).toHaveCount(0);
});
