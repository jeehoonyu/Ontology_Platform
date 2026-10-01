import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Locator, type Page } from "@playwright/test";

/**
 * Overlays hold focus while open, close on Escape, and give focus back to what opened
 * them. `GOAL_FOUNDATIONS_2026-09-25.md` A7: the Dialog, the Menu and the Tooltip.
 *
 * Before A7 the command palette closed on Escape but left focus nowhere, and let Tab
 * walk out behind it; Object Explorer's action dialog did not close on Escape at all.
 * Both are the Dialog primitive now. Focus handling does not change with the viewport,
 * so these run once, on desktop; each was run against a build with the behaviour it
 * defends removed, and failed, before it was believed.
 */

async function focusStaysInside(page: Page, dialog: Locator, presses: number) {
  for (let press = 0; press < presses; press += 1) {
    await page.keyboard.press("Tab");
    expect(await dialog.evaluate((node) => node.contains(document.activeElement)), `focus left the dialog after ${press + 1} Tab(s)`).toBe(true);
  }
  await page.keyboard.press("Shift+Tab");
  expect(await dialog.evaluate((node) => node.contains(document.activeElement)), "focus left the dialog on Shift+Tab").toBe(true);
}

async function axeClean(page: Page, ...include: string[]) {
  let builder = new AxeBuilder({ page });
  for (const selector of include.length ? include : ["[role='dialog']"]) builder = builder.include(selector);
  const scan = await builder.withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
  return scan.violations.filter((violation) => violation.impact === "critical" || violation.impact === "serious").map((violation) => violation.id);
}

test.describe("GOAL_FOUNDATIONS A7, Dialog", () => {
  test.beforeEach(({}, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-1280", "Focus handling is checked once, on desktop.");
  });

  test("The command palette holds focus, closes on Escape, and gives focus back", async ({ page }) => {
    await page.goto("/workspace/decision");
    const trigger = page.getByRole("button", { name: "Search and commands" });
    await trigger.click();
    const dialog = page.getByRole("dialog", { name: "Search workspaces" });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByPlaceholder("Find a workspace or capability"), "the search field has focus").toBeFocused();
    await dialog.getByPlaceholder("Find a workspace or capability").fill("decision");
    await focusStaysInside(page, dialog, 4);
    expect.soft(await axeClean(page), "axe, with the palette open").toEqual([]);
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await expect(trigger, "focus went back to the button that opened it").toBeFocused();
  });

  test("Object Explorer's action dialog closes on Escape and gives focus back", async ({ page }) => {
    expect((await page.request.post("/scenarios/asset-reliability/bootstrap", { data: {} })).ok()).toBeTruthy();
    await page.goto("/workspace/object-explorer?type=asset");
    const table = page.locator(".explorer-table");
    await expect(table).toBeVisible();
    await table.locator("tbody input[type='checkbox']").first().check();
    const action = page.locator(".explorer-action-list button:not([disabled])").first();
    await expect(action).toBeVisible();
    await action.click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    expect(await dialog.evaluate((node) => node.contains(document.activeElement)), "focus moved into the dialog").toBe(true);
    await focusStaysInside(page, dialog, 5);
    expect.soft(await axeClean(page), "axe, with the action dialog open").toEqual([]);
    await page.keyboard.press("Escape");
    await expect(dialog, "Escape closes the action dialog").toBeHidden();
    await expect(action, "focus went back to the action that opened it").toBeFocused();
  });
});

/*
 * The Menu. Its adopter is the pipeline strip's unsaved-changes count, which opens the
 * list of node configurations typed and not saved: a list that pushed the canvas down
 * and stayed open until its button was pressed again, and came back open with the next
 * typed change. A pipeline of the test's own making, as graph-editor.spec.ts builds it,
 * and nodes a and b edited so the list has two items to move between.
 */

interface FixtureNode { id: string; x: number; y: number }

const FOUR: FixtureNode[] = [
  { id: "a", x: 40, y: 60 },
  { id: "b", x: 40, y: 250 },
  { id: "c", x: 300, y: 60 },
  { id: "d", x: 300, y: 250 },
];

async function openFixture(page: Page) {
  const suffix = `${Date.now()}${Math.floor(Math.random() * 1000)}`;
  const name = `Menu fixture ${suffix}`;
  const created = await page.request.post("/pipeline-builder/graphs", { data: {
    id: `menu_fixture_${suffix}`,
    display_name: name,
    nodes: FOUR.map((node) => ({ id: node.id, type: "filter", config: {}, position: { x: node.x, y: node.y } })),
    edges: [{ source: "a", target: "c" }, { source: "b", target: "d" }],
  } });
  expect(created.ok(), `the fixture pipeline was not created: ${created.status()}`).toBeTruthy();
  await page.goto("/workspace/pipeline");
  await page.getByRole("button", { name: "Reset panes" }).click();
  const outputs = page.getByRole("button", { name: "Pane actions for Outputs" });
  const row = page.locator(".output-rail .resource-row").filter({ hasText: name });
  if (!(await row.isVisible()) && await outputs.count()) await outputs.click();
  await row.click();
  await expect(page.locator(".workspace-header")).toContainText(name);
  await expect(page.locator(".pipeline-canvas .pipeline-node")).toHaveCount(FOUR.length);
  await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {});
  await showCanvas(page);
}

/**
 * The canvas at the top of the pane host, where a lasso aimed at the fixture's nodes
 * lands. Opening the pipeline from Outputs, and typing into the node form below the
 * canvas, each scroll the pane host away from it. The strip sits above the pane host,
 * so it stays on screen either way.
 */
async function showCanvas(page: Page) {
  await page.locator(".pipeline-canvas").evaluate((element) => {
    element.scrollLeft = 0;
    element.scrollTop = 0;
    element.scrollIntoView({ block: "start" });
  });
}

function node(page: Page, id: string) {
  return page.locator(`.pipeline-canvas .pipeline-node[data-node-id='${id}']`);
}

function selected(page: Page) {
  return page.locator(".pipeline-canvas .pipeline-node[data-in-selection='true']")
    .evaluateAll((nodes) => nodes.map((each) => each.getAttribute("data-node-id") || "").sort());
}

/** Types into each node's label, leaving one unsaved change per node. */
async function editNodes(page: Page, ids: string[]) {
  const label = page.getByLabel("Node label");
  let original = "";
  for (const id of ids) {
    await node(page, id).click();
    // The form follows the selection a render later; read it before then and the last
    // node's label is renamed twice, leaving one change where there should be two.
    await expect(node(page, id)).toHaveAttribute("data-in-selection", "true");
    await expect(label).not.toHaveValue(/ renamed$/);
    original = await label.inputValue();
    await label.fill(`${original} renamed`);
  }
  await showCanvas(page);
  const count = ids.length === 1 ? "1 unsaved change" : `${ids.length} unsaved changes`;
  const unsaved = page.locator(".workbench-status-strip").getByRole("button", { name: count });
  await expect(unsaved, "typing into a node's form did not count as unsaved").toBeVisible();
  return { unsaved, label, original };
}

async function stageToScreen(page: Page, x: number, y: number) {
  return page.locator(".canvas-stage").evaluate((stage, [px, py]) => {
    const box = stage.getBoundingClientRect();
    const zoom = box.width / (stage as HTMLElement).offsetWidth;
    return { x: box.left + px * zoom, y: box.top + py * zoom };
  }, [x, y] as const);
}

async function startLasso(page: Page, from: [number, number], to: [number, number]) {
  const start = await stageToScreen(page, ...from);
  const end = await stageToScreen(page, ...to);
  await page.mouse.move(start.x, start.y);
  await page.mouse.down();
  for (let step = 1; step <= 12; step += 1) {
    await page.mouse.move(start.x + ((end.x - start.x) * step) / 12, start.y + ((end.y - start.y) * step) / 12);
    await page.waitForTimeout(16);
  }
  await expect(page.locator(".canvas-lasso"), "the lasso never started").toBeVisible();
}

async function finishLasso(page: Page) {
  await page.mouse.up();
  await page.waitForTimeout(150);
}

// a (centre 126,89) and b (126,279); the rectangle takes both and neither of c, d.
const LEFT_COLUMN: [[number, number], [number, number]] = [[10, 30], [240, 340]];

const box = async (locator: Locator) => (await locator.boundingBox())!;

/**
 * Scrolls whatever scrolls the strip by 12px, up when it can so the button stays whole.
 * At 1280 by 900 that is the workspace, which has about 19px to give. Returns how far.
 */
async function nudgeStrip(trigger: Locator) {
  return trigger.evaluate((element) => {
    let scroller: Element | null = element.parentElement;
    while (scroller && !(scroller.scrollHeight > scroller.clientHeight && /auto|scroll/.test(getComputedStyle(scroller).overflowY))) {
      scroller = scroller.parentElement;
    }
    const target = scroller || document.scrollingElement!;
    const before = target.scrollTop;
    target.scrollTop = before - 12;
    if (target.scrollTop === before) target.scrollTop = before + 12;
    return Math.abs(target.scrollTop - before);
  });
}

/** 8px under its button and flush with the button's left edge (UI_CONFIG). */
async function expectUnder(panel: Locator, trigger: Locator) {
  const p = await box(panel);
  const t = await box(trigger);
  expect(Math.abs(p.y - (t.y + t.height) - 8), `the panel is not 8px under its button: ${JSON.stringify({ p, t })}`)
    .toBeLessThanOrEqual(1);
  expect(Math.abs(p.x - t.x), "the panel is not flush with its button's left edge").toBeLessThanOrEqual(1);
}

test.describe("GOAL_FOUNDATIONS A7, Menu", () => {
  test.beforeEach(({}, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-1280", "Focus handling is checked once, on desktop; the fixtures are stateful.");
  });

  test("The unsaved list is a disclosure: it opens from its button, arrows move through it, Escape gives focus back", async ({ page }) => {
    await openFixture(page);
    // Four items, so a key that went the wrong way, or Home and End taken for arrows,
    // lands somewhere other than where the right key does.
    const { unsaved } = await editNodes(page, ["a", "b", "c", "d"]);
    const list = page.getByRole("list", { name: "Unsaved changes" });
    const item = (id: string) => list.getByRole("button", { name: new RegExp(`\\(${id}\\): configuration not saved`) });
    const [itemA, itemB, itemC, itemD] = ["a", "b", "c", "d"].map(item);
    await expect(unsaved, "a disclosure is not announced as a menu").not.toHaveAttribute("aria-haspopup");
    await expect(unsaved).not.toHaveAttribute("aria-controls");
    await expect(unsaved).toHaveAttribute("aria-expanded", "false");

    // A click opens it and leaves focus on the button; its panel names it while open.
    await unsaved.click();
    await expect(list).toBeVisible();
    await expect(unsaved, "opening moved focus off the button; a disclosure leaves it there").toBeFocused();
    await expect(unsaved).toHaveAttribute("aria-expanded", "true");
    const panel = page.locator(".menu-panel");
    await expect(unsaved).toHaveAttribute("aria-controls", (await panel.getAttribute("id"))!);
    // The panel follows its button in the page, so Tab goes into it.
    await page.keyboard.press("Tab");
    await expect(itemA, "Tab from the button did not go into its panel").toBeFocused();
    await expect(list).toBeVisible();

    // The arrows, Home and End move between the items, and the arrows go round.
    for (const [key, target] of [["ArrowDown", itemB], ["End", itemD], ["ArrowDown", itemA], ["ArrowUp", itemD],
                                  ["ArrowUp", itemC], ["Home", itemA], ["Home", itemA]] as const) {
      await page.keyboard.press(key);
      await expect(target, `${key} did not move focus where it should`).toBeFocused();
    }

    // Escape from an item closes it and gives focus back.
    await page.keyboard.press("Escape");
    await expect(list).toHaveCount(0);
    await expect(unsaved, "Escape left focus nowhere").toBeFocused();
    await expect(unsaved).toHaveAttribute("aria-expanded", "false");
    await expect(unsaved).not.toHaveAttribute("aria-controls");

    // From the button, ArrowUp opens onto the last item and ArrowDown onto the first.
    await page.keyboard.press("ArrowUp");
    await expect(itemD, "ArrowUp on the button did not open onto the last item").toBeFocused();
    await page.keyboard.press("Escape");
    await page.keyboard.press("ArrowDown");
    await expect(itemA, "ArrowDown on the button did not open onto the first item").toBeFocused();
    // Escape on the button itself closes it too.
    await unsaved.focus();
    await page.keyboard.press("Escape");
    await expect(list).toHaveCount(0);
    await expect(unsaved).toBeFocused();
  });

  test("The unsaved list floats 8px under its button, moves with it, and closes when it goes out of sight", async ({ page }) => {
    const strip = page.locator(".workbench-status-strip");
    await openFixture(page);
    const { unsaved } = await editNodes(page, ["a"]);
    await unsaved.click();
    const panel = page.locator(".menu-panel");
    const list = page.getByRole("list", { name: "Unsaved changes" });
    await expect(list).toBeVisible();
    await expectUnder(panel, unsaved);
    // Over the canvas, not pushing it down: what is under the panel's corner is the panel.
    expect(await panel.evaluate((element) => {
      const rect = element.getBoundingClientRect();
      return element.contains(document.elementFromPoint(rect.left + 6, rect.bottom - 6));
    }), "the panel is clipped or sits under something").toBe(true);

    // UI_CONFIG's menu: white, radius 4, the overlay shadow, 4px in; 14px/22px items with the minimal hover.
    const look = await panel.evaluate((element) => {
      const style = getComputedStyle(element);
      return { background: style.backgroundColor, radius: style.borderRadius, padding: style.padding, shadow: style.boxShadow, position: style.position };
    });
    expect.soft(look).toEqual({
      background: "rgb(255, 255, 255)", radius: "4px", padding: "4px", position: "fixed",
      shadow: "rgba(17, 20, 24, 0.1) 0px 0px 0px 1px, rgba(0, 0, 0, 0.1) 0px 20px 25px -5px, rgba(0, 0, 0, 0.1) 0px 10px 15px -3px",
    });
    const item = list.getByRole("button").first();
    const itemLook = await item.evaluate((element) => {
      const style = getComputedStyle(element);
      return { height: element.getBoundingClientRect().height, size: style.fontSize, line: Math.round(parseFloat(style.lineHeight)), rest: style.backgroundColor };
    });
    expect.soft(itemLook.height, "a menu item is at least 30px").toBeGreaterThanOrEqual(30);
    expect.soft({ size: itemLook.size, line: itemLook.line, rest: itemLook.rest })
      .toEqual({ size: "14px", line: 22, rest: "rgba(0, 0, 0, 0)" });
    await item.hover();
    await expect.soft(item).toHaveCSS("background-color", "rgba(143, 153, 168, 0.15)");
    expect.soft(await axeClean(page, ".workbench-status-strip"), "axe, with the unsaved list open").toEqual([]);

    // A scroll that leaves the button on screen carries the panel with it.
    expect(await nudgeStrip(unsaved), "nothing scrolled, so the panel had nothing to follow").toBeGreaterThan(0);
    await expect(async () => expectUnder(panel, unsaved), "the panel stayed where the button was").toPass({ timeout: 2_000 });
    await expect(list).toBeVisible();

    // The page laying out again moves the button with no scroll and no resize of its own:
    // the status before it growing, as it does when a check comes back.
    const badge = strip.locator(".badge").first();
    await badge.evaluate((element) => { element.style.paddingRight = "120px"; });
    await expect(async () => expectUnder(panel, unsaved), "the panel stayed where the button was before the strip moved it")
      .toPass({ timeout: 2_000 });
    await badge.evaluate((element) => { element.style.paddingRight = ""; });
    await expect(async () => expectUnder(panel, unsaved)).toPass({ timeout: 2_000 });

    // Under something drawn over it, as the narrow layout's sticky bar covers the strip
    // when the page scrolls, the button is out of sight and the panel goes with it.
    await strip.evaluate((element) => {
      const rect = element.getBoundingClientRect();
      const cover = document.createElement("div");
      cover.id = "menu-test-cover";
      Object.assign(cover.style, { position: "fixed", left: "0", width: "100vw", zIndex: "40", background: "#eee",
                                   top: `${rect.top - 40}px`, height: `${rect.height + 80}px` });
      document.body.appendChild(cover);
    });
    expect(await nudgeStrip(unsaved)).toBeGreaterThan(0);
    await expect(list, "the panel floated on over a bar that covers its button").toHaveCount(0);
    await page.evaluate(() => document.getElementById("menu-test-cover")?.remove());

    // Out of sight, the button takes its panel with it. The strip sits in no scroll box
    // that can hide it on this page, so the strip is moved out of the page's sight by
    // hand, which is what a pane's scroll box does to a button inside it: no scroll event
    // and no resize, only the button no longer seen.
    await unsaved.click();
    await expect(list).toBeVisible();
    await strip.evaluate((element) => { element.style.transform = "translateY(-2000px)"; });
    await expect(unsaved).not.toBeInViewport();
    await expect(list, "the panel floated on after its button scrolled away").toHaveCount(0);

    // A keyboard on a button out of sight opens nothing, and keeps its place.
    await unsaved.evaluate((element) => (element as HTMLElement).focus({ preventScroll: true }));
    await page.keyboard.press("ArrowDown");
    await expect(list).toHaveCount(0);
    await expect(unsaved, "ArrowDown on a button out of sight dropped focus to the page").toBeFocused();
  });

  test("The unsaved list keeps its own scroll when it is placed again", async ({ page }) => {
    await openFixture(page);
    const { unsaved } = await editNodes(page, ["a", "b"]);
    // Two items taller than the room under the strip, so the panel scrolls.
    await page.addStyleTag({ content: ".menu-panel li { min-height: 800px; }" });
    const panel = page.locator(".menu-panel");
    const list = page.getByRole("list", { name: "Unsaved changes" });
    await unsaved.focus();
    await page.keyboard.press("ArrowUp");
    await expect(list.getByRole("button", { name: /\(b\): configuration not saved/ })).toBeFocused();
    const before = await panel.evaluate((element) => element.scrollTop);
    expect(before, "the panel did not scroll to its last item, so there is no scroll to keep").toBeGreaterThan(100);
    expect(await nudgeStrip(unsaved)).toBeGreaterThan(0);
    await expect(async () => expectUnder(panel, unsaved), "the panel was not placed again").toPass({ timeout: 2_000 });
    expect(await panel.evaluate((element) => element.scrollTop), "placing the panel again scrolled it back to its top")
      .toBeGreaterThanOrEqual(before - 1);
  });

  test("Choosing an item, moving focus away, or pressing outside closes the unsaved list", async ({ page }) => {
    await openFixture(page);
    const { unsaved } = await editNodes(page, ["a", "b"]);
    const list = page.getByRole("list", { name: "Unsaved changes" });

    // Choosing: the item's action runs, the list closes, focus is back on the button.
    await unsaved.click();
    await list.getByRole("button", { name: /\(a\): configuration not saved/ }).click();
    await expect(list, "choosing an item left the list open").toHaveCount(0);
    await expect(unsaved, "choosing an item left focus in a panel that is gone").toBeFocused();
    await expect.poll(() => selected(page), "the chosen item's action did not run").toEqual(["a"]);

    // Focus moving to something outside closes it.
    await unsaved.click();
    await expect(list).toBeVisible();
    await page.keyboard.press("Shift+Tab");
    await expect(unsaved).not.toBeFocused();
    await expect(list, "focus left and the list stayed over the page").toHaveCount(0);

    // A press outside closes it; the strip's bare corner takes no focus.
    await unsaved.click();
    await expect(list).toBeVisible();
    await page.locator(".workbench-status-strip").click({ position: { x: 2, y: 2 } });
    await expect(list, "a press outside left the list open").toHaveCount(0);

    // Focus dropped to the page, as when the window loses it, leaves it open.
    await unsaved.click();
    await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
    await expect(list, "the list closed with focus going nowhere").toBeVisible();
  });

  test("Escape closes an open list and nothing else, and an Escape pressed outside it is the drag's", async ({ page }) => {
    await openFixture(page);
    const { unsaved } = await editNodes(page, ["a"]);
    const list = page.getByRole("list", { name: "Unsaved changes" });
    const lasso = page.locator(".canvas-lasso");
    await expect(unsaved).toBeInViewport();

    // Focus in the list. Enter would not open it: dnd-kit stops every click during a drag.
    await startLasso(page, ...LEFT_COLUMN);
    await unsaved.focus();
    await page.keyboard.press("ArrowDown");
    await expect(list).toBeVisible();
    await expect(list.getByRole("button").first()).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(list).toHaveCount(0);
    await expect(unsaved).toBeFocused();
    await expect(lasso, "the Escape that closed the list also cancelled the drag behind it").toBeVisible();
    await page.keyboard.press("Escape");
    await expect(lasso, "the drag was not live, so the first Escape proved nothing").toHaveCount(0);
    await finishLasso(page);

    // Focus outside the list: the Escape belongs to the drag, and the list stays.
    await startLasso(page, ...LEFT_COLUMN);
    await unsaved.focus();
    await page.keyboard.press("ArrowDown");
    await expect(list).toBeVisible();
    await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
    await page.keyboard.press("Escape");
    await expect(lasso, "an Escape pressed outside the list did not cancel the drag").toHaveCount(0);
    await expect(list, "the list took an Escape pressed outside it").toBeVisible();
    await finishLasso(page);
  });

  test("Escape on the unsaved list keeps the canvas selection, and choosing from the keyboard runs the item", async ({ page }) => {
    await openFixture(page);
    const { unsaved } = await editNodes(page, ["a"]);
    const list = page.getByRole("list", { name: "Unsaved changes" });
    await startLasso(page, ...LEFT_COLUMN);
    await finishLasso(page);
    await expect.poll(() => selected(page), "the lasso did not take the left column").toEqual(["a", "b"]);

    await unsaved.focus();
    await page.keyboard.press("ArrowDown");
    await expect(list.getByRole("button", { name: /\(a\): configuration not saved/ })).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(list).toHaveCount(0);
    await expect(unsaved).toBeFocused();
    expect(await selected(page), "the Escape that closed the list also cleared the selection").toEqual(["a", "b"]);

    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("Enter");
    await expect(list).toHaveCount(0);
    await expect(unsaved).toBeFocused();
    await expect.poll(() => selected(page), "Enter on an item did not run it").toEqual(["a"]);
  });

  test("The unsaved list does not come back open with the next typed change", async ({ page }) => {
    await openFixture(page);
    const { unsaved, label, original } = await editNodes(page, ["a"]);
    const list = page.getByRole("list", { name: "Unsaved changes" });
    await unsaved.click();
    await expect(list).toBeVisible();
    await label.fill(original);
    await expect(page.locator(".workbench-status-strip .saved-state")).toHaveText("Saved");
    await label.fill(`${original} renamed`);
    await expect(page.locator(".workbench-status-strip").getByRole("button", { name: "1 unsaved change" })).toBeVisible();
    await expect(list, "the list came back open").toHaveCount(0);
  });
});

/*
 * The Tooltip. Its adopters are the canvas's zoom buttons and edge inserts, and Workshop's
 * Layout, Duplicate node and Delete node: each had only a native title, which a keyboard
 * never shows and which, on Duplicate and Delete, was the button's only name.
 */

const OVERLAY_SHADOW = "rgba(17, 20, 24, 0.1) 0px 0px 0px 1px, rgba(0, 0, 0, 0.1) 0px 20px 25px -5px, rgba(0, 0, 0, 0.1) 0px 10px 15px -3px";

async function centre(locator: Locator) {
  const b = await box(locator);
  return { x: b.x + b.width / 2, y: b.y + b.height / 2 };
}

/** Whether a point is inside a box, give or take a pixel. */
function within(point: { x: number; y: number }, b: { x: number; y: number; width: number; height: number }) {
  return point.x >= b.x - 1 && point.x <= b.x + b.width + 1 && point.y >= b.y - 1 && point.y <= b.y + b.height + 1;
}

test.describe("GOAL_FOUNDATIONS A7, Tooltip", () => {
  test.beforeEach(({}, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-1280", "Checked once, on desktop; the fixtures are stateful.");
  });

  test("Hovering a zoom button shows the dark tooltip beside it once the pointer rests; it stays while hovered, and Escape hides it and moves nothing", async ({ page }) => {
    await openFixture(page);
    const canvas = page.locator(".pipeline-canvas");
    const zoomIn = canvas.getByRole("button", { name: "Zoom in", exact: true });
    const tip = page.getByRole("tooltip");
    await expect(zoomIn, "the native title would show beside the tooltip").not.toHaveAttribute("title");
    await zoomIn.scrollIntoViewIfNeeded();

    // It opens when the pointer rests, not while it sweeps across.
    const b = await box(zoomIn);
    await page.mouse.move(b.x + 2, b.y + b.height / 2);
    for (let x = 3; x < b.width - 2; x += 1) {
      await page.mouse.move(b.x + x, b.y + b.height / 2);
      await page.waitForTimeout(15);
    }
    await expect(tip, "the tooltip opened while the pointer was still moving").toHaveCount(0);
    await page.waitForTimeout(300);
    await expect(tip, "the pointer came to rest and nothing opened").toHaveText("Zoom in");
    await expect(tip).toHaveCount(1);
    expect(await tip.evaluate((element) => element.parentElement === document.body), "the bubble is not on the body").toBe(true);
    await expect(zoomIn, "a tooltip that repeats the name describes nothing").not.toHaveAttribute("aria-describedby");
    await expect(zoomIn).toHaveAccessibleName("Zoom in");
    let t = await box(tip);
    expect(Math.abs(t.x - (b.x + b.width) - 8), "the tooltip is not 8px right of its button").toBeLessThanOrEqual(1);
    expect(Math.abs((t.y + t.height / 2) - (b.y + b.height / 2)), "the tooltip is not centred on its button").toBeLessThanOrEqual(1);

    // UI_CONFIG's dark tooltip: #404854, #f6f7f9 14px/18px text, 8px 12px in, radius 4, over everything.
    const look = await tip.evaluate((element) => {
      const style = getComputedStyle(element);
      return { background: style.backgroundColor, color: style.color, padding: style.padding, radius: style.borderRadius,
               size: style.fontSize, line: Math.round(parseFloat(style.lineHeight)), shadow: style.boxShadow,
               position: style.position, layer: style.zIndex };
    });
    expect.soft(look).toEqual({ background: "rgb(64, 72, 84)", color: "rgb(246, 247, 249)", padding: "8px 12px", radius: "4px",
                                size: "14px", line: 18, shadow: OVERLAY_SHADOW, position: "fixed", layer: "1200" });

    // Hoverable: the pointer resting in the 8px gap is on the bubble's bridge, and it stays;
    // on the bubble, it stays. Persistent: it does not time out.
    const gap = { x: b.x + b.width + 4, y: b.y + b.height / 2 };
    await page.mouse.move(gap.x, gap.y, { steps: 2 });
    await page.waitForTimeout(300);
    await expect(tip, "the tooltip closed with the pointer resting in the gap").toBeVisible();
    expect(await page.evaluate(([x, y]) => Boolean(document.elementFromPoint(x, y)?.closest(".tooltip")), [gap.x, gap.y]),
           "the gap is not the bubble's").toBe(true);
    t = await box(tip);
    await page.mouse.move(t.x + t.width / 2, t.y + t.height / 2, { steps: 4 });
    await page.waitForTimeout(400);
    await expect(tip, "the tooltip closed as the pointer crossed onto it").toBeVisible();
    await page.waitForTimeout(1500);
    await expect(tip, "the tooltip timed out under the pointer").toBeVisible();

    // Dismissible: Escape hides it and moves neither focus nor the pointer.
    const before = await page.evaluateHandle(() => document.activeElement);
    await page.keyboard.press("Escape");
    await expect(tip).toHaveCount(0);
    expect(await page.evaluate((element) => document.activeElement === element, before), "Escape moved focus").toBe(true);

    // Back onto its button, it shows again.
    const onButton = await centre(zoomIn);
    await page.mouse.move(onButton.x, onButton.y, { steps: 4 });
    await expect(tip, "after Escape, coming back to the button did not show it again").toBeVisible();

    // A press shuts it, and a move on the pressed button does not bring it back; leaving
    // and coming back does.
    await zoomIn.click();
    await expect(tip).toHaveCount(0);
    await page.mouse.move(onButton.x + 3, onButton.y + 2, { steps: 2 });
    await page.waitForTimeout(300);
    await expect(tip, "a move on the button just pressed brought the tooltip back").toHaveCount(0);
    await page.mouse.move(0, 0, { steps: 4 });
    await page.mouse.move(onButton.x, onButton.y, { steps: 4 });
    await expect(tip, "coming back after a press did not show it").toBeVisible();
  });

  test("Keyboard focus shows a canvas tooltip, axe is clean while it shows, Enter and Space shut it, and blur hides it", async ({ page }) => {
    await openFixture(page);
    const canvas = page.locator(".pipeline-canvas");
    const zoomIn = canvas.getByRole("button", { name: "Zoom in", exact: true });
    const zoomOut = canvas.getByRole("button", { name: "Zoom out", exact: true });
    const tip = page.getByRole("tooltip");

    await zoomOut.focus();
    await page.keyboard.press("Shift+Tab");
    await expect(zoomIn).toBeFocused();
    await expect(tip, "keyboard focus did not show the tooltip").toHaveText("Zoom in");
    await expect(tip).toHaveCount(1);
    expect.soft(await axeClean(page, "[role='tooltip']", ".canvas-controls"), "axe, with a tooltip showing").toEqual([]);
    await page.keyboard.press("Tab");
    await expect(tip).toHaveText("Zoom out");
    await page.keyboard.press("Tab");
    await expect(tip).toHaveText("Fit to view");

    // Enter and Space, which start a keyboard drag where one can start, shut it.
    await page.keyboard.press("Enter");
    await expect(tip, "Enter left the tooltip showing").toHaveCount(0);
    await page.keyboard.press("Shift+Tab");
    await expect(tip).toHaveText("Zoom out");
    await page.keyboard.press(" ");
    await expect(tip, "Space left the tooltip showing").toHaveCount(0);

    await page.keyboard.press("Shift+Tab");
    await expect(tip).toHaveText("Zoom in");
    await page.evaluate(() => (document.activeElement as HTMLElement).blur());
    await expect(tip).toHaveCount(0);
  });

  test("A tooltip that adds to a button's name describes it at all times, and one that repeats it describes nothing", async ({ page }) => {
    await page.goto("/workspace/workshop");
    const create = page.getByRole("button", { name: "Create draft" });
    await expect(create.or(page.locator(".visual-builder-shell")).first()).toBeVisible();
    if (await create.isVisible()) await create.click();
    await expect(page.locator(".node-library-list button").first()).toBeVisible();
    const layout = page.getByRole("button", { name: "Layout", exact: true });
    const tip = page.getByRole("tooltip");
    await expect(layout).not.toHaveAttribute("title");
    // As its title did: heard by a screen reader's cursor, which moves no focus and opens no bubble.
    await expect(layout, "Layout's explanation is heard only while its bubble shows").toHaveAccessibleDescription("Auto-layout nodes");
    await expect(tip).toHaveCount(0);

    await layout.hover();
    await expect(tip).toHaveText("Auto-layout nodes");
    await expect(layout).toHaveAccessibleDescription("Auto-layout nodes");
    await page.mouse.move(0, 0);
    await expect(tip).toHaveCount(0);
    await expect(layout).toHaveAccessibleDescription("Auto-layout nodes");

    // Duplicate and Delete node had only a title for a name; they have one of their own now.
    await page.locator(".node-library-list button").first().click();
    const remove = page.getByRole("button", { name: "Delete node", exact: true });
    await expect(page.getByRole("button", { name: "Duplicate node", exact: true })).toHaveCount(1);
    await expect(remove).toHaveCount(1);
    await expect(remove).not.toHaveAttribute("title");
    await remove.hover();
    await expect(tip).toHaveText("Delete node");
    await expect(remove, "a tooltip that repeats the name describes nothing").not.toHaveAttribute("aria-describedby");
  });

  test("The edge insert's tooltip sits against it at the largest zoom, unscaled, and follows it when the zoom changes", async ({ page }) => {
    await openFixture(page);
    const canvas = page.locator(".pipeline-canvas");
    const tip = page.getByRole("tooltip");
    // The selected node's menu opens to its right; d's is clear of both inserts.
    await node(page, "d").click();
    const fit = canvas.getByRole("button", { name: "Fit to view", exact: true });
    await fit.click();
    for (let press = 0; press < 7; press += 1) await canvas.getByRole("button", { name: "Zoom in", exact: true }).click();
    const scale = () => page.locator(".canvas-stage").evaluate((stage) => Number(/scale\(([\d.]+)\)/.exec((stage as HTMLElement).style.transform)?.[1]));
    expect(await scale()).toBeCloseTo(1.35, 5);
    const inserts = canvas.getByRole("button", { name: "Insert selected node type" });
    await expect(inserts).toHaveCount(2);
    const insert = inserts.first();
    await insert.hover();
    await expect(tip).toHaveText("Insert selected node type");
    expect(await tip.evaluate((element) => element.parentElement === document.body)).toBe(true);
    const above = async () => {
      const t = await box(tip);
      const i = await box(insert);
      expect(Math.abs(i.y - (t.y + t.height) - 8), "the tooltip is not 8px above the insert").toBeLessThanOrEqual(1);
      expect(Math.abs((t.x + t.width / 2) - (i.x + i.width / 2)), "the tooltip is not centred over the insert").toBeLessThanOrEqual(1);
      expect(t.height, "the bubble was scaled with the stage").toBeLessThan(40);
    };
    await above();

    // Its bridge spans the gap above: the pointer resting there keeps it.
    const i = await box(insert);
    await page.mouse.move(i.x + i.width / 2, i.y - 4, { steps: 2 });
    await page.waitForTimeout(300);
    await expect(tip, "the tooltip closed with the pointer resting in the gap above the insert").toBeVisible();

    // From the keyboard, Up Arrow fits the canvas: the stage scales, nothing scrolls or
    // resizes, and the insert moves; the tooltip goes with it.
    await page.mouse.move(0, 0, { steps: 4 });
    await expect(tip).toHaveCount(0);
    await fit.focus();
    await page.keyboard.press("Tab");
    await expect(insert).toBeFocused();
    await expect(tip).toHaveText("Insert selected node type");
    await page.keyboard.press("ArrowUp");
    await expect.poll(scale, { message: "Up Arrow did not fit the canvas" }).toBeCloseTo(0.86, 5);
    await expect(async () => above(), "the tooltip stayed where the insert was before the zoom").toPass({ timeout: 2_000 });
  });

  test("A clipped insert's tooltip goes, even when the insert's middle lands where the bubble stood", async ({ page }) => {
    await openFixture(page);
    const canvas = page.locator(".pipeline-canvas");
    const tip = page.getByRole("tooltip");
    const insert = canvas.getByRole("button", { name: "Insert selected node type" }).first();
    await node(page, "d").click();
    await canvas.getByRole("button", { name: "Fit to view", exact: true }).focus();
    await page.keyboard.press("Tab");
    await expect(insert).toBeFocused();
    await expect(tip).toHaveText("Insert selected node type");

    // The insert just under the pane host's top edge, its tooltip above it, over the edge.
    const host = page.locator(".pane-host").first();
    const hostTop = (await box(host)).y;
    await host.evaluate((element, by) => { element.scrollTop += by; }, (await box(insert)).y - hostTop - 6);
    await expect(async () => {
      const t = await box(tip);
      expect(Math.abs((await box(insert)).y - (t.y + t.height) - 8)).toBeLessThanOrEqual(1);
    }, "the tooltip did not follow the insert up").toPass({ timeout: 2_000 });
    const stood = await box(tip);

    // 30px more and the insert's middle is above the edge, clipped, on the spot the bubble held.
    await host.evaluate((element) => { element.scrollTop += 30; });
    const middle = await centre(insert);
    expect(middle.y, "the insert's middle is not above the pane host's edge").toBeLessThan(hostTop);
    expect(within(middle, stood), "the insert's middle is not where the bubble stood, so this proves nothing").toBe(true);
    await expect(tip, "the bubble took itself for the insert and floated on").toHaveCount(0);
  });

  test("A drag that crosses a tooltip's button shows no tooltip", async ({ page }) => {
    await openFixture(page);
    const tip = page.getByRole("tooltip");
    // A button held down from bare page onto Zoom in: the pointer is on the button itself.
    const zoomIn = page.locator(".pipeline-canvas").getByRole("button", { name: "Zoom in", exact: true });
    await zoomIn.scrollIntoViewIfNeeded();
    const strip = await box(page.locator(".workbench-status-strip"));
    await page.mouse.move(strip.x + 2, strip.y + 2);
    await page.mouse.down();
    const onZoom = await centre(zoomIn);
    await page.mouse.move(onZoom.x, onZoom.y, { steps: 8 });
    expect(await page.evaluate(([x, y]) => document.elementFromPoint(x, y)?.getAttribute("aria-label"), [onZoom.x, onZoom.y]),
           "the held pointer is not on the button, so no tooltip proves nothing").toBe("Zoom in");
    await page.mouse.move(onZoom.x + 1, onZoom.y + 1, { steps: 2 });
    await page.waitForTimeout(400);
    await expect(tip, "a tooltip opened under a held button").toHaveCount(0);
    await page.mouse.move(0, 0, { steps: 4 });
    await page.mouse.up();

    // A lasso ending on an edge insert shows none either: its rectangle lies over what it
    // crosses. What this guards is the drag itself, which Escape still cancels.
    await showCanvas(page);
    await startLasso(page, [250, 380], [259, 283]);
    await page.waitForTimeout(400);
    await expect(tip, "a tooltip opened during a lasso").toHaveCount(0);
    await page.keyboard.press("Escape");
    await expect(page.locator(".canvas-lasso")).toHaveCount(0);
    await finishLasso(page);
  });

  test("A tooltip the keyboard opens during a live drag takes that Escape alone", async ({ page }) => {
    await openFixture(page);
    const canvas = page.locator(".pipeline-canvas");
    const tip = page.getByRole("tooltip");
    const lasso = page.locator(".canvas-lasso");
    await startLasso(page, ...LEFT_COLUMN);
    await canvas.getByRole("button", { name: "Zoom out", exact: true }).focus();
    await page.keyboard.press("Shift+Tab");
    await expect(tip).toHaveText("Zoom in");
    await page.keyboard.press("Escape");
    await expect(tip).toHaveCount(0);
    await expect(lasso, "the Escape that hid the tooltip also cancelled the drag").toBeVisible();
    await page.keyboard.press("Escape");
    await expect(lasso).toHaveCount(0);
    await finishLasso(page);
  });

  test("With focus elsewhere, Escape hides a hover tooltip and still reaches what has focus; the keyboard can open it again", async ({ page }) => {
    await openFixture(page);
    const canvas = page.locator(".pipeline-canvas");
    const tip = page.getByRole("tooltip");
    await page.getByRole("button", { name: "Search pipeline" }).click();
    const search = page.getByLabel("Find in pipeline");
    await expect(search).toBeFocused();
    // The zoom buttons sit at the canvas's foot, below what the pane host shows; brought
    // into view, focus stays in the search.
    const zoomIn = canvas.getByRole("button", { name: "Zoom in", exact: true });
    await zoomIn.scrollIntoViewIfNeeded();
    await expect(search).toBeFocused();
    const onZoom = await centre(zoomIn);
    await page.mouse.move(onZoom.x, onZoom.y, { steps: 4 });
    await expect(tip).toHaveText("Zoom in");
    await page.keyboard.press("Escape");
    await expect(tip).toHaveCount(0);
    await expect(search, "the tooltip took the Escape that belonged to the search").toHaveCount(0);

    // The mouse has not moved, and the keyboard arriving on the button is a new request.
    await canvas.getByRole("button", { name: "Zoom out", exact: true }).focus();
    await page.keyboard.press("Shift+Tab");
    await expect(zoomIn).toBeFocused();
    await expect(tip, "an Escape meant for the search kept the keyboard's tooltip shut").toHaveText("Zoom in");
  });

  test("A key that shut a hover tooltip does not keep the keyboard's tooltip shut", async ({ page }) => {
    await openFixture(page);
    const canvas = page.locator(".pipeline-canvas");
    const zoomIn = canvas.getByRole("button", { name: "Zoom in", exact: true });
    const tip = page.getByRole("tooltip");
    await zoomIn.scrollIntoViewIfNeeded();
    await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
    await zoomIn.hover();
    await expect(tip).toHaveText("Zoom in");
    // Enter with nothing focused shuts it, and nothing moves: the pointer stays on the
    // button, so nothing but the keyboard can open it again.
    await page.keyboard.press("Enter");
    await expect(tip).toHaveCount(0);
    const c = await centre(zoomIn);
    expect(await page.evaluate(([x, y]) => document.elementFromPoint(x, y)?.getAttribute("aria-label"), [c.x, c.y]),
           "the button moved from under the pointer, which reopens it on its own").toBe("Zoom in");
    await canvas.getByRole("button", { name: "Zoom out", exact: true }).focus();
    await page.keyboard.press("Shift+Tab");
    await expect(zoomIn).toBeFocused();
    await expect(tip, "a key pressed while hovering kept the keyboard's tooltip shut").toHaveText("Zoom in");
  });

  test("With nothing focused, a hover tooltip leaves Escape to the canvas, which clears its selection", async ({ page }) => {
    await openFixture(page);
    const canvas = page.locator(".pipeline-canvas");
    const tip = page.getByRole("tooltip");
    await startLasso(page, ...LEFT_COLUMN);
    await finishLasso(page);
    await expect.poll(() => selected(page), "the lasso did not take the left column").toEqual(["a", "b"]);
    const zoomIn = canvas.getByRole("button", { name: "Zoom in", exact: true });
    await zoomIn.scrollIntoViewIfNeeded();
    await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
    await zoomIn.hover();
    await expect(tip).toHaveText("Zoom in");
    await page.keyboard.press("Escape");
    await expect(tip).toHaveCount(0);
    await expect.poll(() => selected(page), "the tooltip took the Escape that clears the selection").not.toEqual(["a", "b"]);
  });

  test("A finger or a page moving under the pointer opens nothing; a tooltip follows a scroll, and goes when blurred or clipped", async ({ page }) => {
    await openFixture(page);
    const canvas = page.locator(".pipeline-canvas");
    const zoomIn = canvas.getByRole("button", { name: "Zoom in", exact: true });
    const zoomOut = canvas.getByRole("button", { name: "Zoom out", exact: true });
    const tip = page.getByRole("tooltip");
    const host = page.locator(".pane-host").first();
    await zoomIn.scrollIntoViewIfNeeded();
    await zoomIn.evaluate((element) => {
      for (const type of ["pointerover", "pointerenter", "pointermove", "pointermove"]) {
        element.dispatchEvent(new PointerEvent(type, { pointerType: "touch", bubbles: type !== "pointerenter", isPrimary: true }));
      }
    });
    await page.waitForTimeout(400);
    await expect(tip, "a touch opened a tooltip").toHaveCount(0);

    // The pointer resting on bare canvas 40px above the button; the pane host scrolled 40px
    // brings the button under it. Nothing moved the pointer, so nothing opens, until it moves.
    const c = await centre(zoomIn);
    await page.mouse.move(c.x, c.y - 40, { steps: 2 });
    await page.waitForTimeout(200);
    await host.evaluate((element) => { element.scrollTop += 40; });
    await expect.poll(async () => (await centre(zoomIn)).y, { message: "the pane host did not bring the button under the pointer" })
      .toBeCloseTo(c.y - 40, 0);
    await page.waitForTimeout(400);
    await expect(tip, "the page moving under a resting pointer opened a tooltip").toHaveCount(0);
    await page.mouse.move(c.x + 1, c.y - 40);
    await expect(tip, "a real move on the button did not open it").toHaveText("Zoom in");

    // Opened from the keyboard, with the pointer out of the way, so a scroll moves no hover.
    await page.mouse.move(0, 0, { steps: 4 });
    await expect(tip).toHaveCount(0);
    await zoomOut.focus();
    await page.keyboard.press("Shift+Tab");
    await expect(tip).toHaveText("Zoom in");
    const beside = async () => {
      const t = await box(tip);
      const b = await box(zoomIn);
      expect(Math.abs(t.x - (b.x + b.width) - 8), "the tooltip is not beside its button").toBeLessThanOrEqual(1);
      expect(Math.abs((t.y + t.height / 2) - (b.y + b.height / 2)), "the tooltip is not level with its button").toBeLessThanOrEqual(1);
    };

    // The pane host scrolled a little: the button moves and stays in sight, and the tooltip goes along.
    const moved = await host.evaluate((element) => {
      const before = element.scrollTop;
      element.scrollTop = before + 30;
      if (element.scrollTop === before) element.scrollTop = before - 30;
      return Math.abs(element.scrollTop - before);
    });
    expect(moved, "the pane host did not scroll").toBeGreaterThan(0);
    await expect(async () => beside(), "the tooltip stayed where its button was").toPass({ timeout: 2_000 });
    await expect(tip).toBeVisible();

    // The window losing focus takes it away.
    await page.evaluate(() => window.dispatchEvent(new Event("blur")));
    await expect(tip, "the tooltip stayed with the window blurred").toHaveCount(0);
    await zoomOut.focus();
    await page.keyboard.press("Shift+Tab");
    await expect(tip).toHaveText("Zoom in");

    // Scrolled up past the pane host's top edge, the button is clipped while still inside
    // the window, so only a check of what is at its middle can tell; the tooltip goes.
    const b = await box(zoomIn);
    await host.evaluate((element, by) => { element.scrollTop += by; }, b.y + b.height - (await box(host)).y + 40);
    await expect(zoomIn, "the button is still in sight, so this proves nothing").not.toBeInViewport();
    expect((await box(zoomIn)).y, "the button left the window, which the edge check alone catches").toBeGreaterThan(0);
    await expect(tip, "the tooltip floated on after its button was scrolled out of sight").toHaveCount(0);
  });
});

test.describe("GOAL_FOUNDATIONS A7, Tooltip on a touch screen", () => {
  test.use({ hasTouch: true });
  test.beforeEach(({}, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-1280", "Checked once, on desktop; the fixtures are stateful.");
  });

  test("A tap never opens a tooltip", async ({ page }) => {
    await openFixture(page);
    const zoomIn = page.locator(".pipeline-canvas").getByRole("button", { name: "Zoom in", exact: true });
    await zoomIn.scrollIntoViewIfNeeded();
    const c = await centre(zoomIn);
    await page.touchscreen.tap(c.x, c.y);
    await page.waitForTimeout(400);
    await expect(page.getByRole("tooltip"), "a tap opened a tooltip").toHaveCount(0);
  });
});
