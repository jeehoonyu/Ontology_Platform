import AxeBuilder from "@axe-core/playwright";
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

  // U7. A Panel's title is the original's card title, 14px on a 16px line at 600,
  // and it is still the h2 inside section.panel > header.panel-header.
  test("A panel title is 14px bold, and it is still a heading", async ({ page }) => {
    await page.goto("/workspace/decision");
    const title = page.getByRole("heading", { name: "Risk Board", level: 2 });
    await expect(title).toBeVisible();
    expect.soft(await title.evaluate((node) => ({
      inPanel: node.parentElement!.matches("header.panel-header")
        && node.parentElement!.parentElement!.matches("section.panel"),
      font: `${getComputedStyle(node).fontSize}/${getComputedStyle(node).lineHeight} ${getComputedStyle(node).fontWeight}`,
    })), "a panel title").toEqual({ inPanel: true, font: "14px/16px 600" });
  });

  // U7. A card's edge is --shadow-0's ring, with no border, at radius 4, on the
  // #f6f7f9 ground. Panels in the rails that used to flatten themselves keep it.
  test("A panel's edge is a ring shadow, not a border", async ({ page }) => {
    const ring = "rgba(0, 0, 0, 0.15) 0px 0px 0px 1px, rgba(0, 0, 0, 0.02) 0px 0px 5px 0px";
    const edge = (locator: ReturnType<Page["locator"]>) => locator.evaluate((node) => {
      const style = getComputedStyle(node);
      return { shadow: style.boxShadow, border: style.borderTopStyle, radius: style.borderTopLeftRadius,
               background: style.backgroundColor };
    });
    await page.goto("/workspace/decision");
    const panel = page.locator(".panel").filter({ has: page.getByRole("heading", { name: "Risk Board" }) });
    await expect(panel).toBeVisible();
    expect.soft(await edge(panel), "a panel").toEqual({
      shadow: ring, border: "none", radius: "4px", background: "rgb(255, 255, 255)" });
    expect.soft(await page.evaluate(() => getComputedStyle(document.documentElement).backgroundColor), "the app ground")
      .toBe("rgb(246, 247, 249)");

    await page.goto("/workspace/ontology");
    const railPanel = page.locator(".manager-resource-nav .panel").first();
    await expect(railPanel).toBeVisible();
    expect.soft((await edge(railPanel)).shadow, "a panel in the resources rail").toBe(ring);
  });

  // U7. A pane is ruled with the divider, as the original's side panels are, and so
  // is the line under its header.
  test("A pane and its header are ruled with the divider", async ({ page }) => {
    await page.goto("/workspace/pipeline");
    const pane = page.getByRole("region", { name: "Pipeline", exact: true });
    await expect(pane).toBeVisible();
    expect.soft(await pane.evaluate((node) => {
      const style = getComputedStyle(node);
      const header = getComputedStyle(node.querySelector(".pane-header")!);
      return {
        edge: `${style.borderTopWidth} ${style.borderTopStyle} ${style.borderTopColor}`,
        radius: style.borderTopLeftRadius,
        headerRule: `${header.borderBottomWidth} ${header.borderBottomStyle} ${header.borderBottomColor}`,
        headerGround: header.backgroundColor,
      };
    }), "a pane").toEqual({
      edge: `1px solid ${ruleColour}`, radius: "3px",
      headerRule: `1px solid ${ruleColour}`, headerGround: "rgb(246, 247, 249)",
    });
  });

  // U7. A pane's title is the original's side-panel title, 14px at 600, and it is
  // still the <strong> the pane measures against its controls, not a heading.
  test("A pane title is 14px bold, and it is still the pane's strong", async ({ page }) => {
    await page.goto("/workspace/pipeline");
    const title = page.getByRole("region", { name: "Pipeline", exact: true }).locator(".pane-header strong");
    await expect(title).toHaveText("Pipeline");
    expect.soft(await title.evaluate((node) => ({
      tag: node.tagName.toLowerCase(),
      font: `${getComputedStyle(node).fontSize} ${getComputedStyle(node).fontWeight}`,
    })), "a pane title").toEqual({ tag: "strong", font: "14px 600" });
  });

  // U7. The original's tables: a 30px header in 12px 400 uppercase muted text on
  // the app ground, 40px rows, 0 11px cells, and an ink rule under each row. The
  // Object Explorer's table is read with objects in it.
  test("A table header is 30px, 12px, muted and uppercase", async ({ page }) => {
    expect((await page.request.post("/scenarios/asset-reliability/bootstrap", { data: {} })).ok()).toBeTruthy();
    await page.goto("/workspace/object-explorer?type=asset");
    const table = page.locator(".explorer-table");
    await expect(table).toContainText("asset_pump_4");
    const read = (locator: ReturnType<Page["locator"]>) => locator.evaluate((node) => {
      const style = getComputedStyle(node);
      return {
        height: `${Math.round((node.closest("tr") ?? node).getBoundingClientRect().height)}px`,
        font: `${style.fontSize} ${style.fontWeight} ${style.textTransform}`,
        color: style.color, background: style.backgroundColor, padding: style.padding,
        rule: `${style.borderBottomWidth} ${style.borderBottomStyle} ${style.borderBottomColor}`,
      };
    });
    expect.soft(await read(table.locator("thead th:not(.selection-cell)").first()), "a header cell").toEqual({
      height: "30px", font: "12px 400 uppercase", color: "rgb(95, 107, 124)",
      background: "rgb(246, 247, 249)", padding: "0px 11px", rule: `1px solid ${ruleColour}`,
    });
    const cell = await read(table.locator("tbody td:not(.selection-cell)").first());
    expect.soft({ height: cell.height, padding: cell.padding, rule: cell.rule }, "a body row").toEqual({
      height: "40px", padding: "0px 11px", rule: `1px solid ${ruleColour}` });
    // The narrow checkbox column keeps room for its checkbox: no ellipsis beside it.
    for (const selection of [table.locator("thead .selection-cell"), table.locator("tbody .selection-cell").first()]) {
      expect.soft(await selection.evaluate((node) => node.scrollWidth - node.clientWidth),
                  "the checkbox column overflows").toBe(0);
    }
  });

  // U8, the plan's A1. The badge's colour comes from the intent its caller gives,
  // not from its word: the backend bar's OFFLINE used to render green, because the
  // old rule defaulted to success. The readiness call is refused to make it offline.
  test("OFFLINE is not shown as success", async ({ page }) => {
    await page.route((url) => url.pathname === "/project/readiness", (route) => route.abort());
    await page.goto("/workspace/decision");
    const badge = page.locator(".backend-connection .badge");
    await expect(badge).toHaveText("OFFLINE");
    expect.soft(await badge.evaluate((node) => ({
      intent: node.getAttribute("data-intent"), color: getComputedStyle(node).color,
    })), "the offline badge").toEqual({ intent: "danger", color: "rgb(172, 47, 51)" });
  });

  // U8. A warning tag's text is the warning hover step (#935610) on its 10% tint,
  // read against the ground it actually sits on. #c87619, the rest step, is 3:1.
  test("A warning badge reads at AA contrast", async ({ page }) => {
    expect((await page.request.post("/scenarios/asset-reliability/bootstrap", { data: {} })).ok()).toBeTruthy();
    await page.goto("/workspace/command-center");
    const badge = page.locator(".warning-list article").filter({ hasText: "Data contract status is" })
      .locator(".badge").first();
    await expect(badge).toHaveText("warn");
    const reading = await badge.evaluate((node) => {
      const parse = (value: string) => {
        const [r, g, b, a = 1] = (value.match(/[\d.]+/g) || []).map(Number);
        return { r, g, b, a };
      };
      // Composite each translucent background, from the first opaque ancestor up.
      const layers: ReturnType<typeof parse>[] = [];
      for (let el: Element | null = node; el; el = el.parentElement) {
        const background = parse(getComputedStyle(el).backgroundColor);
        if (background.a > 0) layers.unshift(background);
        if (background.a >= 1) break;
      }
      let ground = { r: 255, g: 255, b: 255 };
      for (const layer of layers) {
        ground = { r: layer.r * layer.a + ground.r * (1 - layer.a), g: layer.g * layer.a + ground.g * (1 - layer.a),
                   b: layer.b * layer.a + ground.b * (1 - layer.a) };
      }
      const luminance = ({ r, g, b }: { r: number; g: number; b: number }) => {
        const channel = (c: number) => { const s = c / 255; return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4; };
        return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
      };
      const text = parse(getComputedStyle(node).color);
      const [light, dark] = [luminance(ground), luminance(text)].sort((x, y) => y - x);
      return { intent: node.getAttribute("data-intent"), ratio: Math.round(((light + 0.05) / (dark + 0.05)) * 100) / 100 };
    });
    expect.soft(reading.intent, "the warning badge's intent").toBe("warning");
    expect.soft(reading.ratio, "the warning badge's contrast").toBeGreaterThanOrEqual(4.5);
  });

  // U9, decision H (a). The original's sidebar colours at our 286px width: the dark
  // gray, the active item in #1c2127 with a 600 label, the hover in #383e47.
  test("The sidebar is the original's dark gray", async ({ page }) => {
    await page.goto("/workspace/decision");
    await expect(page.getByRole("heading", { name: "Decision Intelligence" })).toBeVisible();
    const sidebar = page.locator(".sidebar");
    expect.soft(await sidebar.evaluate((node) => ({
      background: getComputedStyle(node).backgroundColor, width: Math.round(node.getBoundingClientRect().width),
    })), "the sidebar").toEqual({ background: "rgb(37, 42, 49)", width: 286 });
    const item = (locator: ReturnType<Page["locator"]>) => locator.evaluate((node) => ({
      background: getComputedStyle(node).backgroundColor,
      label: getComputedStyle(node.querySelector("strong")!).fontWeight,
    }));
    expect.soft(await item(sidebar.locator(".nav-item.active")), "the active item")
      .toEqual({ background: "rgb(28, 33, 39)", label: "600" });
    const other = sidebar.locator(".nav-item:not(.active)").first();
    expect.soft((await item(other)).label, "an inactive item's label").toBe("400");
    await other.hover();
    expect.soft((await item(other)).background, "a hovered item").toBe("rgb(56, 62, 71)");
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

  // U10, Tag. UI_CONFIG's tag: 20px, radius 4, 2px 6px, 12px at 400, on its intent's
  // 10% tint; neutral is the minimal tint. The review tabs' counts were a 10px pill
  // of their own, and are the same tag now.
  test("A tag is 20px with radius 4, and the review counts are tags", async ({ page }) => {
    const read = (locator: ReturnType<Page["locator"]>) => locator.evaluate((node) => {
      const style = getComputedStyle(node);
      return {
        height: `${Math.round(node.getBoundingClientRect().height)}px`, radius: style.borderTopLeftRadius,
        padding: style.padding, font: `${style.fontSize} ${style.fontWeight}`, background: style.backgroundColor,
      };
    });
    const tag = { height: "20px", radius: "4px", padding: "2px 6px", font: "12px 400" };
    await page.goto("/workspace/decision");
    const ready = page.locator(".backend-connection .badge");
    await expect(ready).toHaveText("READY");
    expect.soft(await read(ready), "a success tag").toEqual({ ...tag, background: "rgba(35, 133, 81, 0.1)" });

    await page.goto("/workspace/workshop");
    const create = page.getByRole("button", { name: "Create draft" });
    await expect(create.or(page.locator(".visual-builder-shell")).first()).toBeVisible();
    if (await create.isVisible()) await create.click();
    const count = page.locator(".artifact-review-panel").getByRole("tab", { name: /Comments/ }).locator(".badge");
    await expect(count).toHaveText(/^\d+$/);
    expect.soft(await read(count), "a review-tab count").toEqual({ ...tag, background: "rgba(143, 153, 168, 0.15)" });
  });

  // U10, NonIdealState. UI_CONFIG's empty state: centred in the space it replaces, with
  // no box of its own; a 48px muted icon, then the title at 18px/20px 600 and one 14px
  // line, both in #5f6b7c. Decision's Risk Board is empty until an evaluation runs.
  test("An empty state is centred, with a 48px icon over an 18px muted title", async ({ page }) => {
    await page.goto("/workspace/decision");
    const empty = page.locator(".empty-state-card").filter({ hasText: "No evaluated objects" });
    await expect(empty).toBeVisible();
    expect.soft(await empty.evaluate((node) => {
      const box = node.getBoundingClientRect();
      const offCentre = (element: Element | null) => {
        if (!element) return "missing";
        const rect = element.getBoundingClientRect();
        return Math.abs(rect.left + rect.width / 2 - (box.left + box.width / 2)) <= 1 ? "centred" : "off centre";
      };
      const [icon, title, line] = [node.querySelector(":scope > svg"), node.querySelector("strong"), node.querySelector(":scope > span")];
      const style = (element: Element | null) => (element ? getComputedStyle(element) : null);
      return {
        box: `${style(node)!.borderTopStyle} ${style(node)!.backgroundColor}`,
        icon: icon ? `${Math.round(icon.getBoundingClientRect().width)}px ${style(icon)!.color}` : "missing",
        title: title ? `${style(title)!.fontSize}/${style(title)!.lineHeight} ${style(title)!.fontWeight} ${style(title)!.color}` : "missing",
        line: line ? `${style(line)!.fontSize} ${style(line)!.color}` : "missing",
        placement: [offCentre(icon), offCentre(title), offCentre(line)],
      };
    }), "the Risk Board's empty state").toEqual({
      box: "none rgba(0, 0, 0, 0)", icon: "48px rgb(143, 153, 168)",
      title: "18px/20px 600 rgb(95, 107, 124)", line: "14px rgb(95, 107, 124)",
      placement: ["centred", "centred", "centred"],
    });
  });

  // U10, SectionCard. UI_CONFIG's section card: a 50px header ruled from the body by
  // the divider, running to the card's edges, its title inset 20px; the body is padded
  // 20px, so the first thing in it sits 20px under the rule.
  test("A panel's header is the original's 50px section header", async ({ page }) => {
    await page.goto("/workspace/decision");
    const panel = page.locator("section.panel").filter({ has: page.getByRole("heading", { name: "Risk Board", exact: true }) });
    await expect(panel).toBeVisible();
    expect.soft(await panel.evaluate((node) => {
      const card = node.getBoundingClientRect();
      const header = node.querySelector(":scope > header.panel-header")!;
      const rect = header.getBoundingClientRect();
      const style = getComputedStyle(header);
      const title = header.querySelector("h2")!.getBoundingClientRect();
      const body = header.nextElementSibling!.getBoundingClientRect();
      return {
        height: Math.round(rect.height), rule: `${style.borderBottomWidth} ${style.borderBottomStyle} ${style.borderBottomColor}`,
        flush: [Math.round(rect.left - card.left), Math.round(card.right - rect.right), Math.round(rect.top - card.top)],
        titleInset: Math.round(title.left - card.left), bodyGap: Math.round(body.top - rect.bottom),
      };
    }), "the Risk Board's header").toEqual({
      height: 50, rule: "1px solid rgba(17, 20, 24, 0.15)", flush: [0, 0, 0], titleInset: 20, bodyGap: 20,
    });
  });

  // U10, SectionCard. The taller cards make Object Explorer's inspector, a sticky column
  // capped at the viewport, scroll where it did not; with nothing selected it holds no
  // control, so a keyboard could not scroll it (axe: scrollable-region-focusable, seen
  // once at 1366 in the full run). A short window makes it scroll every time.
  test("A scrolling object inspector can be reached by keyboard", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 480 });
    await page.goto("/workspace/object-explorer");
    await expect(page.getByRole("heading", { name: "Object Explorer" })).toBeVisible();
    const inspector = page.locator(".explorer-inspector");
    await expect(inspector).toContainText("Select a result to inspect");
    expect(await inspector.evaluate((node) => node.scrollHeight > node.clientHeight), "the inspector scrolls").toBe(true);
    const scan = await new AxeBuilder({ page }).include(".explorer-inspector").withRules(["scrollable-region-focusable"]).analyze();
    expect.soft(scan.violations.map((violation) => violation.id), "the inspector's scroll region").toEqual([]);
    await expect.soft(inspector, "the inspector's name").toHaveAccessibleName("Object inspector");
  });

  // U10, AppHeader. UI_CONFIG's app header: a 50px white bar ruled below, the screen's
  // name in 16px/19px 600, and one h1 on the page. Ours runs to the workspace's edges
  // under the flow strip and the backend bar, so it is ruled above as well.
  test("The page title is a 16px name in the original's 50px header bar", async ({ page }) => {
    await page.goto("/workspace/decision");
    const header = page.locator(".page-header");
    await expect(header.getByRole("heading", { level: 1, name: "Decision Intelligence" })).toBeVisible();
    expect.soft(await page.locator("h1").count(), "level-1 headings on the page").toBe(1);
    expect.soft(await header.evaluate((node) => {
      const workspace = node.closest(".workspace")!;
      const bounds = workspace.getBoundingClientRect();
      const rect = node.getBoundingClientRect();
      const style = getComputedStyle(node);
      const title = getComputedStyle(node.querySelector("h1")!);
      return {
        height: Math.round(rect.height), background: style.backgroundColor, rules: style.boxShadow,
        flush: [Math.round(rect.left - bounds.left - workspace.clientLeft),
                Math.round(bounds.left + workspace.clientLeft + workspace.clientWidth - rect.right)],
        title: `${title.fontSize}/${title.lineHeight} ${title.fontWeight}`,
      };
    }), "the page header").toEqual({
      height: 50, background: "rgb(255, 255, 255)",
      rules: "rgba(17, 20, 24, 0.15) 0px 1px 0px 0px, rgba(17, 20, 24, 0.15) 0px -1px 0px 0px",
      flush: [0, 0], title: "16px/19px 600",
    });
  });

  // GOAL_FOUNDATIONS A8, Tabs. UI_CONFIG's underline tabs: a 40px bar ruled by the
  // divider, 14px labels at 400 set 20px apart, the selected one in #215db0 over a 3px
  // indicator and marked aria-current. Only the colour changes.
  test("Tabs are the original's underline tabs", async ({ page }) => {
    await page.goto("/workspace/decision");
    const bar = page.getByRole("navigation", { name: "Decision intelligence views" });
    await expect(bar).toBeVisible();
    expect.soft(await bar.evaluate((node) => {
      const style = getComputedStyle(node);
      return { height: Math.round(node.getBoundingClientRect().height), gap: style.columnGap, rule: style.boxShadow };
    }), "the bar").toEqual({ height: 40, gap: "20px", rule: "rgba(17, 20, 24, 0.15) 0px -1px 0px 0px inset" });
    const read = (tab: ReturnType<Page["locator"]>) => tab.evaluate((node) => {
      const style = getComputedStyle(node);
      return { font: `${style.fontSize} ${style.fontWeight}`, color: style.color, indicator: style.boxShadow,
               current: node.getAttribute("aria-current") };
    });
    expect.soft(await read(bar.getByRole("button", { name: "Risk Board" })), "the selected tab").toEqual({
      font: "14px 400", color: "rgb(33, 93, 176)", indicator: "rgb(33, 93, 176) 0px -3px 0px 0px inset", current: "true" });
    expect.soft(await read(bar.getByRole("button", { name: "Timeline" })), "another tab").toEqual({
      font: "14px 400", color: "rgb(28, 33, 39)", indicator: "none", current: null });
  });

  // GOAL_FOUNDATIONS A8. Each screen's underline tab set is the Tabs primitive: a
  // .tabs nav whose selected tab says so with aria-current. A screen still drawing its
  // own buttons has neither. The list grows as screens move.
  for (const [route, name] of [["decision", "Decision intelligence views"], ["ops", "Operational control views"],
                               ["models", "ModelOps lifecycle"], ["security", "Security & Governance views"],
                               ["control-panel", "Administration sections"], ["delivery", "Delivery sections"]]) {
    test(`The ${route} tabs are the Tabs primitive`, async ({ page }) => {
      await page.goto(`/workspace/${route}`);
      const bar = page.getByRole("navigation", { name });
      await expect(bar).toBeVisible();
      expect.soft(await bar.evaluate((node) => ({
        primitive: node.classList.contains("tabs"),
        current: [...node.querySelectorAll("button")].filter((button) => button.getAttribute("aria-current") === "true").length,
      })), `the ${route} tab bar`).toEqual({ primitive: true, current: 1 });
    });
  }

  // GOAL_FOUNDATIONS A8, tint tabs. UI_CONFIG's bottom-panel tabs: a 35px bar, the
  // selected tab on the rgba(45,114,210,.1) tint in #215db0, with no indicator.
  test("The pipeline drawer's tabs are the original's tint tabs", async ({ page }) => {
    await page.goto("/workspace/pipeline");
    const bar = page.getByRole("navigation", { name: "Drawer views" });
    await expect(bar).toBeVisible();
    expect.soft(await bar.evaluate((node) => ({
      primitive: node.classList.contains("tabs"), height: Math.round(node.getBoundingClientRect().height),
    })), "the drawer's bar").toEqual({ primitive: true, height: 35 });
    const selected = await bar.locator("button[aria-current='true']").evaluate((node) => {
      const style = getComputedStyle(node);
      return { background: style.backgroundColor, color: style.color, indicator: style.boxShadow };
    });
    expect.soft(selected, "the selected drawer tab").toEqual({
      background: "rgba(45, 114, 210, 0.1)", color: "rgb(33, 93, 176)", indicator: "none" });
  });

  // GOAL_FOUNDATIONS A8, the review tablist. The artifact review keeps its ARIA tablist
  // (decision N): Tabs draws it with aria-selected, one tab stop, and the arrow keys
  // moving the selection, which the hand-written tabs lacked.
  test("The artifact review tabs are a Tabs tablist", async ({ page }) => {
    await page.goto("/workspace/workshop");
    const create = page.getByRole("button", { name: "Create draft" });
    await expect(create.or(page.locator(".visual-builder-shell")).first()).toBeVisible();
    if (await create.isVisible()) await create.click();
    const list = page.getByRole("tablist", { name: "Review views" });
    await expect(list).toBeVisible();
    const state = () => list.evaluate((node) => ({
      primitive: node.classList.contains("tabs"),
      tabs: [...node.querySelectorAll("[role='tab']")].map((tab) => [tab.textContent?.replace(/\d+/g, "").trim(),
        tab.getAttribute("aria-selected"), (tab as HTMLElement).tabIndex]),
    }));
    expect.soft(await state(), "the review tablist").toEqual({
      primitive: true, tabs: [["Comments", "true", 0], ["Proposals", "false", -1]] });
    await list.getByRole("tab", { name: /Comments/ }).focus();
    await page.keyboard.press("ArrowRight");
    expect.soft(await state(), "after ArrowRight").toEqual({
      primitive: true, tabs: [["Comments", "false", -1], ["Proposals", "true", 0]] });
    await expect.soft(list.getByRole("tab", { name: /Proposals/ }), "focus follows the selection").toBeFocused();
  });

  // GOAL_FOUNDATIONS A8. The Workshop breakpoint switch is the SegmentedControl, with
  // each option saying whether it is pressed.
  test("The Workshop breakpoint switch is the SegmentedControl", async ({ page }) => {
    await page.goto("/workspace/workshop");
    const create = page.getByRole("button", { name: "Create draft" });
    await expect(create.or(page.locator(".visual-builder-shell")).first()).toBeVisible();
    if (await create.isVisible()) await create.click();
    const control = page.getByRole("group", { name: "Workshop breakpoint" });
    await expect(control).toBeVisible();
    const pressed = () => control.evaluate((node) => ({
      primitive: node.classList.contains("segmented-control"),
      pressed: [...node.querySelectorAll("button")].map((button) => [button.textContent, button.getAttribute("aria-pressed")]),
    }));
    expect.soft(await pressed(), "the breakpoint switch").toEqual({ primitive: true,
      pressed: [["Desktop", "true"], ["Tablet", "false"], ["Mobile", "false"]] });
    await control.getByRole("button", { name: "Tablet" }).click();
    expect.soft((await pressed()).pressed, "after choosing Tablet").toEqual([["Desktop", "false"], ["Tablet", "true"], ["Mobile", "false"]]);
  });

  // GOAL_FOUNDATIONS A8, SegmentedControl. UI_CONFIG's light segmented control: 30px,
  // the selected option white with the default button's ring, the others transparent
  // in #5f6b7c; each option says whether it is pressed.
  test("A segmented control is 30px with the selected option raised", async ({ page }) => {
    expect((await page.request.post("/scenarios/asset-reliability/bootstrap", { data: {} })).ok()).toBeTruthy();
    await page.goto("/workspace/ontology");
    await page.getByRole("button", { name: "health center" }).click();
    const control = page.getByRole("group", { name: "Finding severity" });
    await expect(control).toBeVisible();
    expect.soft(Math.round((await control.boundingBox())!.height), "the control").toBe(30);
    const read = (option: ReturnType<Page["locator"]>) => option.evaluate((node) => {
      const style = getComputedStyle(node);
      return { background: style.backgroundColor, ring: style.borderTopColor, color: style.color,
               pressed: node.getAttribute("aria-pressed") };
    });
    expect.soft(await read(control.getByRole("button", { name: "ALL" })), "the selected option").toEqual({
      background: "rgb(255, 255, 255)", ring: "rgba(69, 78, 91, 0.325)", color: "rgb(28, 33, 39)", pressed: "true" });
    expect.soft(await read(control.getByRole("button", { name: "ERROR" })), "another option").toEqual({
      background: "rgba(0, 0, 0, 0)", ring: "rgba(0, 0, 0, 0)", color: "rgb(95, 107, 124)", pressed: "false" });
  });
});
