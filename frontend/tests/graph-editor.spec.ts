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
  const id = `graph_fixture_${suffix}`;
  const created = await page.request.post("/pipeline-builder/graphs", { data: {
    id,
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
  return { id, name, canvas };
}

/** The status strip's message. */
function status(page: Page) {
  return page.locator(".workbench-status-strip .strip-message");
}

/**
 * The requests that edit a graph. A node's preview and suggestions are reads the
 * canvas sends as POST whenever the node it details changes; they are not edits.
 */
function edits(page: Page) {
  const sent: string[] = [];
  page.on("request", (request) => {
    const path = new URL(request.url()).pathname;
    if (request.method() === "GET" || /\/(preview|suggestions)$/.test(path)) return;
    sent.push(`${request.method()} ${path}`);
  });
  return sent;
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
const EXPECTED_KEYS = ["Ctrl+A", "Ctrl+E", "Ctrl+D", "Ctrl+F", "Up Arrow", "Ctrl+C", "Ctrl+V", "Delete",
                       "Ctrl+H", "Ctrl+Shift+H"];

const PRESS: Record<string, string> = {
  "Ctrl+A": "Control+a", "Ctrl+E": "Control+e", "Ctrl+D": "Control+d", "Ctrl+F": "Control+f",
  "Up Arrow": "ArrowUp", "Ctrl+C": "Control+c", "Ctrl+V": "Control+v", "Delete": "Delete",
  "Ctrl+H": "Control+h", "Ctrl+Shift+H": "Control+Shift+h",
};

const shownCount = (page: Page) => page.locator(".pipeline-canvas .pipeline-node").count();

const zoomOf = (page: Page) => page.locator(".canvas-stage").evaluate((stage) =>
  Number(/scale\(([\d.]+)\)/.exec((stage as HTMLElement).style.transform)?.[1] || 0));

const nodeCount = (page: Page) => page.locator(".pipeline-canvas .pipeline-node").count();

/**
 * How to put the canvas in a known state for a row, and what to read after it. What
 * `reset` returns is handed to `read`, so a row that changes the graph is read as the
 * change since its reset, and a result left over from the run before cannot pass.
 */
const OUTCOMES: Record<string, { reset: (page: Page) => Promise<unknown>; read: (page: Page, before: unknown) => Promise<unknown> }> = {
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
  // Copy is read off the clipboard, which the reset empties; paste and delete as the
  // number of nodes they added or took away since their reset. Delete is set up by a
  // paste, which leaves the one node it added selected.
  "Copy": {
    reset: async (page) => {
      await page.evaluate(() => navigator.clipboard.writeText(""));
      await node(page, "a").click();
    },
    // Each read waits for its change to happen: a read taken before an asynchronous
    // copy or paste has landed would compare two nothings and pass.
    read: async (page) => {
      await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).not.toBe("");
      const text = await page.evaluate(() => navigator.clipboard.readText());
      return JSON.parse(text).nodes.map((item: { id: string }) => item.id);
    },
  },
  "Paste": {
    reset: async (page) => nodeCount(page),
    read: async (page, before) => {
      await expect.poll(() => nodeCount(page)).toBeGreaterThan(before as number);
      return (await nodeCount(page)) - (before as number);
    },
  },
  "Delete selected": {
    reset: async (page) => {
      const before = await nodeCount(page);
      await page.getByRole("button", { name: "Paste", exact: true }).click();
      await expect.poll(() => nodeCount(page)).toBe(before + 1);
      return before + 1;
    },
    read: async (page, before) => {
      await expect.poll(() => nodeCount(page)).toBeLessThan(before as number);
      return (before as number) - (await nodeCount(page));
    },
  },
  // Hiding changes what the canvas shows and nothing else, so both are read from it.
  "Hide selected": {
    reset: async (page) => {
      const showAll = page.getByRole("button", { name: "Show all", exact: true });
      if (await showAll.count()) await showAll.click();
      await node(page, "a").click();
      return shownCount(page);
    },
    read: async (page, before) => {
      await expect.poll(() => shownCount(page)).toBeLessThan(before as number);
      return (before as number) - (await shownCount(page));
    },
  },
  "Show all": {
    reset: async (page) => {
      const showAll = page.getByRole("button", { name: "Show all", exact: true });
      if (await showAll.count()) await showAll.click();
      await node(page, "a").click();
      await page.getByRole("button", { name: "Hide selected", exact: true }).click();
      await expect(page.locator(".canvas-hidden-note")).toBeVisible();
      return shownCount(page);
    },
    read: async (page, before) => {
      await expect.poll(() => shownCount(page)).toBeGreaterThan(before as number);
      return (await shownCount(page)) - (before as number);
    },
  },
};

test.describe("every hotkey has a button, and the reference is the wiring", () => {
  test.use({ permissions: ["clipboard-read", "clipboard-write"] });
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

      const beforeButton = await outcome.reset(page);
      await expect(page.getByRole("button", { name: button, exact: true }),
                   `${keysText} names a button, "${button}", that is not on the page`).toHaveCount(1);
      await page.getByRole("button", { name: button, exact: true }).click();
      const byButton = await outcome.read(page, beforeButton);

      const beforeKey = await outcome.reset(page);
      await page.keyboard.press(PRESS[keysText] || keysText);
      await expect.poll(() => outcome.read(page, beforeKey), { message: `${keysText} did not do what ${button} does` })
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

/**
 * Nodes copy and paste, within and across pipelines, as one batch. X5 of
 * `GOAL_GRAPH_2026-09-23.md`. The clipboard is the system's, read back here to show
 * what a copy put on it; what a paste made is read from the server, not the screen.
 */
test.describe("nodes copy and paste as one batch", () => {
  test.use({ permissions: ["clipboard-read", "clipboard-write"] });
  test.beforeEach(async ({}, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-1280", "Runs once; the fixtures are stateful.");
  });

  test("three copied nodes paste into a second pipeline with their edges", async ({ page }) => {
    const chain: FixtureNode[] = [
      { id: "a", x: 40, y: 60 }, { id: "b", x: 300, y: 60 }, { id: "c", x: 40, y: 250 }, { id: "d", x: 300, y: 250 },
    ];
    await openFixture(page, chain, [["a", "b"], ["b", "c"]]);
    await node(page, "a").click();
    await node(page, "b").click({ modifiers: ["Shift"] });
    await node(page, "c").click({ modifiers: ["Shift"] });
    await expect.poll(() => selected(page)).toEqual(["a", "b", "c"]);
    await page.getByRole("button", { name: "Copy", exact: true }).click();
    await expect(status(page)).toHaveText("Copied 3 nodes and 2 edges.");
    const onClipboard = JSON.parse(await page.evaluate(() => navigator.clipboard.readText()));
    expect(onClipboard.kind, "the clipboard does not hold pipeline nodes").toBe("ontology-platform/pipeline-nodes");
    expect(onClipboard.nodes.map((item: { id: string }) => item.id).sort()).toEqual(["a", "b", "c"]);
    expect(onClipboard.edges, "the copy dropped the edges between the nodes").toHaveLength(2);

    // A second pipeline, opened in a fresh page load: the copy has to come back from
    // the system clipboard, not from anything this page kept.
    const second = await openFixture(page, [{ id: "only", x: 40, y: 400 }], []);
    const sent = edits(page);
    // Opening the pipeline left the focus on its row in the Outputs pane, and a key
    // pressed there is the pane's. A click on bare canvas gives the keys to the canvas.
    const box = await page.locator(".canvas-stage").boundingBox();
    await page.mouse.click(box!.x + 20, box!.y + 20);
    await page.keyboard.press("Control+v");
    await expect(status(page)).toHaveText("Pasted 3 nodes.");
    await expect(page.locator(".pipeline-canvas .pipeline-node")).toHaveCount(4);
    expect(sent, "the paste was not one command batch").toEqual([`POST /pipeline-builder/graphs/${second.id}/commands`]);

    const stored = await (await page.request.get(`/pipeline-builder/graphs/${second.id}`)).json();
    const pasted = stored.nodes.filter((item: { id: string }) => item.id !== "only");
    expect(pasted, "three nodes did not land in the second pipeline").toHaveLength(3);
    // Every fixture node is a Filter with the same label, so a pasted node is told
    // from the others by where it landed: 40px down and right of its original.
    const at = (x: number, y: number) => pasted.find((item: { position: { x: number; y: number } }) =>
      item.position.x === x + 40 && item.position.y === y + 40) as { id: string } | undefined;
    const original = Object.fromEntries(chain.map((item) => [item.id, item]));
    const idOf = (id: string) => {
      const found = at(original[id].x, original[id].y);
      expect(found, `no pasted node sits 40px down and right of ${id}`).toBeTruthy();
      return found!.id;
    };
    expect(stored.edges.map((edge: { source: string; target: string }) => [edge.source, edge.target]).sort(),
           "the edges between the pasted nodes did not come with them")
      .toEqual([[idOf("a"), idOf("b")], [idOf("b"), idOf("c")]].sort());
    await expect.poll(() => selected(page), { message: "the pasted nodes are not what is selected" })
      .toEqual([idOf("a"), idOf("b"), idOf("c")].sort());

    await page.getByRole("button", { name: "Undo paste" }).click();
    await expect(status(page)).toHaveText("Took back the paste of 3 nodes.");
    await expect(page.locator(".pipeline-canvas .pipeline-node"), "one Undo did not take the paste back")
      .toHaveCount(1);
    expect(sent, "taking the paste back was not one request").toHaveLength(2);
  });

  test("Delete removes every selected node in one request", async ({ page }) => {
    const { id } = await openFixture(page);
    await node(page, "a").click();
    await node(page, "b").click({ modifiers: ["Shift"] });
    await expect.poll(() => selected(page)).toEqual(["a", "b"]);
    const sent = edits(page);
    await page.keyboard.press("Delete");
    await expect(status(page)).toHaveText("Deleted 2 nodes. Their edges went with them.");
    await expect(page.locator(".pipeline-canvas .pipeline-node")).toHaveCount(2);
    expect(sent, "deleting two nodes was not one request").toEqual([`POST /pipeline-builder/graphs/${id}/commands`]);
    const stored = await (await page.request.get(`/pipeline-builder/graphs/${id}`)).json();
    expect(stored.nodes.map((item: { id: string }) => item.id).sort()).toEqual(["c", "d"]);
    expect(stored.edges, "an edge still names a deleted node").toEqual([]);
  });
});

/**
 * Hidden nodes are a view state that says how many it hides. X6 of
 * `GOAL_GRAPH_2026-09-23.md`. Hiding is in this browser only, like a pane layout:
 * it survives a reload here, and the pipeline on the server never hears of it.
 */
test.describe("hidden nodes are a view state", () => {
  test.beforeEach(async ({}, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-1280", "Runs once; the fixtures are stateful.");
  });

  test("two hidden nodes are counted, survive a reload here, and are hidden nowhere on the server", async ({ page }) => {
    const { id, name } = await openFixture(page);
    await node(page, "a").click();
    await node(page, "b").click({ modifiers: ["Shift"] });
    const sent = edits(page);
    await page.keyboard.press("Control+h");

    await expect(page.locator(".pipeline-canvas .pipeline-node"), "Ctrl+H did not hide the two selected nodes")
      .toHaveCount(2);
    await expect(page.locator(".canvas-hidden-note"), "the canvas does not say how many it hides")
      .toContainText("2 of 4 nodes hidden in this browser");
    // a feeds c and b feeds d: each node that remains says one neighbour is hidden.
    await expect(page.locator(".hidden-link"), "an edge to a hidden node left no trace on the node it came from")
      .toHaveText(["1 hidden", "1 hidden"]);
    expect(sent, "hiding sent an edit; it is a view of the graph, not a change to it").toEqual([]);

    await page.reload();
    const row = page.locator(".output-rail .resource-row").filter({ hasText: name });
    await row.click();
    await expect(page.locator(".pipeline-canvas .pipeline-node"), "the hidden nodes came back on reload")
      .toHaveCount(2);
    const stored = await (await page.request.get(`/pipeline-builder/graphs/${id}`)).json();
    expect(stored.nodes, "the server lost a node that was only hidden").toHaveLength(4);
    expect(JSON.stringify(stored), "hiding was written to the pipeline on the server").not.toContain("hidden");

    await page.getByRole("button", { name: "Show all", exact: true }).click();
    await expect(page.locator(".pipeline-canvas .pipeline-node")).toHaveCount(4);
    await expect(page.locator(".canvas-hidden-note")).toHaveCount(0);
    await expect(page.locator(".hidden-link")).toHaveCount(0);
  });

  test("a hidden node is out of every tool's reach", async ({ page }) => {
    await openFixture(page);
    await node(page, "a").click();
    await page.getByRole("button", { name: "Hide selected", exact: true }).click();
    await expect(page.locator(".pipeline-canvas .pipeline-node")).toHaveCount(3);
    // a was the node last clicked, which a tool takes when nothing else is selected.
    // Hidden, it is not on the canvas, and no tool may take it.
    await expect(page.locator(".canvas-selection-count"), "a hidden node is still what the tools act on")
      .toHaveText("0 of 4 selected");
    await page.getByRole("button", { name: "Select all", exact: true }).click();
    await expect.poll(() => selected(page), { message: "Select all took a hidden node" }).toEqual(["b", "c", "d"]);
    await expect(page.locator(".canvas-selection-count")).toHaveText("3 of 4 selected");
  });
});

/**
 * A port drag connects two nodes by one command, which one Undo takes back. X7 of
 * `GOAL_GRAPH_2026-09-23.md`. Edges are read from the server; the screen draws them,
 * and a drawing is not what was saved.
 */
async function portCentre(page: Page, selector: string) {
  const box = await page.locator(selector).boundingBox();
  expect(box, `${selector} is not on the canvas`).toBeTruthy();
  return { x: box!.x + box!.width / 2, y: box!.y + box!.height / 2 };
}

/** Picks up a node's output port and carries it onto another node's input port, live. */
async function startPortDrag(page: Page, from: string, to: string) {
  const start = await portCentre(page, `[data-port-out="${from}"]`);
  const end = await portCentre(page, `[data-port-in="${to}"]`);
  await page.mouse.move(start.x, start.y);
  await page.mouse.down();
  for (let step = 1; step <= 12; step += 1) {
    await page.mouse.move(start.x + ((end.x - start.x) * step) / 12, start.y + ((end.y - start.y) * step) / 12);
    await page.waitForTimeout(16);
  }
  await expect(page.locator(".edge-wire"), "the port drag never started").toHaveCount(1);
  await expect(page.locator(`[data-port-in="${to}"]`), "the input port does not show it would take the edge")
    .toHaveClass(/\bport-over\b/);
}

const storedEdges = async (page: Page, id: string) =>
  ((await (await page.request.get(`/pipeline-builder/graphs/${id}`)).json()).edges as Array<{ source: string; target: string }>)
    .map((edge) => `${edge.source}->${edge.target}`).sort();

test.describe("a port drag connects two nodes", () => {
  test.beforeEach(async ({}, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-1280", "Runs once; a port drag is a desktop pointer gesture.");
  });

  test("dragging an output port onto an input port inserts one edge and one Undo removes it", async ({ page }) => {
    const { id } = await openFixture(page);
    const sent = edits(page);
    await startPortDrag(page, "a", "d");
    await page.mouse.up();
    await expect(status(page)).toHaveText("Connected a to d.");
    expect(await storedEdges(page, id), "the drop did not add the one edge").toEqual(["a->c", "a->d", "b->d"]);
    expect(sent, "connecting was not one command").toEqual([`POST /pipeline-builder/graphs/${id}/commands`]);
    await expect(page.locator(".pipeline-canvas .pipeline-node"), "connecting created or lost a node").toHaveCount(4);

    await page.waitForTimeout(150);
    await page.getByRole("button", { name: "Undo connect" }).click();
    await expect(status(page)).toHaveText("Took back the edge a to d.");
    expect(await storedEdges(page, id), "one Undo did not take the edge back").toEqual(["a->c", "b->d"]);
    expect(sent, "taking the edge back was not one command").toHaveLength(2);
  });

  test("Escape during a port drag connects nothing and writes nothing", async ({ page }) => {
    const { id } = await openFixture(page);
    const sent = edits(page);
    await startPortDrag(page, "a", "d");
    await page.keyboard.press("Escape");
    await page.mouse.up();
    await page.waitForTimeout(300);
    await expect(page.locator(".edge-wire"), "Escape left the edge being drawn").toHaveCount(0);
    expect(sent, "a cancelled port drag wrote something").toEqual([]);
    expect(await storedEdges(page, id)).toEqual(["a->c", "b->d"]);
  });

  test("a port dropped on bare canvas connects nothing and creates nothing", async ({ page }) => {
    // A drop over the canvas and no port is where a palette entry lands and makes a
    // node. A port that missed must stop before that, or it posts a node whose type
    // is the port's id.
    const { id } = await openFixture(page);
    const sent = edits(page);
    const start = await portCentre(page, '[data-port-out="a"]');
    const stage = await page.locator(".canvas-stage").boundingBox();
    const bare = { x: stage!.x + 200 * (stage!.width / 1500), y: stage!.y + 190 * (stage!.width / 1500) };
    await page.mouse.move(start.x, start.y);
    await page.mouse.down();
    for (let step = 1; step <= 12; step += 1) {
      await page.mouse.move(start.x + ((bare.x - start.x) * step) / 12, start.y + ((bare.y - start.y) * step) / 12);
      await page.waitForTimeout(16);
    }
    await expect(page.locator(".edge-wire"), "the port drag never started").toHaveCount(1);
    await page.mouse.up();
    await page.waitForTimeout(400);
    expect(sent, "a port dropped on bare canvas wrote something").toEqual([]);
    expect(await storedEdges(page, id)).toEqual(["a->c", "b->d"]);
    await expect(page.locator(".pipeline-canvas .pipeline-node")).toHaveCount(4);
  });

  test("two selected nodes connect without a drag", async ({ page }) => {
    // WCAG 2.5.7: a single pointer and no drag. The first node selected feeds the second.
    const { id } = await openFixture(page);
    await node(page, "b").click();
    await node(page, "c").click({ modifiers: ["Shift"] });
    await page.getByRole("button", { name: "Connect", exact: true }).click();
    await expect(status(page)).toHaveText("Connected b to c.");
    expect(await storedEdges(page, id)).toEqual(["a->c", "b->c", "b->d"]);
  });

  test("the insert control on an edge still inserts a node after the selected one", async ({ page }) => {
    // The control beside the drag stays, and does what it always did: a new node.
    await openFixture(page);
    // d, not a: a selected node's click menu opens to its right, tall, and sits over the
    // edge controls of a left column -- an overlap older than this goal.
    await node(page, "d").click();
    await expect(page.locator(".pipeline-canvas .pipeline-node")).toHaveCount(4);
    await page.locator(".edge-insert").first().click();
    await expect(page.locator(".pipeline-canvas .pipeline-node"), "the edge control inserted nothing").toHaveCount(5);
  });
});

/**
 * The strip says whether there is unsaved work. X8 of `GOAL_GRAPH_2026-09-23.md`.
 * Positions save on drop; what can be unsaved is a node's configuration, typed into
 * its form and held as a draft until it is saved.
 */
test.describe("the strip says whether there is unsaved work", () => {
  test.beforeEach(async ({}, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-1280", "Runs once; the fixtures are stateful.");
  });

  test("a typed node configuration counts as unsaved until it is saved", async ({ page }) => {
    await openFixture(page);
    const strip = page.locator(".workbench-status-strip");
    await expect(strip.locator(".saved-state"), "a pipeline with nothing typed does not say it is saved")
      .toHaveText("Saved");

    await node(page, "a").click();
    const label = page.getByLabel("Node label");
    const original = await label.inputValue();
    await label.fill(`${original} renamed`);
    const unsaved = strip.getByRole("button", { name: "1 unsaved change" });
    await expect(unsaved, "typing into a node's form did not count as unsaved").toBeVisible();
    await expect(strip.locator(".saved-state")).toHaveCount(0);

    await unsaved.click();
    await expect(strip.getByRole("list", { name: "Unsaved changes" }), "the count does not list what is unsaved")
      .toContainText("(a): configuration not saved");

    // Typed back to what is saved, it is not a change.
    await label.fill(original);
    await expect(strip.locator(".saved-state"), "a field changed and changed back still counts as unsaved")
      .toHaveText("Saved");

    await label.fill(`${original} renamed`);
    await expect(strip.getByRole("button", { name: "1 unsaved change" })).toBeVisible();
    // A Filter's field, operator and value are required, and the form will not submit
    // without them.
    await page.getByLabel("Field *").fill("risk");
    await page.getByLabel("Operator *").selectOption("gte");
    await page.getByLabel("Value *").fill("1");
    await page.getByRole("button", { name: "Save configuration" }).click();
    await expect(strip.locator(".saved-state"), "saving the configuration left it counted as unsaved")
      .toHaveText("Saved");
  });
});
