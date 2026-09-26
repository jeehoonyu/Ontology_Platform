import { expect, test, type Page, type TestInfo } from "@playwright/test";

/**
 * Every resource kind has a URL. `GOAL_FOUNDATIONS_2026-09-25.md` A6.
 *
 * For each kind, going to its route selects that resource, Back restores the one before, and
 * an unknown id is named, never swapped for the first item. `frontend/src/routes.json` is the
 * one table; `oms/test_workspace_routes.py` holds the server's copy to it and refuses a kind or
 * a view with no case here.
 *
 * Each data case makes two resources of its own, reads from the page what the bare route opens,
 * and targets whichever of the two that is not: every default is the newest or first item, so
 * a reader removed would open the default and fail.
 */

const desktopOnly = (testInfo: TestInfo) =>
  test.skip(testInfo.project.name !== "desktop-1280", "A URL reads the same at every width; run once, on desktop.");

// Proves an in-app step stayed in this document: checked after the click (the click used
// pushState) and again after Back (Back ran the popstate reader). A goto, goto, goBack
// sequence would re-test only the read at mount.
const markDocument = (page: Page) => page.evaluate(() => { document.body.dataset.routesMark = "kept"; });
const expectSameDocument = (page: Page, step: string) =>
  expect(page.locator("body"), `${step} loaded a new page instead of following the URL in this one`)
    .toHaveAttribute("data-routes-mark", "kept");
const unknownCard = (page: Page, id: string) => page.locator(".empty-state-card").filter({ hasText: id });

test("navigate: a view change leaves the last view's query behind, the open view adds no entry, Back returns", async ({ page }, testInfo) => {
  desktopOnly(testInfo);
  await page.goto("/workspace/ops?tab=alerts");
  const sidebar = page.getByRole("navigation", { name: "Workspaces" });
  await expect(page.getByRole("navigation", { name: "Operational control views" }).getByRole("button", { name: "Alerts", exact: true }))
    .toHaveAttribute("aria-current", "true");
  await markDocument(page);
  await sidebar.getByRole("button", { name: /^Pipeline Builder/ }).click();
  await expect(page, "the view change carried the last view's query or a bare '?'").toHaveURL(/\/workspace\/pipeline$/);
  const entries = await page.evaluate(() => history.length);
  await sidebar.getByRole("button", { name: /^Pipeline Builder/ }).click();
  expect(await page.evaluate(() => history.length), "opening the view already open added a history entry").toBe(entries);
  await page.goBack();
  await expect(page).toHaveURL(/\/workspace\/ops\?tab=alerts$/);
  await expect(page.getByRole("navigation", { name: "Operational control views" }).getByRole("button", { name: "Alerts", exact: true }))
    .toHaveAttribute("aria-current", "true");
  await expectSameDocument(page, "Back to the last view");
});

test("ops: ?tab= opens that tab, Back restores the one before, an unknown tab is named", async ({ page }, testInfo) => {
  desktopOnly(testInfo);
  const tabs = page.getByRole("navigation", { name: "Operational control views" });
  const tab = (name: string) => tabs.getByRole("button", { name, exact: true });

  await page.goto("/workspace/ops");
  await expect(tab("Command Center")).toHaveAttribute("aria-current", "true");
  await expect(page).toHaveURL(/\/workspace\/ops$/);

  await page.goto("/workspace/ops?tab=alerts");
  await expect(tab("Alerts"), "the URL's tab, not Command Center").toHaveAttribute("aria-current", "true");

  await markDocument(page);
  await tab("Incidents").click();
  await expect(page).toHaveURL(/\/workspace\/ops\?tab=incidents$/);
  await expect(page.getByRole("heading", { name: "Incident Queue" })).toBeVisible();
  await expectSameDocument(page, "choosing a tab");

  await page.goBack();
  await expect(tab("Alerts"), "Back did not restore the tab before").toHaveAttribute("aria-current", "true");
  await expect(page.getByRole("heading", { name: "Alert Rules" })).toBeVisible();
  await expect(page).toHaveURL(/\/workspace\/ops\?tab=alerts$/);
  await expectSameDocument(page, "Back");

  await tab("Command Center").click();
  await expect(page, "the default tab wrote itself into the URL").toHaveURL(/\/workspace\/ops$/);

  // The open tab under another spelling is the same place, and adds no entry.
  await page.goto("/workspace/ops?tab=command");
  let entries = await page.evaluate(() => history.length);
  await tab("Command Center").click();
  expect(await page.evaluate(() => history.length), "the open tab, spelled ?tab=command, added a history entry").toBe(entries);
  await page.goto("/workspace/ops?tab=alerts&utm=x");
  entries = await page.evaluate(() => history.length);
  await tab("Alerts").click();
  expect(await page.evaluate(() => history.length), "a param no screen reads made the open tab a new place").toBe(entries);

  await page.goto("/workspace/ops?tab=no_such_tab");
  await expect(unknownCard(page, "no_such_tab"), "an unknown tab was not named").toBeVisible();
  await expect(tabs.locator("[aria-current]"), "an unknown tab marked a tab current").toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Live Operational Feed" }), "an unknown tab fell back to Command Center").toHaveCount(0);
});

test("ops: Back from a tab that threw lands on the tab before, working", async ({ page }, testInfo) => {
  desktopOnly(testInfo);
  // A reliability summary whose runs are not a list makes the Reliability tab throw.
  await page.route((url) => url.pathname === "/reliability/summary",
                   (route) => route.fulfill({ json: { latest_contract_runs: "not a list" } }));
  await page.goto("/workspace/ops?tab=alerts");
  await page.getByRole("navigation", { name: "Operational control views" }).getByRole("button", { name: "Reliability", exact: true }).click();
  const failed = page.getByRole("alert").filter({ hasText: "Operational Control failed." });
  await expect(failed, "the tab did not throw, so this proves nothing").toBeVisible();
  await page.goBack();
  await expect(page).toHaveURL(/\/workspace\/ops\?tab=alerts$/);
  await expect(failed, "the failure of the tab left behind stayed over the one Back returned to").toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Alert Rules" })).toBeVisible();
});

test("navigate: signing in from a deep link comes back to it, query and all", async ({ page }, testInfo) => {
  desktopOnly(testInfo);
  await page.route((url) => url.pathname === "/auth/session",
                   (route) => route.fulfill({ json: { authenticated: false, auth_mode: "local" } }));
  await page.goto("/workspace/ops?tab=incidents");
  const signIn = page.getByRole("link", { name: "Sign in" });
  await expect(signIn, "sign-in drops the query, so a deep link lands on the view's default")
    .toHaveAttribute("href", "/auth/login?next=%2Fworkspace%2Fops%3Ftab%3Dincidents");
  await page.getByRole("navigation", { name: "Operational control views" }).getByRole("button", { name: "Alerts", exact: true }).click();
  await expect(signIn, "the sign-in link kept the tab it was drawn on").toHaveAttribute("href", "/auth/login?next=%2Fworkspace%2Fops%3Ftab%3Dalerts");
  await signIn.click();
  await expect(page, "signing in did not come back to the tab").toHaveURL(/\/workspace\/ops\?tab=alerts$/);
});
