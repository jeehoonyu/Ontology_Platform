import { expect, test, type APIResponse, type Locator, type Page } from "@playwright/test";

/**
 * The grid where the N7d census said a person needs to sort.
 *
 * `docs/GRID_SORT_CENSUS.md` named seven `DataTable` sites whose rows a person scans
 * and compares; the owner chose the full `DataGrid` at all of them. Each test here
 * proves the sort the census gave as that site's reason, on the site itself, with a
 * fixture of its own. Every setup call prints the response it got, so a refused
 * fixture says why rather than failing somewhere later.
 */
async function settled(response: APIResponse) {
  const body = await response.text();
  expect(response.ok(), body.slice(0, 500)).toBeTruthy();
  return JSON.parse(body || "null");
}

function panelTitled(page: Page, title: string) {
  return page.locator(".panel").filter({ has: page.getByRole("heading", { name: title, exact: true }) });
}

async function filterTo(panel: Locator, column: string, text: string) {
  await panel.locator("details.grid-filters summary").click();
  await panel.getByRole("textbox", { name: `Rows where ${column} contains`, exact: true }).fill(text);
}

async function valuesOf(panel: Locator, column: string) {
  const headers = await panel.locator("thead .grid-sort").evaluateAll((buttons) =>
    buttons.map((button) => (button.textContent || "").replace(/[▲▼]/g, "").trim()));
  return panel.locator("tbody tr").evaluateAll((rows, at) => rows.map((row) => row.children[at]?.textContent || ""), headers.indexOf(column));
}

function header(panel: Locator, column: string) {
  return panel.locator("thead th").filter({ has: panel.page().getByRole("button", { name: column, exact: true }) });
}

test.describe("the census sites sort the way the census said a person needs", () => {
  test.beforeEach(async ({}, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-1280", "Runs once; the fixtures are stateful.");
  });

  test("the users list sorts by status and gathers the inactive accounts", async ({ page }) => {
    const suffix = `${Date.now()}`;
    const ids: string[] = [];
    for (const letter of ["a", "b", "c"]) {
      const user = await settled(await page.request.post("/admin/users", { data: {
        username: `grid-user-${suffix}-${letter}`, display_name: `Grid user ${letter}`, organization_ids: [], marking_ids: []
      } })) as { id: string };
      ids.push(user.id);
    }
    await settled(await page.request.post(`/admin/users/${ids[1]}/status`, { data: { status: "inactive" } }));

    await page.goto("/workspace/control-panel");
    await page.getByRole("button", { name: "Users", exact: true }).click();
    const panel = panelTitled(page, "Users");
    await filterTo(panel, "username", suffix);
    await expect(panel.locator("tbody tr")).toHaveCount(3);

    await header(panel, "status").getByRole("button").click();
    await expect(header(panel, "status")).toHaveAttribute("aria-sort", "ascending");
    await expect.poll(() => valuesOf(panel, "status"), { message: "the users did not sort by status" })
      .toEqual(["active", "active", "inactive"]);
    await header(panel, "status").getByRole("button").click();
    await expect.poll(() => valuesOf(panel, "status"), { message: "a second press did not bring the inactive accounts first" })
      .toEqual(["inactive", "active", "active"]);
  });

  test("role grants sort by role, gathering who holds each", async ({ page }) => {
    const suffix = `${Date.now()}`;
    const principal = `grid-principal-${suffix}`;
    for (const role of ["viewer", "owner", "administrator", "editor"]) {
      await settled(await page.request.post("/admin/roles/grant", { data: {
        scope_type: "organization", scope_id: `grid-org-${suffix}`, principal_type: "user", principal_id: principal, role
      } }));
    }

    await page.goto("/workspace/control-panel");
    await page.getByRole("button", { name: "Roles", exact: true }).click();
    const panel = panelTitled(page, "Role Grants");
    await filterTo(panel, "principal_id", suffix);
    await expect(panel.locator("tbody tr")).toHaveCount(4);

    await header(panel, "role").getByRole("button").click();
    await expect.poll(() => valuesOf(panel, "role"), { message: "the grants did not sort by role" })
      .toEqual(["administrator", "editor", "owner", "viewer"]);
  });

  test("tokens sort by whether they are revoked, false before true", async ({ page }) => {
    const suffix = `${Date.now()}`;
    const account = `grid-sa-${suffix}`;
    await settled(await page.request.post("/admin/service-accounts", { data: { id: account, display_name: `Grid account ${suffix}`, organization_id: "local" } }));
    const issued: Array<{ id: string }> = [];
    for (let index = 0; index < 2; index += 1) {
      issued.push(await settled(await page.request.post("/admin/tokens", { data: {
        principal_type: "service_account", principal_id: account, scopes: ["project:default:execute"], ttl_seconds: 3600
      } })) as { id: string });
    }
    await settled(await page.request.post(`/admin/tokens/${issued[1].id}/revoke`, { data: {} }));

    await page.goto("/workspace/control-panel");
    await page.getByRole("button", { name: "Auth", exact: true }).click();
    const panel = panelTitled(page, "API Tokens");
    await filterTo(panel, "principal_id", suffix);
    await expect(panel.locator("tbody tr")).toHaveCount(2);

    await header(panel, "revoked").getByRole("button").click();
    await expect.poll(() => valuesOf(panel, "revoked"), { message: "the tokens did not sort by revoked, false first" })
      .toEqual(["false", "true"]);
    await header(panel, "revoked").getByRole("button").click();
    await expect.poll(() => valuesOf(panel, "revoked")).toEqual(["true", "false"]);
  });

  test("job telemetry says it holds the latest 50, and a cost sort says it ranks only those", async ({ page }) => {
    const project = `grid-jobs-${Date.now()}`;
    const queue = async (cost: number) => settled(await page.request.post("/jobs", { data: {
      project_id: project, job_type: "pipeline.preview", estimated_compute_seconds: 1, estimated_cost_usd: cost, estimated_records: 1
    } }));
    // The oldest job costs most, so a sort that claimed to rank every job would put it
    // first. It is queued a second before the rest: `created_at` is whole seconds, and
    // jobs queued in the same second fall back to database order, so without the gap
    // any one of them could be the job left out of the latest 50.
    await queue(99.5);
    await page.waitForTimeout(1100);
    // Small costs whose text order is wrong: as text, "0.1" sorts before "0.05" and
    // "0.0008", and "1e-7" after them all.
    const newest = [...Array.from({ length: 45 }, (unused, index) => 3 + index * 0.5), 0.1, 0.05, 1e-7, 0.009, 0.0008];
    for (const cost of newest) await queue(cost);

    const summary = await settled(await page.request.get(`/runtime/observability/summary?project_id=${project}`)) as { total_jobs: number };
    const loaded = await settled(await page.request.get(`/runtime/observability/jobs?project_id=${project}&limit=50`)) as Array<{ estimated_cost_usd: number }>;
    expect(summary.total_jobs, "the fixture did not reach past the 50 the table loads").toBe(51);
    expect(loaded.map((job) => job.estimated_cost_usd), "the oldest job was loaded, so the window is not the one this test is about")
      .not.toContain(99.5);

    await page.goto("/workspace/control-panel");
    await page.getByRole("button", { name: "Runtime", exact: true }).click();
    await page.getByLabel("Project", { exact: true }).fill(project);
    const panel = panelTitled(page, "Durable Job Telemetry");
    await expect(panel.getByRole("note"), "the telemetry does not say it holds only the latest jobs")
      .toHaveText("Loaded the latest 50 of 51 jobs");

    const costHeader = header(panel, "estimated_cost_usd");
    await costHeader.getByRole("button").click();
    await expect.poll(async () => (await valuesOf(panel, "estimated_cost_usd")).slice(0, 3),
                      { message: "costs sorted as the text they show, not by value" })
      .toEqual(["1e-7", "0.0008", "0.009"]);
    const scope = panel.locator(".grid-sort-scope");
    await expect(scope, "a sort of the loaded window does not say it ranks only the window")
      .toHaveText("Sorted by estimated_cost_usd: this orders only the latest 50 of 51 jobs.");
    await costHeader.getByRole("button").click();
    // The most expensive of the loaded 50, not the 99.5 the window left out.
    await expect.poll(async () => (await valuesOf(panel, "estimated_cost_usd"))[0],
                      { message: "descending did not start from the most expensive loaded job" }).toBe("25");
    await costHeader.getByRole("button").click();
    await expect(costHeader).toHaveAttribute("aria-sort", "none");
    await expect(scope, "the sentence outlived the sort").toHaveCount(0);
  });
});
