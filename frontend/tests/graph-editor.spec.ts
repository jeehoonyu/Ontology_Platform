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
 * without the right one, and parents and children are one edge away.
 */
const FOUR: FixtureNode[] = [
  { id: "a", x: 120, y: 80 },
  { id: "b", x: 120, y: 260 },
  { id: "c", x: 560, y: 80 },
  { id: "d", x: 560, y: 260 },
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
  await canvas.evaluate((element) => { element.scrollLeft = 0; element.scrollTop = 0; });
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
