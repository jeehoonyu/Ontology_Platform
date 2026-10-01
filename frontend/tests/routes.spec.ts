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
const stamp = () => `${Date.now()}_${Math.random().toString(36).slice(2, 6)}`;
async function post<T = unknown>(page: Page, path: string, data: unknown): Promise<T> {
  const response = await page.request.post(path, { data });
  expect(response.ok(), `${path}: ${response.status()} ${await response.text()}`).toBeTruthy();
  return (await response.json()) as T;
}

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

test("dataset: ?dataset= opens that dataset, Back restores the one before, an unknown id is named", async ({ page }, testInfo) => {
  desktopOnly(testInfo);
  const s = stamp();
  // A decoy first, so a fresh database's first dataset is not one of ours.
  for (const key of ["0", "a", "b"]) {
    await post(page, "/data-assets", { id: `route_${key}_${s}`, display_name: `Route ${key.toUpperCase()} ${s}`, kind: "dataset", asset_schema: {}, records: [] });
  }
  const ours = [{ id: `route_a_${s}`, name: `Route A ${s}` }, { id: `route_b_${s}`, name: `Route B ${s}` }];
  const datasets = page.locator(".panel").filter({ has: page.getByRole("heading", { name: /^Datasets \d+$/ }) });
  const records = (name: string) => page.getByRole("heading", { name: `Records — ${name}` });

  await page.goto("/workspace/data-media");
  await expect(datasets.locator(".resource-row.selected")).toHaveCount(1);
  const opened = (await datasets.locator(".resource-row.selected strong").textContent()) || "";
  await expect(page, "the default dataset wrote itself into the URL").toHaveURL(/\/workspace\/data-media$/);
  const target = ours.find((item) => item.name !== opened)!;
  const other = ours.find((item) => item !== target)!;

  await page.goto(`/workspace/data-media?dataset=${target.id}`);
  await expect(records(target.name), "the URL's dataset, not the first").toBeVisible();
  await expect(datasets.locator(".resource-row.selected strong")).toHaveText(target.name);

  await markDocument(page);
  await datasets.locator(".resource-row").filter({ hasText: other.name }).click();
  await expect(page).toHaveURL(new RegExp(`\\?dataset=${other.id}$`));
  await expect(records(other.name)).toBeVisible();
  await expectSameDocument(page, "choosing a dataset");
  // A file into this one: its receipt belongs to it, and must not follow Back to the one before.
  const receipt = page.locator(".kv-grid").filter({ hasText: "source format" });
  await page.locator('input[type="file"]').setInputFiles({ name: "route.csv", mimeType: "text/csv", buffer: Buffer.from("id,name\n1,one\n") });
  await expect(receipt, "the upload left no receipt, so its absence below proves nothing").toBeVisible();

  await page.goBack();
  await expect(records(target.name), "Back did not restore the dataset before").toBeVisible();
  await expect(receipt, "the last dataset's upload receipt followed Back to the one before").toHaveCount(0);
  await expect(page).toHaveURL(new RegExp(`\\?dataset=${target.id}$`));
  await expectSameDocument(page, "Back");

  // A created dataset opens under its own id, pushed, so Back returns to the one before.
  await page.getByPlaceholder("New dataset name").fill(`Route C ${s}`);
  await page.getByRole("button", { name: "Create dataset" }).click();
  await expect(records(`Route C ${s}`), "a created dataset did not open").toBeVisible();
  await expect(page, "the created dataset is not the URL's").toHaveURL(new RegExp(`\\?dataset=route_c_${s}$`));
  await page.goBack();
  await expect(records(target.name), "Back from a created dataset did not return to the one before").toBeVisible();
  await expect(page).toHaveURL(new RegExp(`\\?dataset=${target.id}$`));
  await expectSameDocument(page, "Back from a created dataset");

  await page.goto(`/workspace/data-media?dataset=no_such_dataset_${s}`);
  await expect(unknownCard(page, `no_such_dataset_${s}`), "an unknown dataset was not named").toBeVisible();
  // The list loaded, so a fallback to its first dataset would have happened by now.
  await expect(datasets.locator(".resource-row").filter({ hasText: target.name })).toBeVisible();
  await expect(datasets.locator(".resource-row.selected"), "an unknown dataset fell back to the first").toHaveCount(0);
  await expect(page.getByRole("link", { name: "Download raw file" })).toHaveCount(0);

  // In the page, from a dataset to one that does not exist, as an in-app link would go, with the
  // unknown one's answer held back: while it is on its way, nothing of the last dataset stays on
  // screen under the new id, and once it lands the id is named.
  await page.goto(`/workspace/data-media?dataset=${target.id}`);
  await expect(records(target.name)).toBeVisible();
  const held = `no_such_held_${s}`;
  await page.route((url) => url.pathname === `/data-assets/${held}`, async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 1500));
    await route.continue();
  });
  await page.evaluate((id) => {
    history.pushState({}, "", `/workspace/data-media?dataset=${id}`);
    dispatchEvent(new PopStateEvent("popstate"));
  }, held);
  await page.waitForTimeout(400);
  expect(await records(target.name).count(), "the last dataset's records stayed while the next one's answer was on its way").toBe(0);
  expect(await page.getByText("Developer evidence: selected dataset detail").count(), "the last dataset's detail stayed under the next id").toBe(0);
  await expect(unknownCard(page, held)).toBeVisible();
  await expect(datasets.locator(".resource-row.selected"), "an unknown dataset reached in the page fell back to the first").toHaveCount(0);
  await expect(records(target.name), "the last dataset's records stayed under an unknown one").toHaveCount(0);
});

test("dataset: a 403 names the id as a 404 does; any other failure is a failure, not an unknown", async ({ page }, testInfo) => {
  desktopOnly(testInfo);
  const s = stamp();
  const id = `route_err_${s}`;
  await post(page, "/data-assets", { id, display_name: `Route Err ${s}`, kind: "dataset", asset_schema: {}, records: [] });
  let status = 500;
  await page.route((url) => url.pathname === `/data-assets/${id}`,
                   (route) => route.fulfill({ status, json: { detail: `held back by the test (${status})` } }));

  await page.goto(`/workspace/data-media?dataset=${id}`);
  await expect(page.getByText("held back by the test (500)"), "a server failure was not shown as one").toBeVisible();
  await expect(unknownCard(page, id), "a server failure was called an unknown dataset").toHaveCount(0);

  status = 403;
  await page.goto(`/workspace/data-media?dataset=${id}`);
  await expect(unknownCard(page, id), "a dataset this person cannot open was not named as unknown").toBeVisible();
  await expect(page.getByText("held back by the test (403)"), "a 403 leaked the server's words").toHaveCount(0);

  // A failed upload is about the dataset it was for; choosing another clears it.
  const others = [`route_up_a_${s}`, `route_up_b_${s}`];
  for (const other of others) {
    await post(page, "/data-assets", { id: other, display_name: other, kind: "dataset", asset_schema: {}, records: [] });
  }
  await page.route((url) => url.pathname === `/data-assets/${others[0]}/upload`,
                   (route) => route.fulfill({ status: 500, json: { detail: "upload held back by the test" } }));
  await page.goto(`/workspace/data-media?dataset=${others[0]}`);
  await page.locator('input[type="file"]').setInputFiles({ name: "route.csv", mimeType: "text/csv", buffer: Buffer.from("id\n1\n") });
  await expect(page.getByText("upload held back by the test"), "the failed upload said nothing").toBeVisible();
  await page.locator(".resource-row").filter({ hasText: others[1] }).click();
  await expect(page).toHaveURL(new RegExp(`\\?dataset=${others[1]}$`));
  await expect(page.getByText("upload held back by the test"), "one dataset's failed upload stayed over the next").toHaveCount(0);
});
