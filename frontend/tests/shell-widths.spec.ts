import { expect, test, type Page } from "@playwright/test";

/**
 * The screen you get at the width you have. S1 of `GOAL_SHELL_2026-09-23.md`.
 *
 * The pane and movement goals were judged on four widths -- 375, 768, 1280,
 * 1600 -- and a render sweep at the same four. Opened at 1000, 1024 and 1100,
 * the built app was a dark bar with the brand centred in it: two media queries
 * disagree on that band, and neither width the sweep visits is in it. A sweep at
 * four widths is a claim about four widths.
 *
 * So this walks the widths from 320 to 1920, landing on each breakpoint the
 * stylesheet declares and on either side of it, plus 1024 and 1366, which are
 * what real screens are. At every width, on every screen with panes:
 *
 *  1. the workspace begins in the top half of the first viewport -- a first
 *     screen that is mostly sidebar is the defect, not only one that is all of it;
 *  2. the canvas is the widest pane in the pane row, and the pane host fills the
 *     workspace it sits in to within the gutter, so no empty track sits beside it;
 *  3. no pane title is clipped: its `scrollWidth` equals its `clientWidth`.
 *
 * Each width is a soft step, so one run reports every width that fails rather
 * than the first. The list is here, in one place, so the next width is one line.
 */
export const SHELL_WIDTHS = [
  320, 375, 640, 700, 760, 768, 900, 901, 1000, 1024,
  1100, 1101, 1200, 1280, 1366, 1500, 1600, 1920,
];

/** 1024 and 1366 are measured at the height those screens have. */
const heightAt = (width: number) => (width === 1024 || width === 1366 ? 768 : 700);

/** Allowance for the page's own padding and the pane host's borders. */
const GUTTER_PX = 24;

const SCREENS: Array<{ name: string; route: string; canvas: string; prepare?: (page: Page) => Promise<void> }> = [
  { name: "pipeline builder", route: "/workspace/pipeline", canvas: "Pipeline" },
  { name: "ontology manager", route: "/workspace/ontology", canvas: "Object type" },
  {
    name: "workshop",
    route: "/workspace/workshop",
    canvas: "Canvas",
    prepare: async (page) => {
      const draft = page.getByRole("button", { name: "Create draft" });
      await expect(draft.or(page.locator(".pane-host")).first()).toBeVisible();
      if (await draft.isVisible()) await draft.click();
    },
  },
];

interface Reading {
  viewportHeight: number;
  workspaceTop: number;
  workspaceContent: number;
  hostWidth: number;
  canvasWidth: number;
  widestOther: { title: string; width: number };
  clipped: Array<{ title: string; scroll: number; client: number }>;
}

async function read(page: Page, canvas: string): Promise<Reading> {
  return page.evaluate((canvasTitle) => {
    window.scrollTo(0, 0);
    const workspace = document.querySelector("main.workspace") as HTMLElement;
    const style = getComputedStyle(workspace);
    const content = workspace.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
    const host = document.querySelector(".pane-host") as HTMLElement;
    const rowPanes = Array.from(document.querySelectorAll<HTMLElement>(".pane-host-row .pane"));
    const width = (element: HTMLElement) => element.getBoundingClientRect().width;
    const canvasPane = rowPanes.find((pane) => pane.getAttribute("aria-label") === canvasTitle);
    const others = rowPanes.filter((pane) => pane !== canvasPane)
      .map((pane) => ({ title: pane.getAttribute("aria-label") || "", width: width(pane) }))
      .sort((a, b) => b.width - a.width);
    const clipped = Array.from(document.querySelectorAll<HTMLElement>(".pane .pane-header strong"))
      .filter((title) => title.scrollWidth > title.clientWidth)
      .map((title) => ({ title: title.textContent || "", scroll: title.scrollWidth, client: title.clientWidth }));
    return {
      viewportHeight: window.innerHeight,
      workspaceTop: workspace.getBoundingClientRect().top + window.scrollY,
      workspaceContent: content,
      hostWidth: host ? width(host) : 0,
      canvasWidth: canvasPane ? width(canvasPane) : 0,
      widestOther: others[0] || { title: "(none)", width: 0 },
      clipped,
    };
  }, canvas);
}

test.describe("every screen with panes, at every width in the list", () => {
  for (const screen of SCREENS) {
    test(`the ${screen.name} holds its layout at every width`, async ({ page }, testInfo) => {
      test.skip(testInfo.project.name !== "desktop-1280", "Runs once; this test sets every viewport itself.");
      test.setTimeout(240_000);
      const bootstrap = await page.request.post("/scenarios/asset-reliability/bootstrap", { data: {} });
      expect(bootstrap.ok(), "the scenario did not bootstrap").toBeTruthy();

      await page.setViewportSize({ width: 1280, height: 900 });
      await page.goto(screen.route);
      await screen.prepare?.(page);
      await expect(page.getByRole("button", { name: "Reset panes" })).toBeVisible();
      // The default arrangement is what is judged; a layout left by another test
      // would measure that test's choices.
      await page.getByRole("button", { name: "Reset panes" }).click();

      for (const width of SHELL_WIDTHS) {
        await test.step(`${width}px`, async () => {
          await page.setViewportSize({ width, height: heightAt(width) });
          await page.reload();
          await screen.prepare?.(page);
          await expect(page.locator(".pane-host-row .pane").first()).toBeVisible();
          const at = await read(page, screen.canvas);

          expect.soft(at.workspaceTop,
            `${width}px: the workspace begins at ${at.workspaceTop}px of a ${at.viewportHeight}px first screen`)
            .toBeLessThanOrEqual(at.viewportHeight / 2);

          expect.soft(at.canvasWidth, `${width}px: the ${screen.canvas} pane is not on the screen`).toBeGreaterThan(0);
          expect.soft(at.canvasWidth,
            `${width}px: ${screen.canvas} is ${Math.round(at.canvasWidth)}px, narrower than ` +
            `${at.widestOther.title} at ${Math.round(at.widestOther.width)}px`)
            .toBeGreaterThanOrEqual(at.widestOther.width - 1);
          expect.soft(at.workspaceContent - at.hostWidth,
            `${width}px: the pane host is ${Math.round(at.hostWidth)}px of ${Math.round(at.workspaceContent)}px ` +
            `the workspace has; the rest is a track nothing fills`)
            .toBeLessThanOrEqual(GUTTER_PX);

          expect.soft(at.clipped,
            `${width}px: pane titles clipped: ` +
            at.clipped.map((clip) => `${clip.title} (${clip.scroll} in ${clip.client})`).join(", "))
            .toEqual([]);
        });
      }
    });
  }
});

/**
 * A badge says what is true. S5 of `GOAL_SHELL_2026-09-23.md`.
 *
 * The pipeline builder's status strip read `canvas?.validation.status || "loading"`,
 * so with no pipeline selected, and after a canvas failed to load, it said loading
 * while nothing was. Each state is reached with a response the test controls,
 * because which pipeline a fresh database selects depends on what earlier tests made.
 */
test.describe("the pipeline status strip says what is true", () => {
  const badge = (page: Page) => page.locator(".workbench-status-strip .badge");
  const isPageState = (url: URL) => url.pathname === "/ui-state/pipeline";
  const isCanvas = (url: URL) => /^\/ui-state\/pipeline\/[^/]+\/canvas$/.test(url.pathname);

  test.beforeEach(async ({}, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-1280", "Runs once; the strip is the same at every width.");
  });

  test("with no pipeline selected the strip says so, not loading", async ({ page }) => {
    await page.route(isPageState, async (route) => {
      const response = await route.fetch();
      const body = await response.json();
      await route.fulfill({ response, json: { ...body, selected_canvas: null } });
    });
    await page.goto("/workspace/pipeline");
    await expect(badge(page), "the strip claims something is loading when no pipeline is selected")
      .toHaveText("No pipeline selected");
  });

  test("while the page itself loads the strip says loading, not that nothing is selected", async ({ page }) => {
    let release: () => void = () => {};
    const held = new Promise<void>((resolve) => { release = resolve; });
    await page.route(isPageState, async (route) => {
      await held;
      const response = await route.fetch();
      await route.fulfill({ response, json: { ...(await response.json()), selected_canvas: null } });
    });
    await page.goto("/workspace/pipeline");
    await expect(badge(page), "the strip says nothing is selected before it knows").toHaveText("loading");
    release();
    await expect(badge(page)).toHaveText("No pipeline selected");
  });

  /** A pipeline of its own, opened from the Outputs pane with nothing preselected. */
  async function openFixture(page: Page) {
    const suffix = `${Date.now()}`;
    const name = `Strip fixture ${suffix}`;
    const created = await page.request.post("/pipeline-builder/graphs", { data: {
      id: `strip_fixture_${suffix}`, display_name: name,
      nodes: [{ id: "input", type: "input_dataset", config: {} }], edges: [],
    } });
    expect(created.ok(), `the fixture pipeline was not created: ${created.status()}`).toBeTruthy();
    await page.route(isPageState, async (route) => {
      const response = await route.fetch();
      await route.fulfill({ response, json: { ...(await response.json()), selected_canvas: null } });
    });
    await page.goto("/workspace/pipeline");
    await expect(badge(page)).toHaveText("No pipeline selected");
    const row = page.locator(".output-rail .resource-row").filter({ hasText: name });
    await expect(row).toBeVisible();
    return { row };
  }

  test("while a canvas loads the strip says loading, and then what the canvas says", async ({ page }) => {
    let release: () => void = () => {};
    const held = new Promise<void>((resolve) => { release = resolve; });
    let status = "";
    await page.route(isCanvas, async (route) => {
      await held;
      const response = await route.fetch();
      status = (await response.json())?.validation?.status || "";
      await route.fulfill({ response });
    });
    const { row } = await openFixture(page);
    await row.click();
    await expect(badge(page), "a canvas on its way is not said to be loading").toHaveText("loading");

    release();
    await expect.poll(() => status, { message: "the canvas was never requested" }).not.toBe("");
    await expect(badge(page), "the strip still says loading after the canvas arrived").toHaveText(status);
    await expect(badge(page)).not.toHaveText("loading");
  });

  test("a canvas that failed to load is not said to be loading", async ({ page }) => {
    await page.route(isCanvas, (route) => route.fulfill({ status: 500, json: { detail: "held back by the test" } }));
    const { row } = await openFixture(page);
    await row.click();
    await expect(badge(page), "a failed canvas still reads as loading").toHaveText("Canvas failed to load");
  });
});

