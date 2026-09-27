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

test("pipeline_graph: ?graph= opens that pipeline, Back restores the one before, an unknown id is named", async ({ page }, testInfo) => {
  desktopOnly(testInfo);
  const s = stamp();
  const ours: Array<{ id: string; name: string }> = [];
  for (const key of ["A", "B"]) {
    const name = `Route ${key} ${s}`;
    const created = await post<{ id: string }>(page, "/pipeline-builder/graphs", { display_name: name, description: "", nodes: [], edges: [], parameters: {}, status: "DRAFT" });
    ours.push({ id: created.id, name });
  }
  const title = page.locator(".pipeline-workbench-page .workspace-header strong");
  const row = (name: string) => page.locator(".output-rail .resource-row").filter({ hasText: name });
  const strip = page.locator(".workbench-status-strip");

  await page.goto("/workspace/pipeline");
  await expect(title).not.toHaveText("Pipeline graph");
  const opened = (await title.textContent()) || "";
  await expect(page, "the default pipeline wrote itself into the URL").toHaveURL(/\/workspace\/pipeline$/);
  const target = ours.find((item) => item.name !== opened)!;
  const other = ours.find((item) => item !== target)!;

  await page.goto(`/workspace/pipeline?graph=${target.id}`);
  await expect(title, "the URL's pipeline, not the newest").toHaveText(target.name);
  await expect(row(target.name)).toHaveClass(/selected/);

  await markDocument(page);
  await row(other.name).click();
  await expect(page).toHaveURL(new RegExp(`\\?graph=${other.id}$`));
  await expect(title).toHaveText(other.name);
  await expectSameDocument(page, "choosing a pipeline");

  await page.goBack();
  await expect(title, "Back did not restore the pipeline before").toHaveText(target.name);
  await expect(page).toHaveURL(new RegExp(`\\?graph=${target.id}$`));
  await expectSameDocument(page, "Back");

  // A new pipeline opens under its own id, and asks for its canvas once.
  const canvasFor: string[] = [];
  page.on("request", (request) => {
    const match = /\/ui-state\/pipeline\/([^/?]+)\/canvas/.exec(new URL(request.url()).pathname);
    if (match) canvasFor.push(decodeURIComponent(match[1]));
  });
  const createdResponse = page.waitForResponse((response) => response.request().method() === "POST"
    && new URL(response.url()).pathname === "/pipeline-builder/graphs");
  await page.getByRole("button", { name: "New pipeline" }).click();
  const createdId = ((await (await createdResponse).json()) as { id: string }).id;
  await expect(page.getByText("Pipeline draft created")).toBeVisible();
  await expect(page, "the new pipeline is not the URL's").toHaveURL(new RegExp(`\\?graph=${createdId}$`));
  await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {});
  expect(canvasFor.filter((id) => id === createdId), "a new pipeline asked for its canvas more than once").toHaveLength(1);
  await expect(unknownCard(page, createdId)).toHaveCount(0);
  await page.goBack();
  await expect(title, "Back from a new pipeline did not return to the one before").toHaveText(target.name);

  await page.goto(`/workspace/pipeline?graph=no_such_graph_${s}`);
  await expect(unknownCard(page, `no_such_graph_${s}`), "an unknown pipeline was not named").toBeVisible();
  await expect(page.locator(".pipeline-canvas"), "an unknown pipeline drew a canvas").toHaveCount(0);
  // The list loaded, so a fallback to the newest would have happened by now.
  await expect(row(target.name)).toBeVisible();
  await expect(page.locator(".output-rail .resource-row.selected"), "an unknown pipeline fell back to the newest").toHaveCount(0);
  await expect(strip).toContainText("Pipeline not found");
  await expect(page.getByRole("button", { name: "Deploy", exact: true })).toBeDisabled();

  // In the page, to a pipeline that does not exist and Back: its failure never shows over a real one.
  await page.goto(`/workspace/pipeline?graph=${target.id}`);
  await expect(title).toHaveText(target.name);
  await page.evaluate((id) => {
    history.pushState({}, "", `/workspace/pipeline?graph=${id}`);
    dispatchEvent(new PopStateEvent("popstate"));
  }, `no_such_graph_${s}`);
  await expect(unknownCard(page, `no_such_graph_${s}`)).toBeVisible();
  // Back, with the real pipeline's canvas held back: while it is on its way, nothing of the
  // unknown one shows over it.
  await page.route((url) => url.pathname === `/ui-state/pipeline/${target.id}/canvas`, async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 1500));
    await route.continue();
  });
  await page.goBack();
  await expect(page).toHaveURL(new RegExp(`\\?graph=${target.id}$`));
  await page.waitForTimeout(300);
  expect(await page.locator(".empty-state-card").filter({ hasText: "No pipeline named" }).count(),
         "the unknown pipeline's card stayed while the real one loaded").toBe(0);
  expect(await strip.textContent(), "the unknown pipeline's failure stayed in the strip while the real one loaded").not.toContain("not found");
  expect(await page.getByRole("button", { name: "Deploy", exact: true }).isDisabled(), "Deploy stayed off for the real pipeline while it loaded").toBe(false);
  await expect(title, "Back from an unknown pipeline did not return").toHaveText(target.name);
  await page.unrouteAll({ behavior: "ignoreErrors" });
});

test("pipeline_graph: one pipeline's outputs never show under another while the next one's load", async ({ page }, testInfo) => {
  desktopOnly(testInfo);
  const s = stamp();
  const withOutput = await post<{ id: string }>(page, "/pipeline-builder/graphs", {
    display_name: `Route Out ${s}`, description: "", edges: [], parameters: {}, status: "DRAFT",
    nodes: [{ id: "out", type: "dataset_output", label: `Route output ${s}`, config: {}, position: { x: 80, y: 80 } }],
  });
  const empty = await post<{ id: string }>(page, "/pipeline-builder/graphs", { display_name: `Route Empty ${s}`, description: "", nodes: [], edges: [], parameters: {}, status: "DRAFT" });
  const outputsPanel = page.locator(".panel").filter({ has: page.getByRole("heading", { name: "Pipeline Outputs" }) });
  await page.goto(`/workspace/pipeline?graph=${withOutput.id}`);
  await expect(outputsPanel, "the pipeline's output node is not listed, so its absence below proves nothing").toContainText(`Route output ${s}`);
  for (const suffix of ["canvas", "outputs"]) {
    await page.route((url) => url.pathname === `/ui-state/pipeline/${empty.id}/${suffix}`, async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 1500));
      await route.continue();
    });
  }
  await page.locator(".output-rail .resource-row").filter({ hasText: `Route Empty ${s}` }).click();
  await expect(page).toHaveURL(new RegExp(`\\?graph=${empty.id}$`));
  await page.waitForTimeout(300);
  expect(await outputsPanel.getByText(`Route output ${s}`).count(), "one pipeline's outputs stayed under another while its own loaded").toBe(0);
  await page.unrouteAll({ behavior: "ignoreErrors" });
});

test("pipeline_graph: a new pipeline that lands after the user has moved on does not pull them back", async ({ page }, testInfo) => {
  desktopOnly(testInfo);
  // A pipeline of its own, so the page has one open whatever ran before.
  await post(page, "/pipeline-builder/graphs", { display_name: `Route Late ${stamp()}`, description: "", nodes: [], edges: [], parameters: {}, status: "DRAFT" });
  await page.goto("/workspace/pipeline");
  await expect(page.locator(".pipeline-workbench-page .workspace-header strong")).not.toHaveText("Pipeline graph");
  await page.route((url) => url.pathname === "/pipeline-builder/graphs", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    await new Promise((resolve) => setTimeout(resolve, 1500));
    await route.continue();
  });
  const created = page.waitForResponse((response) => response.request().method() === "POST" && new URL(response.url()).pathname === "/pipeline-builder/graphs");
  await page.getByRole("button", { name: "New pipeline" }).click();
  await page.getByRole("navigation", { name: "Workspaces" }).getByRole("button", { name: /^Operational Control/ }).click();
  await expect(page).toHaveURL(/\/workspace\/ops$/);
  await created;
  await page.waitForTimeout(500);
  await expect(page, "a pipeline created after the user left pulled them back to it").toHaveURL(/\/workspace\/ops$/);
  await page.unrouteAll({ behavior: "ignoreErrors" });
});

test("pipeline_graph: a 403 names the id as a 404 does; a server failure is a failure; the server's link opens the pipeline", async ({ page }, testInfo) => {
  desktopOnly(testInfo);
  const s = stamp();
  const name = `Route Err ${s}`;
  const { id } = await post<{ id: string }>(page, "/pipeline-builder/graphs", { display_name: name, description: "", nodes: [], edges: [], parameters: {}, status: "DRAFT" });
  const other = await post<{ id: string }>(page, "/pipeline-builder/graphs", { display_name: `Route Ok ${s}`, description: "", nodes: [], edges: [], parameters: {}, status: "DRAFT" });
  // 0: answer, slowly; otherwise fulfil with this status.
  let status = 500;
  await page.route((url) => url.pathname === `/ui-state/pipeline/${id}/canvas`, async (route) => {
    if (status === 0) {
      await new Promise((resolve) => setTimeout(resolve, 1500));
      return route.continue();
    }
    return route.fulfill({ status, json: { detail: `held back by the test (${status})` } });
  });
  const strip = page.locator(".workbench-status-strip");

  await page.goto(`/workspace/pipeline?graph=${id}`);
  await expect(strip, "a server failure was not shown as one").toContainText("Canvas failed to load");
  await expect(unknownCard(page, id), "a server failure was called an unknown pipeline").toHaveCount(0);

  // Another pipeline, then Back to the one that failed, which now answers, slowly: while it is
  // asked again it is loading, not its old failure.
  await page.locator(".output-rail .resource-row").filter({ hasText: `Route Ok ${s}` }).click();
  await expect(page).toHaveURL(new RegExp(`\\?graph=${other.id}$`));
  await expect(page.locator(".pipeline-workbench-page .workspace-header strong")).toHaveText(`Route Ok ${s}`);
  status = 0;
  await page.goBack();
  await expect(page).toHaveURL(new RegExp(`\\?graph=${id}$`));
  await page.waitForTimeout(300);
  expect(await strip.textContent(), "a pipeline asked again showed its old failure instead of loading").not.toContain("Canvas failed to load");
  await expect(page.locator(".pipeline-workbench-page .workspace-header strong")).toHaveText(name);

  status = 403;
  await page.goto(`/workspace/pipeline?graph=${id}`);
  await expect(unknownCard(page, id), "a pipeline this person cannot open was not named as unknown").toBeVisible();
  await expect(strip).toContainText("Pipeline not found");
  await page.unrouteAll({ behavior: "ignoreErrors" });

  // The server's link, from the Command Center's evidence, opens the pipeline it names.
  expect((await page.request.post("/scenarios/asset-reliability/bootstrap", { data: {} })).ok()).toBeTruthy();
  const state = await (await page.request.get("/scenarios/asset-reliability/workflow-state")).json() as
    { evidence_links: Array<{ kind: string; id: string | null; href: string }> };
  const link = state.evidence_links.find((item) => item.kind === "pipeline_graph" && item.id);
  expect(link, "the Command Center names no pipeline").toBeTruthy();
  expect(link!.href, "the server spelled the pipeline's URL by hand, or not at all").toBe(`/workspace/pipeline?graph=${encodeURIComponent(link!.id!)}`);
  const graph = await (await page.request.get(`/pipeline-builder/graphs/${encodeURIComponent(link!.id!)}`)).json() as { display_name: string };
  // The stepper's pipeline step names the same pipeline, the same way.
  const workflow = state as unknown as { steps: Array<{ id: string; href: string; graph_id: string | null }> };
  const step = workflow.steps.find((item) => item.id === "pipeline");
  expect(step?.graph_id, "the stepper's pipeline step names another pipeline than the evidence").toBe(link!.id);
  expect(step?.href, "the stepper spelled the pipeline's URL by hand, or not at all").toBe(link!.href);
  // A newer pipeline is now the default, so the link opening its own proves the reader.
  await post(page, "/pipeline-builder/graphs", { display_name: `Route Newer ${s}`, description: "", nodes: [], edges: [], parameters: {}, status: "DRAFT" });
  await page.goto(link!.href);
  await expect(page.locator(".pipeline-workbench-page .workspace-header strong"), "the server's link did not open its pipeline")
    .toHaveText(graph.display_name);
});

test("dataset: a dataset created after the user chose another does not open over their choice", async ({ page }, testInfo) => {
  desktopOnly(testInfo);
  const s = stamp();
  for (const key of ["x", "y"]) {
    await post(page, "/data-assets", { id: `route_${key}_${s}`, display_name: `Route ${key.toUpperCase()} ${s}`, kind: "dataset", asset_schema: {}, records: [] });
  }
  await page.goto(`/workspace/data-media?dataset=route_x_${s}`);
  await expect(page.getByRole("heading", { name: `Records — Route X ${s}` })).toBeVisible();
  await page.route((url) => url.pathname === "/data-assets", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    await new Promise((resolve) => setTimeout(resolve, 1500));
    await route.continue();
  });
  const created = page.waitForResponse((response) => response.request().method() === "POST" && new URL(response.url()).pathname === "/data-assets");
  await page.getByPlaceholder("New dataset name").fill(`Route Late ${s}`);
  await page.getByRole("button", { name: "Create dataset" }).click();
  await page.locator(".resource-row").filter({ hasText: `Route Y ${s}` }).click();
  await expect(page).toHaveURL(new RegExp(`\\?dataset=route_y_${s}$`));
  await created;
  await page.waitForTimeout(500);
  await expect(page, "a dataset created after the user chose another opened over their choice").toHaveURL(new RegExp(`\\?dataset=route_y_${s}$`));
  await expect(page.getByRole("heading", { name: `Records — Route Y ${s}` })).toBeVisible();
  await page.unrouteAll({ behavior: "ignoreErrors" });
});

// One screen serves the four builders; each has its own view and kind in routes.json.
const BUILDERS = [
  ["workshop", "workshop", "Workshop"],
  ["aip_logic", "aip", "AIP Logic"],
  ["investigation_graph", "investigations", "Investigations"],
  ["entity_resolution", "entity-resolution", "Entity Resolution"],
] as const;
const artifactState = (kind: string, label?: string) => ({
  nodes: label ? [{ id: "route_node", position: { x: 80, y: 80 }, data: { label, nodeType: "note" } }] : [],
  edges: [], ...(kind === "workshop" ? { widgets: [] } : {}),
});

for (const [kind, view, title] of BUILDERS) {
  test(`${kind}: ?artifact= opens that artifact, Back restores the one before, an unknown id is named`, async ({ page }, testInfo) => {
    desktopOnly(testInfo);
    const s = stamp();
    // Each with a node of its own, so what is on the canvas says whose it is.
    const ours: Array<{ id: string; name: string; node: string }> = [];
    for (const key of ["A", "B"]) {
      const name = `Route ${key} ${s}`;
      const node = `Route ${key} node ${s}`;
      const created = await post<{ id: string }>(page, "/artifacts", { artifact_type: kind, display_name: name, state: artifactState(kind, node) });
      ours.push({ id: created.id, name, node });
    }
    const picker = page.getByLabel(`${title} artifact`);
    const onCanvas = (label: string) => page.locator(".react-flow__node").filter({ hasText: label });
    const undo = page.getByRole("button", { name: "Undo", exact: true });

    await page.goto(`/workspace/${view}`);
    await expect(picker).toBeVisible();
    const opened = await picker.inputValue();
    await expect(page, "the default artifact wrote itself into the URL").toHaveURL(new RegExp(`/workspace/${view}$`));
    const target = ours.find((item) => item.id !== opened)!;
    const other = ours.find((item) => item !== target)!;

    await page.goto(`/workspace/${view}?artifact=${target.id}`);
    await expect(picker, "the URL's artifact, not the newest").toHaveValue(target.id);
    await expect(onCanvas(target.node), "the URL's artifact is not the one drawn").toBeVisible();

    await markDocument(page);
    await picker.selectOption(other.id);
    await expect(page).toHaveURL(new RegExp(`/workspace/${view}\\?artifact=${other.id}$`));
    await expect(onCanvas(other.node)).toBeVisible();
    await expectSameDocument(page, "choosing an artifact");
    // Work on this one: a preview, and a node added, which Undo could take back.
    await page.getByRole("button", { name: "Preview", exact: true }).click();
    await expect(page.locator(".preview-metrics"), "the preview did not run, so its absence below proves nothing").toBeVisible();
    await page.locator(".node-library-list button").first().click();
    await expect(undo, "adding a node left nothing to undo, so its absence below proves nothing").toBeEnabled();

    await page.goBack();
    await expect(picker, "Back did not restore the artifact before").toHaveValue(target.id);
    await expect(page).toHaveURL(new RegExp(`/workspace/${view}\\?artifact=${target.id}$`));
    await expect(onCanvas(target.node), "Back did not draw the artifact before").toBeVisible();
    await expect(onCanvas(other.node), "the last artifact's node stayed on the canvas").toHaveCount(0);
    await expect(page.locator(".preview-metrics"), "the last artifact's preview stayed under this one").toHaveCount(0);
    await expect(undo, "the last artifact's history could be undone onto this one").toBeDisabled();
    await expectSameDocument(page, "Back");

    // Made after the page fetched its list, which is cached for 15 s: the list is asked again
    // before the id is called unknown.
    // The list asked again is held back: while it is on its way, the id is neither called
    // unknown nor answered with the artifact before.
    const late = await post<{ id: string }>(page, "/artifacts", { artifact_type: kind, display_name: `Route C ${s}`, state: artifactState(kind) });
    await page.route((url) => url.pathname === "/artifacts" && url.searchParams.get("artifact_type") === kind, async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 1500));
      await route.continue();
    });
    await page.evaluate(({ path }) => {
      history.pushState({}, "", path);
      dispatchEvent(new PopStateEvent("popstate"));
    }, { path: `/workspace/${view}?artifact=${late.id}` });
    await page.waitForTimeout(400);
    expect(await unknownCard(page, late.id).count(), "an artifact made after the list was fetched was called unknown before the list was asked again").toBe(0);
    expect(await page.locator(".visual-builder-shell").count(), "the artifact before stayed on screen under the next one's id").toBe(0);
    await expect(picker, "an artifact made after the list was fetched was not opened").toHaveValue(late.id);
    await expect(unknownCard(page, late.id)).toHaveCount(0);
    await page.unrouteAll({ behavior: "ignoreErrors" });

    await page.goto(`/workspace/${view}?artifact=no_such_artifact_${s}`);
    await expect(unknownCard(page, `no_such_artifact_${s}`), "an unknown artifact was not named").toBeVisible();
    await expect(page.locator(".visual-builder-shell"), "an unknown id fell back to the newest artifact").toHaveCount(0);
  });
}

test("aip_logic: a draft created from an empty builder opens under its own id", async ({ page }, testInfo) => {
  desktopOnly(testInfo);
  // An empty list, so the builder offers its first draft; the real list answers afterwards.
  await page.route((url) => url.pathname === "/artifacts" && url.searchParams.get("artifact_type") === "aip_logic", async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    return route.fulfill({ json: [] });
  });
  await page.goto("/workspace/aip");
  const create = page.getByRole("button", { name: "Create draft" });
  await expect(create).toBeVisible();
  await page.unrouteAll({ behavior: "ignoreErrors" });
  const created = page.waitForResponse((response) => response.request().method() === "POST" && new URL(response.url()).pathname === "/artifacts");
  await create.click();
  const { id } = await (await created).json() as { id: string };
  await expect(page, "a created draft is not the URL's").toHaveURL(new RegExp(`/workspace/aip\\?artifact=${id}$`));
  await expect(page.getByLabel("AIP Logic artifact")).toHaveValue(id);
  await expect(unknownCard(page, id), "a created draft was called unknown").toHaveCount(0);
});

test("aip_logic: a draft that lands after the user has moved on does not pull them back", async ({ page }, testInfo) => {
  desktopOnly(testInfo);
  await page.route((url) => url.pathname === "/artifacts" && url.searchParams.get("artifact_type") === "aip_logic", async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    return route.fulfill({ json: [] });
  });
  await page.route((url) => url.pathname === "/artifacts", async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    await new Promise((resolve) => setTimeout(resolve, 1500));
    await route.continue();
  });
  await page.goto("/workspace/aip");
  const created = page.waitForResponse((response) => response.request().method() === "POST" && new URL(response.url()).pathname === "/artifacts");
  await page.getByRole("button", { name: "Create draft" }).click();
  await page.getByRole("navigation", { name: "Workspaces" }).getByRole("button", { name: /^Operational Control/ }).click();
  await expect(page).toHaveURL(/\/workspace\/ops$/);
  await created;
  await page.waitForTimeout(500);
  await expect(page, "a draft created after the user left pulled them back to it").toHaveURL(/\/workspace\/ops$/);
  await page.unrouteAll({ behavior: "ignoreErrors" });
});

test("object: ?type=&object= open that type and object, Back restores both, unknown ids are named", async ({ page }, testInfo) => {
  desktopOnly(testInfo);
  const s = stamp();
  await post(page, "/data-assets", { id: `route_objects_${s}`, display_name: `Route objects ${s}`, kind: "dataset", asset_schema: {}, records: [] });
  const [decoy, a, b] = [`route_0_${s}`, `route_a_${s}`, `route_b_${s}`];
  for (const id of [decoy, a, b]) {
    await post(page, "/object-types", { id, display_name: id, description: "", properties: { name: { type: "string" } } });
    for (const n of [1, 2]) {
      await post(page, "/objects", { id: `${id}_${n}`, object_type_id: id, source_asset_id: `route_objects_${s}`, properties: { name: `${id} ${n}` } });
    }
  }
  const typeSelect = page.getByLabel("Object type");
  const table = page.locator(".explorer-table");
  const preview = page.locator(".object-profile-heading small");
  const hold = async (match: (url: URL) => boolean) => {
    await page.route(match, async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 1500));
      await route.continue();
    });
  };

  await page.goto("/workspace/object-explorer");
  await expect(typeSelect).not.toHaveValue("");
  const opened = await typeSelect.inputValue();
  await expect(page, "the default type wrote itself into the URL").toHaveURL(/\/workspace\/object-explorer$/);
  const target = [a, b].find((id) => id !== opened)!;
  const other = [a, b].find((id) => id !== target)!;

  await page.goto(`/workspace/object-explorer?type=${target}&object=${target}_1`);
  await expect(typeSelect, "the URL's type, not the first").toHaveValue(target);
  await expect(table).toContainText(`${target}_2`);
  await expect(preview, "the URL's object is not the one inspected").toHaveText(`${target}_1`);

  await markDocument(page);
  await table.getByRole("button", { name: `${target}_2`, exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`\\?type=${target}&object=${target}_2$`));
  await expect(preview).toHaveText(`${target}_2`);
  await expectSameDocument(page, "choosing an object");

  await typeSelect.selectOption(other);
  await expect(page, "a type change kept the last type's object").toHaveURL(new RegExp(`\\?type=${other}$`));
  await expect(table, "choosing a type did not query it").toContainText(`${other}_1`);
  await expect(page.locator(".object-profile-heading")).toHaveCount(0);

  // Back to the type before, with its query held back: while it is on its way, the last type's
  // rows are not shown under it.
  await hold((url) => url.pathname === "/object-explorer/query");
  await page.goBack();
  await expect(typeSelect, "Back did not restore the type before").toHaveValue(target);
  await page.waitForTimeout(300);
  expect(await table.getByText(`${other}_1`).count(), "the last type's rows stayed under the type Back returned to").toBe(0);
  expect(await page.locator(".explorer-results-header h2").textContent(), "the last type's results heading stayed under the type Back returned to").not.toBe(other);
  expect(await page.locator(".explorer-results-header span").first().textContent(), "the last type's result count stayed under the type Back returned to").toBe("Run an exploration");
  await expect(table).toContainText(`${target}_2`);
  await expect(preview).toHaveText(`${target}_2`);
  await page.unrouteAll({ behavior: "ignoreErrors" });

  // Back to the object before, with its profile held back: the last object is not shown meanwhile.
  await hold((url) => url.pathname === `/objects/${target}/${target}_1/profile`);
  await page.goBack();
  await page.waitForTimeout(300);
  expect(await page.locator(".object-profile-heading small").filter({ hasText: `${target}_2` }).count(),
         "the last object stayed in the inspector while the next one's profile was on its way").toBe(0);
  await expect(preview, "Back did not restore the object before").toHaveText(`${target}_1`);
  await expectSameDocument(page, "Back");
  await page.unrouteAll({ behavior: "ignoreErrors" });

  await page.goto(`/workspace/object-explorer?type=no_such_type_${s}`);
  await expect(unknownCard(page, `no_such_type_${s}`), "an unknown type was not named").toBeVisible();
  await expect(table, "an unknown type drew the first type's objects").toHaveCount(0);
  await expect(typeSelect, "the type select showed another type for an unknown one").toHaveValue(`no_such_type_${s}`);
  await expect(page.getByRole("button", { name: "Run", exact: true })).toBeDisabled();

  // Under an unknown type, the type is what is unknown: one card, not a second for the object.
  await page.goto(`/workspace/object-explorer?type=no_such_type_${s}&object=x_${s}`);
  await expect(unknownCard(page, `no_such_type_${s}`)).toBeVisible();
  await page.waitForTimeout(500);
  await expect(page.locator(".empty-state-card"), "an unknown type named its object as missing too").toHaveCount(1);

  await page.goto(`/workspace/object-explorer?type=${target}&object=no_such_object_${s}`);
  await expect(page.locator(".explorer-inspector .empty-state-card"), "an unknown object was not named").toContainText(`no_such_object_${s}`);
  await expect(table).toContainText(`${target}_1`);

  // Search opens an object type in Object Explorer, to its objects, with the URL the table builds.
  const found = await (await page.request.get(`/search?q=${encodeURIComponent(target)}&kind=object_type`)).json() as
    { results: Array<{ kind: string; id?: string; resource_id?: string; url: string }> };
  const hit = found.results.find((item) => item.kind === "object_type" && (item.id === target || item.resource_id === target));
  expect(hit?.url, "search's object type link is not the one the table builds").toBe(`/workspace/object-explorer?type=${target}`);

  // The server's link, from the Command Center's evidence, opens the object it names.
  expect((await page.request.post("/scenarios/asset-reliability/bootstrap", { data: {} })).ok()).toBeTruthy();
  const state = await (await page.request.get("/scenarios/asset-reliability/workflow-state")).json() as
    { evidence_links: Array<{ kind: string; id: string | null; href: string }> };
  const asset = state.evidence_links.find((item) => item.kind === "asset" && item.id);
  expect(asset, "the Command Center names no asset").toBeTruthy();
  expect(asset!.href, "the server's asset link is not the one the table builds").toMatch(new RegExp(`^/workspace/object-explorer\\?type=[^&]+&object=${encodeURIComponent(asset!.id!)}$`));
  await page.goto(asset!.href);
  await expect(preview, "the server's link did not open its object").toHaveText(asset!.id!);
});

test("object: a profile that failed says so for its own object only, and a click on the open object asks again", async ({ page }, testInfo) => {
  desktopOnly(testInfo);
  const s = stamp();
  const type = `route_fail_${s}`;
  await post(page, "/data-assets", { id: `route_fail_objects_${s}`, display_name: `Route fail objects ${s}`, kind: "dataset", asset_schema: {}, records: [] });
  await post(page, "/object-types", { id: type, display_name: type, description: "", properties: { name: { type: "string" } } });
  for (const n of [1, 2]) {
    await post(page, "/objects", { id: `${type}_${n}`, object_type_id: type, source_asset_id: `route_fail_objects_${s}`, properties: { name: `${type} ${n}` } });
  }
  let failing = true;
  await page.route((url) => url.pathname === `/objects/${type}/${type}_1/profile`, async (route) => {
    if (failing) return route.fulfill({ status: 500, json: { detail: "profile held back by the test" } });
    return route.continue();
  });
  const table = page.locator(".explorer-table");
  const preview = page.locator(".object-profile-heading small");
  const failure = page.locator(".explorer-inspector").getByText("profile held back by the test");

  await page.goto(`/workspace/object-explorer?type=${type}&object=${type}_1`);
  await expect(failure, "a profile that failed did not say so").toBeVisible();

  // The next object's profile held back: while it is on its way, the failure is not shown for it.
  await page.route((url) => url.pathname === `/objects/${type}/${type}_2/profile`, async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 1500));
    await route.continue();
  });
  await table.getByRole("button", { name: `${type}_2`, exact: true }).click();
  await page.waitForTimeout(300);
  expect(await failure.count(), "one object's failed profile stayed over the next while its profile was on its way").toBe(0);
  await expect(preview).toHaveText(`${type}_2`);
  await expect(failure, "one object's failed profile stayed over the next").toHaveCount(0);

  await page.goBack();
  await expect(failure, "Back to the object whose profile failed did not say so").toBeVisible();

  // The server answers now; a click on the object already open asks again, as it always did.
  failing = false;
  await table.getByRole("button", { name: `${type}_1`, exact: true }).click();
  await expect(preview, "a click on the open object did not ask for its profile again").toHaveText(`${type}_1`);
  await expect(failure).toHaveCount(0);
  await page.unrouteAll({ behavior: "ignoreErrors" });
});

test("object: an action dialog open on one type closes when Back leaves it", async ({ page }, testInfo) => {
  desktopOnly(testInfo);
  expect((await page.request.post("/scenarios/asset-reliability/bootstrap", { data: {} })).ok()).toBeTruthy();
  const s = stamp();
  const type = `route_dialog_${s}`;
  await post(page, "/object-types", { id: type, display_name: type, description: "", properties: { name: { type: "string" } } });
  await page.goto(`/workspace/object-explorer?type=${type}`);
  await page.getByLabel("Object type").selectOption("asset");
  await expect(page).toHaveURL(/\?type=asset$/);
  const table = page.locator(".explorer-table");
  await table.locator("tbody input[type='checkbox']").first().check();
  await page.locator(".explorer-action-list button:not([disabled])").first().click();
  const dialog = page.getByRole("dialog");
  await expect(dialog, "no action dialog opened, so its closing proves nothing").toBeVisible();
  await page.goBack();
  await expect(page).toHaveURL(new RegExp(`\\?type=${type}$`));
  await expect(dialog, "the last type's action dialog stayed open over this one").toHaveCount(0);
});
