import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Locator, type Page } from "@playwright/test";

/**
 * Overlays hold focus while open, close on Escape, and give focus back to what opened
 * them. `GOAL_FOUNDATIONS_2026-09-25.md` A7: the Dialog, then the Menu.
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
