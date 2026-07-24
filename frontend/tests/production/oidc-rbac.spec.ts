import { expect, test, type Page } from "@playwright/test";

const adminPassword = process.env.PILOT_ADMIN_PASSWORD;
const viewerPassword = process.env.PILOT_VIEWER_PASSWORD;
const productionBaseUrl = process.env.PRODUCTION_BASE_URL || "http://localhost:18000";

async function waitForReadiness() {
  await expect.poll(async () => {
    try {
      return (await fetch(`${productionBaseUrl}/health/ready`)).status;
    } catch {
      return 0;
    }
  }, { timeout: 60_000, intervals: [500, 1000, 2000] }).toBe(200);
}

async function signIn(page: Page, username: string, password: string) {
  await page.goto(`/auth/login?next=${encodeURIComponent("/workspace/command-center")}`);
  await page.locator("#username").fill(username);
  await page.locator("#password").fill(password);
  await page.locator("#kc-login").click();
  await expect(page).toHaveURL(/localhost:18000\/workspace\/command-center/);
  await expect(page.locator(".app-shell")).toBeVisible();
}

test("real OIDC login and backend RBAC enforcement", async ({ page }) => {
  test.skip(!adminPassword || !viewerPassword, "Rehearsal account passwords are required.");
  await waitForReadiness();

  await signIn(page, "pilot-admin", adminPassword as string);
  const adminSession = await page.evaluate(async () => (await fetch("/auth/session")).json());
  expect(adminSession.authenticated).toBe(true);
  expect(adminSession.roles).toContain("administrator");
  expect(adminSession.organization_id).toBe("pilot");
  expect(adminSession.project_ids).toContain("default");

  const adminMutation = await page.evaluate(async () => {
    const response = await fetch("/artifacts", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        artifact_type: "workshop",
        display_name: "OIDC rehearsal workshop",
        state: { widgets: [{ id: "risk", type: "metric" }] },
        layout: {}
      })
    });
    return { status: response.status, body: await response.json() };
  });
  expect(adminMutation.status).toBe(201);

  const workflow = await page.evaluate(async () => {
    const json = async (path: string, method = "GET", body?: unknown) => {
      const response = await fetch(path, {
        method,
        headers: body ? { "content-type": "application/json" } : undefined,
        body: body ? JSON.stringify(body) : undefined
      });
      return { status: response.status, body: await response.json() };
    };
    await json("/project/demo/reset", "POST", { actor: "production-rehearsal" });
    const bootstrap = await json("/scenarios/asset-reliability/bootstrap", "POST", { actor: "production-rehearsal", run_pipelines: true, run_checks: true });
    const triage = await json("/scenarios/asset-reliability/run-triage", "POST", { actor: "production-rehearsal" });
    const approval = triage.body.approval as { id: string; action_type_id: string; parameters: Record<string, unknown> };
    const decision = await json(`/approvals/${approval.id}/decision`, "POST", { actor: "pilot-admin", decision: "APPROVED", reason: "production rehearsal" });
    const action = await json("/actions/execute", "POST", {
      action_type_id: approval.action_type_id,
      parameters: approval.parameters,
      idempotency_key: `production-rehearsal-${approval.id}`,
      actor: "pilot-admin",
      approval_request_id: approval.id
    });
    const report = await json("/scenarios/asset-reliability/report");
    return { bootstrap, triage, decision, action, report };
  });
  expect(workflow.bootstrap.status).toBe(200);
  expect(workflow.triage.body.status).toBe("APPROVAL_REQUIRED");
  expect(workflow.decision.body.status).toBe("APPROVED");
  expect(workflow.action.body.status).toBe("SUCCESS");
  expect(workflow.report.status).toBe(200);

  await page.goto("/workspace/graph");
  await expect(page.locator(".platform-graph-canvas .react-flow")).toBeVisible();
  await page.goto("/workspace/ontology");
  await expect(page.locator(".ontology-relationship-canvas .react-flow")).toBeVisible();

  await page.evaluate(async () => fetch("/auth/logout", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ all_sessions: false })
  }));
  await page.context().clearCookies();

  await signIn(page, "pilot-viewer", viewerPassword as string);
  const viewerSession = await page.evaluate(async () => (await fetch("/auth/session")).json());
  expect(viewerSession.roles).toContain("viewer");
  expect(viewerSession.permissions).toEqual(["view"]);
  expect(viewerSession.project_ids).toContain("default");

  const viewerAccess = await page.evaluate(async () => {
    const read = await fetch("/artifacts");
    const edit = await fetch("/artifacts", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ artifact_type: "workshop", display_name: "Forbidden", state: { widgets: [] } })
    });
    return { read: read.status, edit: edit.status, detail: await edit.json() };
  });
  expect(viewerAccess.read).toBe(200);
  expect(viewerAccess.edit).toBe(403);
  expect(viewerAccess.detail.detail).toContain("Permission 'edit' is required");
});
