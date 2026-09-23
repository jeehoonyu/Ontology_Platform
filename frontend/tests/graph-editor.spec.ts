import { expect, test, type Page } from "@playwright/test";

/**
 * The pipeline canvas worked the way the original's graph editor does.
 * `GOAL_GRAPH_2026-09-23.md`.
 *
 * Each test builds its own pipeline through the API, with nodes at positions it
 * chooses, and opens it from the Outputs pane. A graph a test did not make is one
 * whose shape it cannot know, and a lasso aimed at a node that is somewhere else
 * selects nothing and passes.
 *
 * The selection is read from the nodes themselves: `data-in-selection` is on the
 * nodes every tool acts on, which is the set, or the one node last clicked when the
 * set is empty. The `.selected` class was both, and could not say which.
 */

interface FixtureNode { id: string; x: number; y: number }

/**
 * Four nodes in two rows, edges a→c and b→d, so a region can take the left column
 * without the right one, and parents and children are one edge away. Placed inside
 * what the canvas shows at 1280 -- 489px at zoom 0.86, 568 stage pixels -- and clear
 * of the legend in its top right corner, which a lasso must not start on.
 */
const FOUR: FixtureNode[] = [
  { id: "a", x: 40, y: 60 },
  { id: "b", x: 40, y: 250 },
  { id: "c", x: 300, y: 60 },
  { id: "d", x: 300, y: 250 },
];

async function openFixture(page: Page, nodes: FixtureNode[] = FOUR,
                           edges: Array<[string, string]> = [["a", "c"], ["b", "d"]]) {
  const suffix = `${Date.now()}${Math.floor(Math.random() * 1000)}`;
  const name = `Graph fixture ${suffix}`;
  const created = await page.request.post("/pipeline-builder/graphs", { data: {
    id: `graph_fixture_${suffix}`,
    display_name: name,
    nodes: nodes.map((node) => ({ id: node.id, type: "filter", config: {}, position: { x: node.x, y: node.y } })),
    edges: edges.map(([source, target]) => ({ source, target })),
  } });
  expect(created.ok(), `the fixture pipeline was not created: ${created.status()}`).toBeTruthy();
  await page.goto("/workspace/pipeline");
  await page.getByRole("button", { name: "Reset panes" }).click();
  const outputs = page.getByRole("button", { name: "Pane actions for Outputs" });
  const row = page.locator(".output-rail .resource-row").filter({ hasText: name });
  if (!(await row.isVisible()) && await outputs.count()) await outputs.click();
  await row.click();
  await expect(page.locator(".workspace-header")).toContainText(name);
  const canvas = page.locator(".pipeline-canvas");
  await expect(canvas.locator(".pipeline-node")).toHaveCount(nodes.length);
  await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {});
  // Opening the pipeline from the Outputs pane scrolled the workspace to that row,
  // and a pointer gesture aimed at the canvas then landed 1,260px above the screen.
  await canvas.evaluate((element) => {
    element.scrollLeft = 0;
    element.scrollTop = 0;
    element.scrollIntoView({ block: "start" });
  });
  return { name, canvas };
}

/** The ids every tool would act on, read from the nodes. */
function selected(page: Page) {
  return page.locator(".pipeline-canvas .pipeline-node[data-in-selection='true']")
    .evaluateAll((nodes) => nodes.map((node) => node.getAttribute("data-node-id") || "").sort());
}

function node(page: Page, id: string) {
  return page.locator(`.pipeline-canvas .pipeline-node[data-node-id='${id}']`);
}

/** Records every request the page sends from now on. */
function requests(page: Page) {
  const sent: string[] = [];
  page.on("request", (request) => {
    if (!request.url().includes("/assets/")) sent.push(`${request.method()} ${new URL(request.url()).pathname}`);
  });
  return sent;
}

test.describe("the selection is one set, and every tool writes it", () => {
  test.beforeEach(async ({}, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-1280", "Runs once; the fixtures are stateful.");
  });

  test("Select all, parents and children write the one selection and send nothing", async ({ page }) => {
    await openFixture(page);
    await node(page, "c").click();
    await expect.poll(() => selected(page)).toEqual(["c"]);
    await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {});
    const sent = requests(page);

    await page.getByRole("button", { name: "Select parents" }).click();
    await expect.poll(() => selected(page), { message: "Select parents did not add c's parent" }).toEqual(["a", "c"]);

    await page.getByRole("button", { name: "Select all" }).click();
    await expect.poll(() => selected(page), { message: "Select all did not select every node" })
      .toEqual(["a", "b", "c", "d"]);
    await expect(page.locator(".canvas-selection-count")).toHaveText("4 of 4 selected");

    await page.keyboard.press("Escape");
    await expect.poll(() => selected(page)).toEqual(["c"]);
    await page.getByRole("button", { name: "Select children" }).click();
    await expect.poll(() => selected(page), { message: "Select children added something other than nothing" })
      .toEqual(["c"]);

    await page.waitForTimeout(300);
    expect(sent, "selecting sent requests; a selection is a view of the graph, not an edit").toEqual([]);
  });

  test("Ctrl+A, Ctrl+E and Ctrl+D do what their buttons do", async ({ page }) => {
    await openFixture(page);
    await node(page, "a").click();
    await expect.poll(() => selected(page)).toEqual(["a"]);

    await page.keyboard.press("Control+d");
    await expect.poll(() => selected(page), { message: "Ctrl+D did not select a's children" }).toEqual(["a", "c"]);

    await node(page, "d").click();
    await page.keyboard.press("Control+e");
    await expect.poll(() => selected(page), { message: "Ctrl+E did not select d's parents" }).toEqual(["b", "d"]);

    await page.keyboard.press("Control+a");
    await expect.poll(() => selected(page), { message: "Ctrl+A did not select every node" })
      .toEqual(["a", "b", "c", "d"]);
  });

  test("a key typed into a field is the field's", async ({ page }) => {
    await openFixture(page);
    await node(page, "a").click();
    const label = page.getByLabel("Node label");
    await label.fill("keep this text");
    await label.press("Control+a");
    await expect.poll(() => selected(page), { message: "Ctrl+A in a field selected nodes" }).toEqual(["a"]);
  });
});


/**
 * A region of the canvas selects with a drag. X2 of `GOAL_GRAPH_2026-09-23.md`.
 *
 * Points are chosen in stage pixels -- the coordinates node positions are stored
 * in -- and turned into screen points through the stage's own box and zoom, so the
 * rectangle is where the fixture's nodes are whatever the pane's width.
 */
async function stageToScreen(page: Page, x: number, y: number) {
  return page.locator(".canvas-stage").evaluate((stage, [px, py]) => {
    const box = stage.getBoundingClientRect();
    const zoom = box.width / (stage as HTMLElement).offsetWidth;
    return { x: box.left + px * zoom, y: box.top + py * zoom };
  }, [x, y] as const);
}

/** Presses on bare canvas at one stage point and drags to another, live, not released. */
async function startLasso(page: Page, from: [number, number], to: [number, number], shift = false) {
  const start = await stageToScreen(page, ...from);
  const end = await stageToScreen(page, ...to);
  await page.mouse.move(start.x, start.y);
  if (shift) await page.keyboard.down("Shift");
  await page.mouse.down();
  for (let step = 1; step <= 12; step += 1) {
    await page.mouse.move(start.x + ((end.x - start.x) * step) / 12, start.y + ((end.y - start.y) * step) / 12);
    await page.waitForTimeout(16);
  }
  // Live before anything is judged: a rectangle that never started selects nothing
  // and would pass every assertion about Escape below.
  await expect(page.locator(".canvas-lasso"), "the lasso never started").toBeVisible();
}

async function finishLasso(page: Page, shift = false) {
  await page.mouse.up();
  if (shift) await page.keyboard.up("Shift");
  // dnd-kit swallows the click that follows a drop for 50ms.
  await page.waitForTimeout(150);
}

// The left column holds a (centre 126,89) and b (126,279); the right, c (386,89) and d.
const LEFT_COLUMN: [[number, number], [number, number]] = [[10, 30], [240, 340]];
const TOP_RIGHT: [[number, number], [number, number]] = [[250, 30], [520, 160]];

test.describe("a region of the canvas selects with a drag", () => {
  test.beforeEach(async ({}, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-1280", "Runs once; the lasso is a desktop pointer gesture.");
  });

  test("a lasso selects the nodes inside it and Escape selects nothing", async ({ page }) => {
    await openFixture(page);
    const writes: string[] = [];
    page.on("request", (request) => { if (request.method() !== "GET") writes.push(request.url()); });

    await startLasso(page, ...LEFT_COLUMN);
    await expect(page.locator(".pipeline-canvas"), "a lasso lit the drop outline, as if something could land")
      .not.toHaveClass(/\bdrag-active\b/);
    await finishLasso(page);
    await expect.poll(() => selected(page), { message: "the lasso did not select the left column" })
      .toEqual(["a", "b"]);

    await startLasso(page, ...TOP_RIGHT);
    await page.keyboard.press("Escape");
    await page.mouse.up();
    await page.waitForTimeout(150);
    await expect(page.locator(".canvas-lasso"), "Escape left the rectangle drawn").toHaveCount(0);
    const after = await selected(page);
    expect(after, "a lasso cancelled with Escape selected what it was over").not.toContain("c");
    expect(writes, "a lasso wrote something; it selects, and a selection is not an edit").toEqual([]);
    await expect(page.locator(".pipeline-canvas .pipeline-node"), "a lasso created a node").toHaveCount(4);
  });

  test("Shift held when a lasso begins adds to the selection", async ({ page }) => {
    await openFixture(page);
    await startLasso(page, ...LEFT_COLUMN);
    await finishLasso(page);
    await expect.poll(() => selected(page)).toEqual(["a", "b"]);

    await startLasso(page, ...TOP_RIGHT, true);
    await finishLasso(page, true);
    await expect.poll(() => selected(page), { message: "a Shift lasso replaced the selection" })
      .toEqual(["a", "b", "c"]);

    await startLasso(page, ...TOP_RIGHT);
    await finishLasso(page);
    await expect.poll(() => selected(page), { message: "a plain lasso added instead of replacing" })
      .toEqual(["c"]);
  });

  test("the nodes a lasso selects can be selected without a drag", async ({ page }) => {
    // WCAG 2.5.7: a single pointer and no drag. Shift+click builds the same set.
    await openFixture(page);
    await node(page, "a").click();
    await node(page, "b").click({ modifiers: ["Shift"] });
    await expect.poll(() => selected(page), { message: "Shift+click did not build the lasso's selection" })
      .toEqual(["a", "b"]);
  });
});

/**
 * One command lays out the pipeline, and one undo puts it back. X3 of
 * `GOAL_GRAPH_2026-09-23.md`. Positions are read as committed -- `style.left` and
 * `style.top`, never a bounding box -- for the reason `GOAL_DRAG` L8 records.
 */
test.describe("one command lays out the pipeline", () => {
  test.beforeEach(async ({}, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-1280", "Runs once; the fixtures are stateful.");
  });

  const position = (page: Page, id: string) => node(page, id).evaluate((element) => {
    const style = (element as HTMLElement).style;
    return { x: Number.parseFloat(style.left) || 0, y: Number.parseFloat(style.top) || 0 };
  });

  test("auto layout moves every node and one Undo restores every position", async ({ page }) => {
    // Out of order on purpose: a flows into b and d, b into c, and nothing is where
    // its layer would put it.
    const messy: FixtureNode[] = [
      { id: "a", x: 300, y: 300 }, { id: "b", x: 40, y: 40 }, { id: "c", x: 200, y: 420 }, { id: "d", x: 420, y: 60 },
    ];
    await openFixture(page, messy, [["a", "b"], ["b", "c"], ["a", "d"]]);
    const before = Object.fromEntries(await Promise.all(messy.map(async (item) => [item.id, await position(page, item.id)])));
    const layouts: string[] = [];
    page.on("request", (request) => {
      if (request.method() === "PATCH" && request.url().includes("/layout")) layouts.push(request.url());
    });

    await page.getByRole("button", { name: "Auto layout" }).click();
    await expect(page.locator(".workbench-status-strip")).toContainText("Laid out 4 nodes.");

    // Layer 0 is a; layer 1 is b above d, the order they already had; layer 2 is c.
    const expected: Record<string, { x: number; y: number }> = {
      a: { x: 40, y: 60 }, b: { x: 300, y: 60 }, d: { x: 300, y: 170 }, c: { x: 560, y: 60 },
    };
    for (const [id, at] of Object.entries(expected)) {
      await expect.poll(() => position(page, id), { message: `auto layout did not place ${id} in its layer` })
        .toEqual(at);
    }
    expect(layouts, "auto layout was not one save").toHaveLength(1);

    await page.getByRole("button", { name: "Undo move" }).click();
    await expect(page.locator(".workbench-status-strip")).toContainText("Moved 4 nodes back.");
    for (const item of messy) {
      await expect.poll(() => position(page, item.id), { message: `one Undo did not put ${item.id} back` })
        .toEqual(before[item.id]);
    }
    expect(layouts, "the undo was not one save").toHaveLength(2);
    await expect(page.getByRole("button", { name: "Undo move" }), "one undo left more to undo").toBeDisabled();
  });
});

/**
 * Every hotkey has a button, and the reference is the wiring. X4 of
 * `GOAL_GRAPH_2026-09-23.md`.
 *
 * The test reads `View hotkeys` and nothing else to learn what the keys are, then
 * for each row checks that the button it names is on the page, and that pressing the
 * key gives what clicking the button gives. The keys the goal names are checked for
 * by name, so a row taken out of the table fails here because the reference -- drawn
 * from the same table -- no longer lists it.
 */
const EXPECTED_KEYS = ["Ctrl+A", "Ctrl+E", "Ctrl+D", "Ctrl+F", "Up Arrow"];

const PRESS: Record<string, string> = {
  "Ctrl+A": "Control+a", "Ctrl+E": "Control+e", "Ctrl+D": "Control+d", "Ctrl+F": "Control+f",
  "Up Arrow": "ArrowUp",
};

const zoomOf = (page: Page) => page.locator(".canvas-stage").evaluate((stage) =>
  Number(/scale\(([\d.]+)\)/.exec((stage as HTMLElement).style.transform)?.[1] || 0));

/** How to put the canvas in a known state for a row, and what to read after it. */
const OUTCOMES: Record<string, { reset: (page: Page) => Promise<void>; read: (page: Page) => Promise<unknown> }> = {
  "Select all": { reset: (page) => node(page, "a").click(), read: selected },
  "Select parents": { reset: (page) => node(page, "c").click(), read: selected },
  "Select children": { reset: (page) => node(page, "a").click(), read: selected },
  "Search pipeline": {
    reset: async (page) => {
      const close = page.getByRole("button", { name: "Close search" });
      if (await close.count()) await close.click();
      await node(page, "a").click();
    },
    read: (page) => page.getByLabel("Find in pipeline").evaluate((box) => box === document.activeElement),
  },
  "Fit to view": {
    reset: async (page) => {
      await page.getByRole("button", { name: "Zoom in" }).click();
      await page.getByRole("button", { name: "Zoom in" }).click();
      await node(page, "a").click();
    },
    read: zoomOf,
  },
};

test.describe("every hotkey has a button, and the reference is the wiring", () => {
  test.beforeEach(async ({}, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-1280", "Runs once; the fixtures are stateful.");
  });

  test("the hotkeys reference lists the table, and each key does what its button does", async ({ page }) => {
    await openFixture(page);
    await page.getByRole("button", { name: "View hotkeys" }).click();
    const reference = page.getByRole("dialog", { name: "Hotkeys" });
    await expect(reference).toBeVisible();
    const rows = await reference.locator("tbody tr").evaluateAll((trs) =>
      trs.map((tr) => Array.from(tr.querySelectorAll("td")).map((cell) => (cell.textContent || "").trim())));
    const keys = rows.map((row) => row[0]);
    for (const expected of EXPECTED_KEYS) {
      expect(keys, `the hotkeys reference does not list ${expected}`).toContain(expected);
    }
    await page.keyboard.press("Escape");
    await expect(reference, "Escape did not close the reference").toHaveCount(0);
    await expect(page.getByRole("button", { name: "View hotkeys" }), "closing lost the focus").toBeFocused();

    for (const [keysText, label, button] of rows) {
      const outcome = OUTCOMES[label];
      expect(outcome, `the reference lists "${label}", which this test has no way to observe`).toBeTruthy();
      await expect(page.getByRole("button", { name: button, exact: true }),
                   `${keysText} names a button, "${button}", that is not on the page`).toHaveCount(1);

      await outcome.reset(page);
      await page.getByRole("button", { name: button, exact: true }).click();
      const byButton = await outcome.read(page);

      await outcome.reset(page);
      await page.keyboard.press(PRESS[keysText] || keysText);
      await expect.poll(() => outcome.read(page), { message: `${keysText} did not do what ${button} does` })
        .toEqual(byButton);
    }
  });

  test("a search selects what matches, and a tool used after it takes that", async ({ page }) => {
    await openFixture(page);
    await page.getByRole("button", { name: "Search pipeline" }).click();
    const box = page.getByLabel("Find in pipeline");
    await expect(box, "the search box did not take the focus").toBeFocused();
    await box.fill("c");
    await expect.poll(() => selected(page), { message: "the search did not select the node it matched" })
      .toEqual(["c"]);
    await expect(page.locator(".canvas-search-count")).toHaveText("1 of 4 match");
    await page.getByRole("button", { name: "Select parents" }).click();
    await expect.poll(() => selected(page), { message: "a tool after a search did not take what it found" })
      .toEqual(["a", "c"]);
  });
});

test.describe("a hotkey never takes a key a drag is using", () => {
  test.beforeEach(async ({}, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-1280", "Runs once; the fixtures are stateful.");
  });

  test("Up Arrow during a keyboard drag moves the node, not the zoom", async ({ page }) => {
    // Up Arrow fits the view, and it is also how a keyboard drag moves a node up.
    // The drag handles it first and prevents its default; this proves the hotkey
    // then leaves it alone rather than refitting the canvas under the drag.
    await openFixture(page);
    await page.getByRole("button", { name: "Zoom in" }).click();
    await page.getByRole("button", { name: "Zoom in" }).click();
    const zoomBefore = await zoomOf(page);
    expect(zoomBefore, "the zoom did not leave the fitted level").not.toBe(0.86);
    const topOf = () => node(page, "b").evaluate((element) => Number.parseFloat((element as HTMLElement).style.top) || 0);
    const before = await topOf();

    await node(page, "b").focus();
    const announcement = page.locator("[id^='DndLiveRegion']").filter({ hasText: /node:/ });
    await page.keyboard.press("Space");
    await expect(announcement, "the keyboard drag never started").toContainText(/draggable item/i);
    for (let step = 0; step < 2; step += 1) {
      await page.keyboard.press("ArrowUp");
      await page.waitForTimeout(60);
    }
    expect(await zoomOf(page), "Up Arrow refitted the canvas in the middle of a drag").toBe(zoomBefore);
    await page.keyboard.press("Space");
    await expect.poll(topOf, { message: "the keyboard drag did not move the node up" }).toBeLessThan(before);
    expect(await zoomOf(page), "Up Arrow refitted the canvas after the drag").toBe(zoomBefore);
  });
});
