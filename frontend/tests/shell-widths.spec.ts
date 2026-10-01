import { randomUUID } from "node:crypto";
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

const SCREENS: Array<{ name: string; route: string; canvas: string; surface: string;
                       prepare?: (page: Page) => Promise<void> }> = [
  { name: "pipeline builder", route: "/workspace/pipeline", canvas: "Pipeline", surface: ".pipeline-canvas" },
  { name: "ontology manager", route: "/workspace/ontology", canvas: "Object type", surface: ".manager-surface" },
  {
    name: "workshop",
    route: "/workspace/workshop",
    canvas: "Canvas",
    surface: ".visual-flow-canvas",
    prepare: async (page) => {
      const draft = page.getByRole("button", { name: "Create draft" });
      await expect(draft.or(page.locator(".pane-host")).first()).toBeVisible();
      if (await draft.isVisible()) await draft.click();
    },
  },
];

interface Reading {
  surfaceWidth: number;
  paneContent: number;
  viewportHeight: number;
  workspaceTop: number;
  workspaceContent: number;
  hostWidth: number;
  canvasWidth: number;
  widestOther: { title: string; width: number };
  clipped: Array<{ title: string; scroll: number; client: number }>;
}

async function read(page: Page, canvas: string, surface: string): Promise<Reading> {
  return page.evaluate(([canvasTitle, surfaceSelector]) => {
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
    // The thing a person works on, inside the pane that holds it. S3 made the pane
    // the widest; the pipeline's canvas then sat in a 236px grid track inside it,
    // with the rest of the pane blank beside it, because the pane was measured and
    // the canvas was not.
    const body = canvasPane?.querySelector(".pane-body") as HTMLElement | null;
    const bodyStyle = body ? getComputedStyle(body) : null;
    const paneContent = body && bodyStyle
      ? body.clientWidth - parseFloat(bodyStyle.paddingLeft) - parseFloat(bodyStyle.paddingRight) : 0;
    const surfaceElement = canvasPane?.querySelector(surfaceSelector) as HTMLElement | null;
    return {
      surfaceWidth: surfaceElement ? width(surfaceElement) : 0,
      paneContent,
      viewportHeight: window.innerHeight,
      workspaceTop: workspace.getBoundingClientRect().top + window.scrollY,
      workspaceContent: content,
      hostWidth: host ? width(host) : 0,
      canvasWidth: canvasPane ? width(canvasPane) : 0,
      widestOther: others[0] || { title: "(none)", width: 0 },
      clipped,
    };
  }, [canvas, surface] as const);
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
          const at = await read(page, screen.canvas, screen.surface);

          expect.soft(at.workspaceTop,
            `${width}px: the workspace begins at ${at.workspaceTop}px of a ${at.viewportHeight}px first screen`)
            .toBeLessThanOrEqual(at.viewportHeight / 2);

          expect.soft(at.canvasWidth, `${width}px: the ${screen.canvas} pane is not on the screen`).toBeGreaterThan(0);
          expect.soft(at.canvasWidth,
            `${width}px: ${screen.canvas} is ${Math.round(at.canvasWidth)}px, narrower than ` +
            `${at.widestOther.title} at ${Math.round(at.widestOther.width)}px`)
            .toBeGreaterThanOrEqual(at.widestOther.width - 1);
          expect.soft(at.paneContent - at.surfaceWidth,
            `${width}px: the ${screen.canvas} surface is ${Math.round(at.surfaceWidth)}px of the ` +
            `${Math.round(at.paneContent)}px its pane holds; the rest is blank beside it`)
            .toBeLessThanOrEqual(GUTTER_PX);
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
 * Data & Media does not scroll sideways, and says each upload route whole.
 *
 * Each upload panel names the route it posts to in a `<code>` inside a
 * `.summary-list`, a grid whose one column was `auto`. An auto track grows to its
 * widest item's min-content, and a route has nowhere to break, so with a dataset
 * selected the column was the route plus its paragraph's padding and
 * `main.workspace` scrolled sideways: 31px at 320, 1px at 350, measured 2026-09-26.
 * A media set's id is a 32-character uuid unless it is given one, so its route
 * was wider still: it scrolled the workspace at 1101 too, where the two panels
 * sit side by side, and at 1200 ran out of its panel without scrolling anything.
 * Clipping the route would pass a scroll check and hide the one thing the
 * paragraph is there to say, so the route is read back whole and every line of
 * its text must sit inside the list that holds it.
 */
test.describe("Data & Media at every width in the list", () => {
  test("does not scroll sideways, and shows each upload route whole", async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-1280", "Runs once; this test sets every viewport itself.");
    test.setTimeout(240_000);
    const stamp = Date.now();
    const dataset = { id: `sideways_dataset_${stamp}`, name: `Sideways dataset ${stamp}` };
    const mediaSet = { id: randomUUID().replace(/-/g, ""), name: `Sideways media ${stamp}` };
    const created = await page.request.post("/data-assets", { data: {
      id: dataset.id, project_id: "default", display_name: dataset.name, kind: "dataset",
      asset_schema: { name: "string" }, records: [{ name: "one" }],
    } });
    expect(created.ok(), await created.text()).toBeTruthy();
    const createdSet = await page.request.post("/media-sets", { data: {
      id: mediaSet.id, display_name: mediaSet.name, media_type: "document",
    } });
    expect(createdSet.ok(), await createdSet.text()).toBeTruthy();
    const routes = [`/data-assets/${dataset.id}/upload`, `/media-sets/${mediaSet.id}/items/upload`];

    for (const width of SHELL_WIDTHS) {
      await test.step(`${width}px`, async () => {
        await page.setViewportSize({ width, height: heightAt(width) });
        await page.goto("/workspace/data-media");
        // Each section selects its first entry by itself; these are selected by name,
        // and the class is waited for so a click mid-render cannot land on another row.
        for (const name of [dataset.name, mediaSet.name]) {
          const row = page.getByRole("button", { name });
          await row.click();
          await expect(row).toHaveClass(/selected/);
        }
        for (const route of routes) await expect(page.locator("code", { hasText: route })).toBeVisible();

        const at = await page.evaluate((expected) => {
          const workspace = document.querySelector("main.workspace") as HTMLElement;
          const codes = Array.from(workspace.querySelectorAll("code"));
          return {
            overflow: workspace.scrollWidth - workspace.clientWidth,
            routes: expected.map((route) => {
              const code = codes.find((candidate) => candidate.textContent === route);
              if (!code) return { route, whole: false, outside: 0 };
              // The text's own lines, not the element's box: a code clipped to its
              // box would keep its box inside the list and its text past it.
              const text = document.createRange();
              text.selectNodeContents(code);
              const edge = (code.closest(".summary-list") as HTMLElement).getBoundingClientRect().right;
              const rights = Array.from(text.getClientRects()).map((line) => line.right);
              return { route, whole: true, outside: Math.round(Math.max(0, ...rights.map((right) => right - edge))) };
            }),
          };
        }, routes);

        expect.soft(at.overflow, `${width}px: the workspace scrolls ${at.overflow}px sideways`).toBeLessThanOrEqual(0);
        for (const route of at.routes) {
          expect.soft(route.whole, `${width}px: ${route.route} is not on the page whole`).toBe(true);
          expect.soft(route.outside, `${width}px: ${route.route} runs ${route.outside}px past its list`)
            .toBeLessThanOrEqual(0);
        }
      });
    }
  });
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
    // A page-state request still in the handler when the test ends is not this test's.
    await page.unrouteAll({ behavior: "ignoreErrors" });
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
    // Selecting the pipeline selects its first node, and that second canvas request can still be
    // in the handler when the test ends: late in a full run its fetch outlived the page, and the
    // disposed response failed a test that had passed. What it would answer is not this test's.
    await page.unrouteAll({ behavior: "ignoreErrors" });
  });

  test("a canvas that failed to load is not said to be loading", async ({ page }) => {
    await page.route(isCanvas, (route) => route.fulfill({ status: 500, json: { detail: "held back by the test" } }));
    const { row } = await openFixture(page);
    await row.click();
    await expect(badge(page), "a failed canvas still reads as loading").toHaveText("Canvas failed to load");
  });
});


/**
 * The workspace stays where it is when the backend's status arrives. The bar above every
 * workspace drew its readiness disclosure only once `/project/readiness` answered, and its
 * job counts only once `/jobs/summary` did; below 640px each part is its own row. The
 * workspace moved down under a pointer already aimed at it, which is why two drag tests
 * failed now and then in long runs. Both answers are held here until the workspace has drawn.
 */
test.describe("the workspace stays put when the backend's status arrives", () => {
  test("the Platform Graph does not move when readiness and job counts land", async ({ page }) => {
    let release!: () => void;
    const held = new Promise<void>((resolve) => { release = resolve; });
    const late = (url: URL) => url.pathname === "/project/readiness" || url.pathname === "/jobs/summary";
    await page.route(late, async (route) => {
      await held;
      await route.continue();
    });
    await page.goto("/workspace/graph");
    const heading = page.getByRole("heading", { name: "Platform Graph", exact: true });
    await expect(heading).toBeVisible();
    await expect(page.locator(".backend-connection"), "the status was not held back").toContainText("CHECKING");
    const before = await heading.boundingBox();

    const landed = Promise.all([late, late].map((_, index) => page.waitForResponse((response) =>
      new URL(response.url()).pathname === (index ? "/jobs/summary" : "/project/readiness"))));
    release();
    await landed;
    await expect(page.locator(".backend-connection .execution-health")).toBeVisible();
    await expect(page.locator(".backend-connection")).not.toContainText("CHECKING");
    const after = await heading.boundingBox();
    const moved = Math.round((after!.y - before!.y) * 10) / 10;
    expect(Math.abs(moved), `the workspace moved ${moved}px when the backend's status arrived`).toBeLessThanOrEqual(1);
  });
});

test.describe("the top bar at a narrow width", () => {
  // At 1100 and below, `.app-shell` is one grid column with `min-height: 100vh`.
  // With no row sizes, a page shorter than the window gave its spare height to
  // both rows, so the top bar stretched: 70px on Ops at 768 where 60 is its
  // content, and 92px once body text went to 14px (GOAL_LOOK U5) made the page
  // shorter. The bar is as tall as its contents, however short the page.
  const WINDOW = 10_000;
  for (const width of [768, 1024, 1100]) {
    test(`is as tall as its contents on a short page at ${width}`, async ({ page }, testInfo) => {
      test.skip(testInfo.project.name !== "desktop-1280", "Runs once; this test sets its own viewport.");
      // Taller than any page, so the page is short whatever earlier tests seeded.
      await page.setViewportSize({ width, height: WINDOW });
      await page.goto("/workspace/ops");
      await expect(page.getByRole("heading", { name: "Operational Control Plane" })).toBeVisible();
      const { bar, content, page: pageHeight } = await page.locator(".sidebar").evaluate((sidebar: HTMLElement) => {
        const style = getComputedStyle(sidebar);
        const tallest = Math.max(...[...sidebar.children].map((child) => (child as HTMLElement).offsetHeight));
        return {
          bar: sidebar.offsetHeight,
          content: Math.round(tallest + parseFloat(style.paddingTop) + parseFloat(style.paddingBottom)
                              + parseFloat(style.borderTopWidth) + parseFloat(style.borderBottomWidth)),
          // Where the content ends, not the workspace: after the fix the workspace
          // row fills the window by design.
          page: Math.max(...[...document.querySelector(".workspace")!.children]
            .map((child) => child.getBoundingClientRect().bottom + window.scrollY)),
        };
      });
      expect(pageHeight, `the content ends at ${pageHeight}px, not above the window's ${WINDOW}, so this proves nothing`)
        .toBeLessThan(WINDOW);
      expect(bar, `the top bar is ${bar}px for ${content}px of contents`).toBeLessThanOrEqual(content + 1);
    });
  }
});
