import { expect, test, type Page } from "@playwright/test";

/**
 * The look, read back from the browser. `GOAL_LOOK_2026-09-24.md`.
 *
 * Each test reads computed styles from the built app, because the question is
 * what a user sees, not what a stylesheet says. A declaration that names an
 * undefined custom property is invalid at computed-value time: the property
 * computes as if unset, the browser draws nothing, and no build step or type
 * check notices. That is how Decision and Ops lost their borders, grounds and
 * active-tab marks -- `styles.css` names `--border`, `--accent` and five more
 * that nothing defined.
 *
 * Computed styles do not change with the viewport, so these run once, on
 * desktop. Each was run against a build with the thing it defends removed, and
 * failed, before it was believed.
 */

const ruleColour = "rgba(17, 20, 24, 0.15)"; // --divider
const selectedText = "rgb(33, 93, 176)";      // --text-selected, #215db0

async function styleOf(page: Page, selector: string, properties: string[]) {
  const element = page.locator(selector).first();
  await expect(element).toBeVisible();
  return element.evaluate((node, names) => {
    const style = getComputedStyle(node);
    return Object.fromEntries(names.map((name) => [name, style.getPropertyValue(name)]));
  }, properties);
}

test.describe("GOAL_LOOK", () => {
  test.beforeEach(({}, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-1280", "Computed styles are read once, on desktop.");
  });

  // U3. tokens.css is imported before styles.css, and its alias block defines
  // the seven names styles.css already used.
  test("The Decision and Ops screens draw the borders and colours their stylesheet names", async ({ page }) => {
    await page.goto("/workspace/decision");
    await expect(page.getByRole("heading", { name: "Decision Intelligence" })).toBeVisible();
    expect.soft(await styleOf(page, ".decision-topbar",
                         ["border-top-width", "border-top-style", "border-top-color"]))
      .toEqual({ "border-top-width": "1px", "border-top-style": "solid", "border-top-color": ruleColour });
    expect.soft(await styleOf(page, ".decision-tabs button.active", ["color", "box-shadow"]))
      .toEqual({ color: selectedText, "box-shadow": `${selectedText} 0px -3px 0px 0px inset` });

    await page.goto("/workspace/ops");
    await expect(page.getByRole("heading", { name: "Operational Control Plane" })).toBeVisible();
    expect.soft(await styleOf(page, ".ops-topbar", ["border-top-width", "border-top-style", "border-top-color"]))
      .toEqual({ "border-top-width": "1px", "border-top-style": "solid", "border-top-color": ruleColour });
  });
});
