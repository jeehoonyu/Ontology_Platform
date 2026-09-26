import { expect, test, type Page } from "@playwright/test";

/**
 * What the app must not claim, and what must not take it down.
 * `GOAL_FOUNDATIONS_2026-09-25.md`.
 *
 * A2: browser storage is a convenience. A private window, blocked site data or a
 * full quota makes it throw, and an older build can leave any shape in it. Before
 * A2, five storage calls were unguarded and nothing caught an error thrown by a
 * screen, so React unmounted the whole root: a blank page, sidebar and all.
 *
 * Storage and error handling do not change with the viewport, so these run once,
 * on desktop. Each was run against a build with the thing it defends removed, and
 * failed, before it was believed.
 */

// Every Storage method throws, as it does with site data blocked.
async function blockStorage(page: Page) {
  await page.addInitScript(() => {
    const refuse = () => {
      throw new DOMException("The operation is insecure.", "SecurityError");
    };
    for (const method of ["getItem", "setItem", "removeItem", "clear", "key"]) {
      Object.defineProperty(Storage.prototype, method, { configurable: true, value: refuse });
    }
  });
}

async function shellStands(page: Page, heading: string) {
  await expect(page.locator(".sidebar"), "the sidebar").toBeVisible();
  await expect(page.getByRole("heading", { name: heading, exact: true }).first(), `the ${heading} heading`).toBeVisible();
}

// A builder's collaboration effect reads storage once an artifact exists; its join
// request is the sign that the effect ran without throwing.
async function openBuilderWithArtifact(page: Page, view: string) {
  const joined = page.waitForRequest((request) => /\/artifacts\/[^/]+\/collaboration\/join$/.test(new URL(request.url()).pathname));
  await page.goto(`/workspace/${view}`);
  const create = page.getByRole("button", { name: "Create draft" });
  await expect(create.or(page.locator(".visual-builder-shell")).first()).toBeVisible();
  if (await create.isVisible()) await create.click();
  await joined;
}

test.describe("GOAL_FOUNDATIONS A2", () => {
  test.beforeEach(({}, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-1280", "Storage and error handling are checked once, on desktop.");
  });

  test("A blocked store leaves every screen standing", async ({ page }) => {
    await blockStorage(page);
    await page.goto("/workspace/command-center");
    await shellStands(page, "Asset Reliability Command Center");

    for (const [view, title] of [["workshop", "Workshop"], ["aip", "AIP Logic"],
                                 ["investigations", "Investigations"], ["entity-resolution", "Entity Resolution"]]) {
      await openBuilderWithArtifact(page, view);
      await shellStands(page, title);
    }

    // Platform Graph reads its saved layout once the overview has loaded, and places
    // the nodes only after that read; the asset scenario gives it nodes to place.
    expect((await page.request.post("/scenarios/asset-reliability/bootstrap", { data: {} })).ok()).toBeTruthy();
    await page.goto("/workspace/graph");
    await expect(page.locator(".react-flow__node").first(), "a placed graph node").toBeVisible();
    await shellStands(page, "Platform Graph");
  });

  for (const stored of ["{bad", "null", "\"x\""]) {
    test(`A corrupt recents list is ignored: ${stored}`, async ({ page }) => {
      await page.addInitScript((value) => window.localStorage.setItem("ontology.recentViews", value), stored);
      await page.goto("/workspace/command-center");
      await shellStands(page, "Asset Reliability Command Center");
      await expect(page.locator(".recent-links"), "no recents from a corrupt list").toHaveCount(0);
    });
  }

  // The boundary: an overview whose nodes are not a list makes Platform Graph throw
  // in its layout effect. The shell stands, the failure names the screen, and the
  // sidebar still navigates.
  test("A screen that throws leaves the shell standing and names itself", async ({ page }) => {
    await page.route((url) => url.pathname === "/graph/overview",
                     (route) => route.fulfill({ json: { nodes: "not a list", edges: [], summary: {} } }));
    await page.goto("/workspace/graph");
    await expect(page.getByRole("alert").filter({ hasText: "Platform Graph failed." }), "the screen's failure").toBeVisible();
    await expect(page.locator(".sidebar"), "the sidebar").toBeVisible();
    await page.locator(".sidebar").getByRole("button", { name: /^Command Center/ }).click();
    await shellStands(page, "Asset Reliability Command Center");
  });
});
