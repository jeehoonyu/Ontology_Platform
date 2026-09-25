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

  // U4. fonts.css bundles Source Sans 3. A computed style names the family
  // whether or not the face loaded, so this asks Chrome which font drew the
  // glyphs: a title (bold, drawn by the 600 face) and a subtitle (the 400 face).
  // The files' own names read "Source Sans 3 ExtraLight ...": they were cut from
  // Google's variable font, whose default instance is ExtraLight; their OS/2
  // weights are 400 and 600, and their style names say Regular and SemiBold.
  test("The page text renders in the bundled face, not a system font", async ({ page }) => {
    await page.goto("/workspace/decision");
    await expect(page.getByRole("heading", { name: "Decision Intelligence" })).toBeVisible();
    await page.evaluate(() => document.fonts.ready);
    const cdp = await page.context().newCDPSession(page);
    await cdp.send("DOM.enable");
    await cdp.send("CSS.enable");
    const { root } = await cdp.send("DOM.getDocument", { depth: -1 });
    for (const [selector, style] of [[".page-header h1", "SemiBold"], [".page-header p", "Regular"]]) {
      const { nodeId } = await cdp.send("DOM.querySelector", { nodeId: root.nodeId, selector });
      const { fonts } = await cdp.send("CSS.getPlatformFontsForNode", { nodeId });
      expect.soft(fonts.map((font) => ({
        bundled: font.isCustomFont,
        family: font.familyName.startsWith("Source Sans 3") ? "Source Sans 3" : font.familyName,
        style: font.postScriptName?.split("-").pop(),
      })), `${selector}: ${JSON.stringify(fonts)}`)
        .toEqual([{ bundled: true, family: "Source Sans 3", style }]);
    }
  });

  // U5. The original's body is 14px on an 18px line (Blueprint's 1.28581). Text
  // with no size of its own inherits both, like a page subtitle. A button takes
  // the size through `font: inherit` and keeps its own `line-height: 1.2`, which
  // U6's button rule replaces; explicit values stay.
  test("The body text is 14px on an 18px line", async ({ page }) => {
    await page.goto("/workspace/decision");
    await expect(page.getByRole("heading", { name: "Decision Intelligence" })).toBeVisible();
    const read = (selector: string) => page.locator(selector).first().evaluate((node) => {
      const style = getComputedStyle(node);
      // 1.28581 x 14 is 18.0013px; a line is whole pixels on screen.
      const line = style.lineHeight === "normal" ? "normal" : `${Math.round(parseFloat(style.lineHeight))}px`;
      return { fontSize: style.fontSize, lineHeight: line };
    });
    for (const selector of [":root", ".page-header p"]) {
      expect.soft(await read(selector), selector).toEqual({ fontSize: "14px", lineHeight: "18px" });
    }
    expect.soft((await read(".decision-tabs button")).fontSize, "a button's text").toBe("14px");
  });
});
