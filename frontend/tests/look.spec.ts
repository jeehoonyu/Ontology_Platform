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

  // U6. The original's default button: 30px, padding 4px 8px, radius 4, #f7f8f9,
  // and --shadow-button's ring. The ring is drawn as the border (tokens.css says
  // why), so it reads as a 1px border in the ring's colour plus the drop shadow.
  // Primary takes the intent fill, and a deliberately small control keeps its size.
  test("A default button is 30px tall with the original's ring shadow", async ({ page }) => {
    await page.goto("/workspace/decision");
    await expect(page.getByRole("heading", { name: "Decision Intelligence" })).toBeVisible();
    const box = (locator: ReturnType<Page["locator"]>) => locator.evaluate((node) => {
      const style = getComputedStyle(node);
      return {
        height: `${Math.round(node.getBoundingClientRect().height)}px`,
        border: `${style.borderTopWidth} ${style.borderTopStyle} ${style.borderTopColor}`,
        shadow: style.boxShadow, background: style.backgroundColor, color: style.color,
        radius: style.borderTopLeftRadius, padding: style.padding,
      };
    });
    expect.soft(await box(page.locator(".decision-topbar").getByRole("button", { name: "Refresh" })), "a default button")
      .toEqual({
        height: "30px", border: "1px solid rgba(69, 78, 91, 0.325)",
        shadow: "rgba(17, 20, 24, 0.1) 0px 1px 2px 0px", background: "rgb(247, 248, 249)",
        color: "rgb(28, 33, 39)", radius: "4px", padding: "4px 8px",
      });
    const primary = await box(page.getByRole("button", { name: "Evaluate risk" }));
    expect.soft({ background: primary.background, color: primary.color, height: primary.height }, "a primary button")
      .toEqual({ background: "rgb(45, 114, 210)", color: "rgb(255, 255, 255)", height: "30px" });

    // The canvas pane is wide at 1280, so its controls are in its header rather
    // than behind ⋯ (the library pane, at 220px, always uses the menu).
    await page.goto("/workspace/pipeline");
    const collapse = page.getByRole("button", { name: "Collapse Pipeline" });
    await expect(collapse).toBeVisible();
    const small = parseFloat((await box(collapse)).height);
    expect.soft(small, "a pane control was raised to the control height").toBeLessThan(30);
    // The canvas toolbar is a dense row of text actions: the original's small size.
    expect.soft((await box(page.getByRole("button", { name: "Select all" }))).height,
                "a canvas tool is the small button").toBe("24px");
  });

  // U6. The original's text field: 30px, 0 8px, radius 4, white, the ring (drawn as
  // the border) and an inset shade; on focus the ring turns #4c90f0 and a 3px halo
  // replaces the shade. A select takes the same height.
  test("A text input is 30px with an inset ring and a blue focus ring", async ({ page }) => {
    await page.goto("/workspace/decision");
    await expect(page.getByRole("heading", { name: "Decision Intelligence" })).toBeVisible();
    const field = page.getByLabel("Decision object ID");
    const read = () => field.evaluate((node) => {
      const style = getComputedStyle(node);
      return {
        height: `${Math.round(node.getBoundingClientRect().height)}px`,
        border: `${style.borderTopWidth} ${style.borderTopStyle} ${style.borderTopColor}`,
        shadow: style.boxShadow, background: style.backgroundColor,
        radius: style.borderTopLeftRadius, padding: style.padding, outline: style.outlineStyle,
      };
    });
    expect.soft(await read(), "a text field at rest").toEqual({
      height: "30px", border: "1px solid rgba(17, 20, 24, 0.2)",
      shadow: "rgba(17, 20, 24, 0.3) 0px 1px 1px 0px inset", background: "rgb(255, 255, 255)",
      radius: "4px", padding: "0px 8px", outline: "none",
    });
    await field.focus();
    const focused = await read();
    expect.soft({ border: focused.border, shadow: focused.shadow, outline: focused.outline }, "a focused text field")
      .toEqual({ border: "1px solid rgb(76, 144, 240)", shadow: "rgba(76, 144, 240, 0.3) 0px 0px 0px 3px", outline: "none" });
    const select = page.getByLabel("Decision object type");
    expect.soft(Math.round((await select.boundingBox())!.height), "a select").toBe(30);

    // A disabled field reads as disabled: the pipeline's delivery strategy is off
    // until the snapshot runtime is chosen.
    await page.goto("/workspace/pipeline");
    const disabled = page.getByLabel("Delivery strategy");
    await expect(disabled).toBeDisabled();
    expect.soft(await disabled.evaluate((node) => {
      const style = getComputedStyle(node);
      return { background: style.backgroundColor, color: style.color, shadow: style.boxShadow };
    }), "a disabled field").toEqual({ background: "rgb(246, 247, 249)", color: "rgb(143, 153, 168)", shadow: "none" });
  });
});
