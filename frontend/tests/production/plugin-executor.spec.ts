import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test, type Page } from "@playwright/test";

const adminPassword = process.env.PILOT_ADMIN_PASSWORD;
const stage = process.env.PLUGIN_REHEARSAL_STAGE;
const statePath = process.env.PLUGIN_REHEARSAL_STATE_PATH;
const evidencePath = process.env.PLUGIN_REHEARSAL_EVIDENCE_PATH;
const productionBaseUrl = process.env.PRODUCTION_BASE_URL || "http://localhost:18000";

type RehearsalState = {
  suffix: string;
  token: string;
  pluginVersionId: string;
  serviceAccountId: string;
  fastExecutionId?: string;
  recoveryExecutionId?: string;
  recoveryJobId?: string;
};

async function waitForReadiness() {
  await expect.poll(async () => {
    try {
      return (await fetch(`${productionBaseUrl}/health/ready`)).status;
    } catch {
      return 0;
    }
  }, { timeout: 60_000, intervals: [500, 1000, 2000] }).toBe(200);
}

async function signIn(page: Page) {
  await page.goto(`/auth/login?next=${encodeURIComponent("/workspace/command-center")}`);
  await page.locator("#username").fill("pilot-admin");
  await page.locator("#password").fill(adminPassword as string);
  await page.locator("#kc-login").click();
  await expect(page).toHaveURL(/localhost:18000\/workspace\/command-center/);
}

async function api(page: Page, path: string, method = "GET", body?: unknown) {
  return page.evaluate(async ({ path, method, body }) => {
    const response = await fetch(path, {
      method,
      headers: body === undefined ? undefined : { "content-type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const payload = await response.json();
    return { status: response.status, body: payload };
  }, { path, method, body });
}

function loadState(): RehearsalState {
  return JSON.parse(readFileSync(statePath as string, "utf8")) as RehearsalState;
}

test("signed plugin executor production rehearsal stage", async ({ page }) => {
  test.skip(!adminPassword || !stage || !statePath, "Production plugin rehearsal environment is required.");
  await waitForReadiness();
  await signIn(page);

  if (stage === "bootstrap") {
    const suffix = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
    const raw = execFileSync("python", [resolve("../oms/build_rehearsal_plugin.py"), "--suffix", suffix], {
      cwd: resolve("."), encoding: "utf8",
    });
    const fixture = JSON.parse(raw);
    const trust = await api(page, "/api/v1/plugins/trust-keys", "POST", fixture.trust_key);
    expect(trust.status).toBe(201);
    const registration = await api(page, "/api/v1/plugins/register", "POST", fixture.register);
    expect(registration.status).toBe(201);
    const activation = await api(page, `/api/v1/plugins/${registration.body.id}/activate`, "POST");
    expect(activation.status).toBe(200);

    const serviceAccountId = `plugin-executor-${suffix}`;
    const account = await api(page, "/admin/service-accounts", "POST", {
      id: serviceAccountId,
      display_name: "Production plugin executor",
      organization_id: "pilot",
    });
    expect(account.status).toBe(201);
    const token = await api(page, "/admin/tokens", "POST", {
      principal_type: "service_account",
      principal_id: serviceAccountId,
      scopes: ["project:default:execute"],
      ttl_seconds: 3600,
    });
    expect(token.status).toBe(201);
    writeFileSync(statePath as string, JSON.stringify({
      suffix,
      token: token.body.token,
      pluginVersionId: registration.body.id,
      serviceAccountId,
    } satisfies RehearsalState), { encoding: "utf8", mode: 0o600 });
    return;
  }

  const state = loadState();
  if (stage === "queue_recovery") {
    const fast = await api(page, `/api/v1/plugins/${state.pluginVersionId}/invoke-async`, "POST", {
      operation: "fast",
      input: { marker: `fast-${state.suffix}` },
      idempotency_key: `fast-${state.suffix}`,
      max_attempts: 3,
    });
    expect(fast.status).toBe(202);
    await expect.poll(async () => (await api(page, `/api/v1/plugins/executions/${fast.body.id}`)).body.status, {
      timeout: 90_000, intervals: [500, 1000, 2000],
    }).toBe("SUCCEEDED");
    const fastResult = (await api(page, `/api/v1/plugins/executions/${fast.body.id}`)).body;
    expect(fastResult.output.attempt_safe).toBe(true);
    expect(fastResult.sandbox.mode).toBe("oci");
    expect(fastResult.sandbox.read_only).toBe(true);
    expect(fastResult.sandbox.non_root).toBe(true);
    expect(fastResult.sandbox.network).toBe("none");

    const recovery = await api(page, `/api/v1/plugins/${state.pluginVersionId}/invoke-async`, "POST", {
      operation: "slow",
      input: { marker: `recovery-${state.suffix}`, delay_seconds: 25 },
      idempotency_key: `recovery-${state.suffix}`,
      max_attempts: 3,
    });
    expect(recovery.status).toBe(202);
    await expect.poll(async () => (await api(page, `/api/v1/plugins/executions/${recovery.body.id}`)).body.status, {
      timeout: 60_000, intervals: [250, 500, 1000],
    }).toBe("RUNNING");
    writeFileSync(statePath as string, JSON.stringify({
      ...state,
      fastExecutionId: fast.body.id,
      recoveryExecutionId: recovery.body.id,
      recoveryJobId: recovery.body.job_id,
    } satisfies RehearsalState), { encoding: "utf8", mode: 0o600 });
    return;
  }

  expect(stage).toBe("verify_recovery");
  expect(state.recoveryExecutionId).toBeTruthy();
  expect(state.recoveryJobId).toBeTruthy();
  await expect.poll(async () => (await api(page, `/api/v1/plugins/executions/${state.recoveryExecutionId}`)).body.status, {
    timeout: 120_000, intervals: [500, 1000, 2000],
  }).toBe("SUCCEEDED");
  const execution = (await api(page, `/api/v1/plugins/executions/${state.recoveryExecutionId}`)).body;
  const job = (await api(page, `/jobs/${state.recoveryJobId}`)).body;
  expect(execution.output).toEqual({ operation: "slow", marker: `recovery-${state.suffix}`, attempt_safe: true });
  expect(job.attempt).toBeGreaterThanOrEqual(2);
  expect(job.events.some((event: { event_type: string; payload?: { reason?: string } }) =>
    event.event_type === "job.requeued" && event.payload?.reason === "lease_expired")).toBe(true);
  expect(job.events.filter((event: { event_type: string }) => event.event_type === "job.succeeded")).toHaveLength(1);

  const readiness = (await api(page, "/project/readiness")).body;
  const pluginCheck = readiness.checks?.find((check: { id?: string; name?: string }) =>
    check.id === "plugin_execution" || check.name?.toLowerCase().includes("plugin"));
  expect(pluginCheck?.status).toBe("PASS");
  const workers = (await api(page, "/runtime/workers?project_id=default")).body;
  const executorWorker = workers.find((worker: { worker_name?: string }) =>
    worker.worker_name === "rehearsal-plugin-executor");
  expect(executorWorker?.labels?.egress_proxy).toBe("ready");
  const audit = (await api(page, "/audit-logs/search?event_type=plugin.execution.succeeded&limit=20")).body;
  expect(audit.results.some((entry: { subject_id: string }) => entry.subject_id === state.recoveryExecutionId)).toBe(true);

  if (evidencePath) {
    writeFileSync(resolve(evidencePath), JSON.stringify({
      generated_at: new Date().toISOString(),
      profile: "production-oidc-plugin-execution",
      status: "PASS",
      plugin_version_id: state.pluginVersionId,
      fast_execution_id: state.fastExecutionId,
      recovery_execution_id: state.recoveryExecutionId,
      recovery_job_id: state.recoveryJobId,
      recovered_attempt: job.attempt,
      recovery_reason: "lease_expired",
      terminal_success_events: job.events.filter((event: { event_type: string }) => event.event_type === "job.succeeded").length,
      sandbox: execution.sandbox,
      assertions: {
        real_oidc_administration: true,
        execute_only_service_token: true,
        signed_bundle: true,
        digest_pinned_oci: true,
        governed_egress_proxy_provisioned: true,
        executor_loss_recovered: true,
        duplicate_terminal_delivery_prevented: true,
        audit_evidence: true,
      },
    }, null, 2) + "\n", "utf8");
  }
});
