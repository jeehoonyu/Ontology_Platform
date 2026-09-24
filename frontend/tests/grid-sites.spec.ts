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

// The operations feed's severity ranks, restated so the test fails if the product's
// change. A severity in no rank is -1.
const SEVERITY_TIERS: Record<string, number> = { info: 0, low: 1, medium: 2, warn: 2, warning: 2, high: 3, error: 3, critical: 4 };

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
    await expect.poll(() => panel.getByRole("note").evaluate((element) => element.scrollWidth <= element.clientWidth),
                      { message: "the note is cut off, hiding how many jobs there are" }).toBe(true);

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

  test("the compatibility grid puts every BREAKING change first, and a new comparison starts unsorted", async ({ page }) => {
    const suffix = `${Date.now()}`;
    const objectTypeId = `grid_registry_${suffix}`;
    const displayName = `Grid Registry ${suffix}`;
    // A channel of its own, so the comparison is against this test's baseline only.
    const channel = `grid-${suffix}`;
    await settled(await page.request.post("/object-types", { data: {
      id: objectTypeId, display_name: displayName, description: "Grid registry contract",
      properties: { assetId: { type: "string" }, name: { type: "string" }, note: { type: "string" } }
    } }));
    await settled(await page.request.put(`/ontology/object-types/${objectTypeId}/profile`, { data: {
      api_name: `GridRegistry${suffix}`, primary_key: "assetId", title_key: "name",
      properties: { assetId: { base_type: "string", required: true }, name: { base_type: "string", required: true }, note: { base_type: "string", required: false } }
    } }));
    const publishRevision = async (title: string, changes: object[], source: { base_revision_id: string } | { capture_current: true }) => {
      const change = await settled(await page.request.post("/ontology/change-sets", { data: {
        project_id: "default", title, ...source, changes
      } })) as { id: string };
      await settled(await page.request.post(`/ontology/change-sets/${change.id}/validate`));
      await settled(await page.request.post(`/ontology/change-sets/${change.id}/decision`, { data: { approve: true } }));
      // Archiving a property is a breaking change, which publishes only when acknowledged.
      const published = await settled(await page.request.post(`/ontology/change-sets/${change.id}/publish`, { data: { environment: "production", allow_breaking: true } })) as { revision: { id: string } };
      return published.revision.id;
    };
    // The baseline has to carry the object type. A revision is its base plus its changes,
    // and the base is production's current revision when there is one, which predates
    // the type. Capturing the live ontology carries it whether or not production has a
    // revision yet, so this does not depend on another test having published one.
    const baseline = await publishRevision(`Grid registry baseline ${suffix}`, [], { capture_current: true });
    await settled(await page.request.post("/ontology/registry/publish", { data: {
      project_id: "default", revision_id: baseline, version: `1.0.${suffix}`, channel, allow_breaking: true
    } }));
    // Archiving a property breaks consumers; adding an optional one does not.
    const next = await publishRevision(`Grid registry change ${suffix}`, [
      { operation: "archive_property", object_type_id: objectTypeId, property_name: "note" },
      { operation: "add_property", object_type_id: objectTypeId, property_name: "extra", spec: { base_type: "string", required: false } }
    ], { base_revision_id: baseline });

    await page.goto("/workspace/ontology");
    await page.locator(".manager-resource-nav .resource-row").filter({ hasText: displayName }).click();
    await page.getByRole("button", { name: /^schema registry$/i }).click();
    const registry = page.getByRole("region", { name: "Ontology schema registry" });
    await registry.getByLabel("Channel").fill(channel);
    const baselineEntry = registry.getByRole("button", { name: new RegExp(`1\\.0\\.${suffix} ${channel}`) });
    await expect(baselineEntry).toBeVisible();
    await registry.getByLabel("Published revision").selectOption(next);
    await registry.getByRole("button", { name: "Check compatibility" }).click();
    await expect(registry.locator('.registry-status[role="status"]')).toContainText("Compatibility result: BREAKING");

    const panel = panelTitled(page, "Semantic Compatibility");
    const classification = header(panel, "classification");
    await classification.getByRole("button").click();
    await expect.poll(async () => (await valuesOf(panel, "classification"))[0],
                      { message: "sorting by classification did not put a BREAKING change first" }).toBe("BREAKING");
    expect(await valuesOf(panel, "classification"), "the comparison is not mixed, so this proves nothing").toContain("NON_BREAKING");
    await classification.getByRole("button").click();
    await expect.poll(async () => (await valuesOf(panel, "classification"))[0]).toBe("NON_BREAKING");

    await baselineEntry.click();
    await expect(header(panel, "classification"), "the last comparison's sort carried into a different comparison")
      .toHaveAttribute("aria-sort", "none");
  });

  test("the operations feed ranks severity, keeps arrival order within a rank, and returns to it", async ({ page }) => {
    // Nine events from a source of this test's own. `warning` and `error` are words the
    // server's own rank does not have; `notice` is in no rank at all.
    const source = `grid-severity-${Date.now()}`;
    const severities = ["info", "warn", "warning", "error", "medium", "high", "critical", "low", "notice"];
    for (const severity of severities) {
      await settled(await page.request.post("/ops/events/ingest", { data: {
        source, event_type: "grid.severity", severity, title: `Severity ${severity}`
      } }));
    }
    await page.goto("/workspace/ops");
    const panel = panelTitled(page, "Live Operational Feed");
    await filterTo(panel, "source", source);
    await expect(panel.locator("tbody tr")).toHaveCount(severities.length);
    const arrival = await valuesOf(panel, "title");
    const tiers = async () => (await valuesOf(panel, "severity")).map((value) => SEVERITY_TIERS[value] ?? -1);
    const severity = header(panel, "severity");

    await severity.getByRole("button").click();
    await expect(severity, "the first press on severity does not put the worst first").toHaveAttribute("aria-sort", "descending");
    await expect.poll(tiers, { message: "severity sorts as text, not by rank" }).toEqual([4, 3, 3, 2, 2, 2, 1, 0, -1]);
    await severity.getByRole("button").click();
    await expect(severity).toHaveAttribute("aria-sort", "ascending");
    await expect.poll(tiers).toEqual([-1, 0, 1, 2, 2, 2, 3, 3, 4]);
    await severity.getByRole("button").click();
    await expect(severity, "a third press does not take the sort off").toHaveAttribute("aria-sort", "none");
    await expect.poll(() => valuesOf(panel, "title"), { message: "the feed did not return to the order it arrived in" }).toEqual(arrival);
  });

  test("Refresh keeps the feed's filter and sort, and what was typed into a form", async ({ page }) => {
    // Every refresh -- the button, and the one each action ends with -- replaced the page with
    // a loading screen, so every tab unmounted: the feed's filter and sort, and a half-typed
    // rule, went back to where they start.
    const source = `grid-refresh-${Date.now()}`;
    for (const severity of ["low", "critical", "medium"]) {
      await settled(await page.request.post("/ops/events/ingest", { data: {
        source, event_type: "grid.refresh", severity, title: `Refresh ${severity}`
      } }));
    }
    await page.goto("/workspace/ops");
    const refresh = page.getByRole("button", { name: "Refresh", exact: true });
    const refreshed = async () => {
      const summary = page.waitForResponse((response) => new URL(response.url()).pathname === "/ops/summary");
      await refresh.click();
      await summary;
      await expect(refresh, "the refresh did not finish").toBeEnabled();
    };
    const panel = panelTitled(page, "Live Operational Feed");
    await filterTo(panel, "source", source);
    await expect(panel.locator("tbody tr")).toHaveCount(3);
    const severity = header(panel, "severity");
    await severity.getByRole("button").click();
    await expect(severity).toHaveAttribute("aria-sort", "descending");

    await refreshed();
    await expect(severity, "Refresh took the feed's sort off").toHaveAttribute("aria-sort", "descending");
    await expect(panel.locator("tbody tr"), "Refresh took the feed's filter off").toHaveCount(3);
    await expect.poll(() => valuesOf(panel, "severity")).toEqual(["critical", "medium", "low"]);

    await page.getByRole("button", { name: "Alerts", exact: true }).click();
    const ruleName = page.getByLabel("Alert rule name");
    await ruleName.fill(`Typed before a refresh ${source}`);
    await refreshed();
    await expect(ruleName, "Refresh threw away a rule name that had not been sent").toHaveValue(`Typed before a refresh ${source}`);
  });

  test.describe("in one locale and zone, so a text sort of the times is wrong the same way every run", () => {
    test.use({ locale: "en-US", timezoneId: "UTC" });

    test("occurred sorts in time across the 12 o'clock hour and a year boundary, and says what a sort ranks", async ({ page }) => {
      // The ingest endpoint stamps its own created_at, so these times can only be
      // served. The suite's first stubbed responses: the events list and the summary
      // it is counted against. Everything else on the page is the real server.
      const at = (year: number, month: number, day: number, hour: number, minute: number) => Date.UTC(year, month - 1, day, hour, minute) / 1000;
      const times: Array<[string, number]> = [
        ["2025-12-31 23:00", at(2025, 12, 31, 23, 0)],
        ["2026-01-01 00:30", at(2026, 1, 1, 0, 30)],
        ["2026-01-01 01:00", at(2026, 1, 1, 1, 0)],
        ["2026-01-01 09:15", at(2026, 1, 1, 9, 15)],
        ["2026-01-01 10:00", at(2026, 1, 1, 10, 0)],
        ["2026-01-01 11:59", at(2026, 1, 1, 11, 59)],
        ["2026-01-01 12:00", at(2026, 1, 1, 12, 0)],
        ["2026-01-01 12:30", at(2026, 1, 1, 12, 30)],
        ["2026-01-01 13:00", at(2026, 1, 1, 13, 0)]
      ];
      const chronological = times.map(([title]) => title);
      // Newest first, the way the server lists them.
      const events = [...times].reverse().map(([title, created_at], index) => ({
        id: `stub_event_${index}`, source: "grid-time-stub", event_type: "grid.time", severity: "medium", status: "OPEN", title, created_at
      }));
      await page.route((url) => url.pathname === "/ops/events", (route) => route.fulfill({ json: events }));
      await page.route((url) => url.pathname === "/ops/summary", (route) => route.fulfill({ json: {
        events: 1204, open_alerts: 0, open_incidents: 0, runbooks: 0, pending_approvals: 0, unread_notifications: 0,
        severity_counts: {}, latest_events: [], latest_alerts: [], latest_incidents: []
      } }));
      await page.goto("/workspace/ops");
      const panel = panelTitled(page, "Live Operational Feed");
      await expect(panel.locator("tbody tr")).toHaveCount(times.length);
      const arrival = await valuesOf(panel, "title");
      const occurred = header(panel, "occurred");
      const scope = panel.locator(".grid-sort-scope");

      await occurred.getByRole("button").click();
      await expect(occurred).toHaveAttribute("aria-sort", "ascending");
      // Read through the titles, which name each time, so the check does not depend on
      // how this browser's ICU spaces "PM".
      await expect.poll(() => valuesOf(panel, "title"), { message: "occurred sorts as the text it shows, not as a time" }).toEqual(chronological);
      await occurred.getByRole("button").click();
      await expect(occurred).toHaveAttribute("aria-sort", "descending");
      await expect.poll(() => valuesOf(panel, "title")).toEqual([...chronological].reverse());
      await expect(scope, "a sort of the 9 loaded events does not say it ranks only those")
        .toHaveText("Sorted by occurred: this orders only the latest 9 of 1,204 events.");

      await occurred.getByRole("button").click();
      await expect(occurred).toHaveAttribute("aria-sort", "none");
      await expect.poll(() => valuesOf(panel, "title")).toEqual(arrival);
      await expect(scope, "the sentence outlived the sort it described").toHaveCount(0);
    });
  });
});
