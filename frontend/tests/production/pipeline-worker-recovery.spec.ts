import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test, type Page } from "@playwright/test";

const adminPassword = process.env.PILOT_ADMIN_PASSWORD;
const stage = process.env.PIPELINE_WORKER_REHEARSAL_STAGE;
const statePath = process.env.PIPELINE_WORKER_REHEARSAL_STATE_PATH;
const productionBaseUrl = process.env.PRODUCTION_BASE_URL || "http://localhost:18000";
const firstWorkerName = process.env.PIPELINE_WORKER_FIRST_NAME || "rehearsal-pipeline-worker-one";
const replacementWorkerName = process.env.PIPELINE_WORKER_REPLACEMENT_NAME || "rehearsal-pipeline-worker-two";

type WorkerRecoveryState = {
  suffix: string;
  token: string;
  jobId: string;
  outputAssetId: string;
  inputSnapshotId: string;
  rows: number;
  partitions: number;
  verification?: {
    attempt: number;
    claimCount: number;
    requeueCount: number;
    successCount: number;
    outputSnapshotId: string;
    outputRows: number;
    databaseHead: string;
    runtimeHead: string;
  };
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
  await page.goto(`/auth/login?next=${encodeURIComponent("/workspace/pipeline")}`);
  await page.locator("#username").fill("pilot-admin");
  await page.locator("#password").fill(adminPassword as string);
  await page.locator("#kc-login").click();
  await expect(page).toHaveURL(/localhost:18000\/workspace\/pipeline/);
}

async function api(page: Page, path: string, method = "GET", body?: unknown) {
  return page.evaluate(async ({ path, method, body }) => {
    const response = await fetch(path, {
      method,
      headers: body === undefined ? undefined : { "content-type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const text = await response.text();
    return { status: response.status, body: text ? JSON.parse(text) : {} };
  }, { path, method, body });
}

test("container-isolated pipeline worker recovery", async ({ page }) => {
  test.skip(!adminPassword || !stage || !statePath, "Pipeline worker rehearsal environment is required.");
  await waitForReadiness();
  await signIn(page);

  if (stage === "bootstrap") {
    const fixture = JSON.parse(execFileSync("python", [
      resolve("../oms/build_pipeline_worker_recovery_fixture.py"),
      "--endpoint", "http://127.0.0.1:19000",
      "--bucket", "ontology-rehearsal",
      "--rows", process.env.PIPELINE_WORKER_REHEARSAL_ROWS || "100000",
      "--partitions", process.env.PIPELINE_WORKER_REHEARSAL_PARTITIONS || "32",
    ], { cwd: resolve("."), encoding: "utf8", env: process.env }));
    const suffix = fixture.run_id as string;
    const serviceAccountId = `pipeline-worker-${suffix}`;
    expect((await api(page, "/admin/service-accounts", "POST", {
      id: serviceAccountId,
      display_name: "Production pipeline worker",
      organization_id: "pilot",
    })).status).toBe(201);
    const token = await api(page, "/admin/tokens", "POST", {
      principal_type: "service_account",
      principal_id: serviceAccountId,
      scopes: ["project:default:execute"],
      ttl_seconds: 3600,
    });
    expect(token.status).toBe(201);

    const inputAssetId = `container-recovery-input-${suffix}`;
    const outputAssetId = `container-recovery-output-${suffix}`;
    const graphId = `container-recovery-graph-${suffix}`;
    expect((await api(page, "/data-assets", "POST", {
      id: inputAssetId,
      project_id: "default",
      display_name: "Container recovery input",
      asset_schema: {},
      records: [],
    })).status).toBe(200);
    const snapshot = await api(page, `/api/v1/datasets/${inputAssetId}/snapshots/register`, "POST", {
      storage_uri: fixture.storage_uri,
      partition_spec: { fields: ["region"], hive_partitioning: true },
      lineage: { production_rehearsal: suffix },
    });
    expect(snapshot.status).toBe(201);
    expect(snapshot.body.row_count).toBe(fixture.rows);
    expect(snapshot.body.partition_spec._manifest.file_count).toBe(fixture.partitions);

    const graph = await api(page, "/pipeline-builder/graphs", "POST", {
      id: graphId,
      project_id: "default",
      display_name: "Container worker recovery graph",
      nodes: [
        { id: "input", type: "input_dataset", config: { asset_id: inputAssetId, snapshot_id: snapshot.body.id } },
        { id: "filter", type: "filter", config: { field: "risk_score", operator: "gte", value: 90 } },
        { id: "output", type: "dataset_output", config: { asset_id: outputAssetId } },
      ],
      edges: [{ source: "input", target: "filter" }, { source: "filter", target: "output" }],
    });
    expect(graph.status).toBe(201);
    const plan = await api(page, `/api/v1/pipelines/${graphId}/plans`, "POST", { executor: "duckdb" });
    expect(plan.status).toBe(201);
    const execution = await api(page, `/api/v1/pipeline-plans/${plan.body.id}/execute`, "POST", {
      mode: "deliver",
      output_asset_id: outputAssetId,
      idempotency_key: `container-worker-recovery-${suffix}`,
    });
    expect(execution.status).toBe(202);
    writeFileSync(statePath, JSON.stringify({
      suffix,
      token: token.body.token,
      jobId: execution.body.execution.id,
      outputAssetId,
      inputSnapshotId: snapshot.body.id,
      rows: fixture.rows,
      partitions: fixture.partitions,
    } satisfies WorkerRecoveryState), { encoding: "utf8", mode: 0o600 });
    return;
  }

  expect(stage).toBe("verify");
  const state = JSON.parse(readFileSync(statePath, "utf8")) as WorkerRecoveryState;
  await expect.poll(async () => (await api(page, `/jobs/${state.jobId}`)).body.status, {
    timeout: 180_000,
    intervals: [500, 1000, 2000],
  }).toBe("SUCCEEDED");
  const job = (await api(page, `/jobs/${state.jobId}`)).body;
  expect(job.attempt).toBe(2);
  expect(job.events.filter((event: { event_type: string }) => event.event_type === "job.claimed")).toHaveLength(2);
  expect(job.events.filter((event: { event_type: string }) => event.event_type === "job.requeued")).toHaveLength(1);
  expect(job.events.filter((event: { event_type: string }) => event.event_type === "job.succeeded")).toHaveLength(1);
  expect(job.events.find((event: { event_type: string; payload?: { reason?: string } }) =>
    event.event_type === "job.requeued")?.payload?.reason).toBe("lease_expired");

  const snapshots = (await api(page, `/api/v1/datasets/${state.outputAssetId}/snapshots`)).body.snapshots;
  expect(snapshots).toHaveLength(1);
  expect(snapshots[0].row_count).toBe(state.rows / 10);
  expect(snapshots[0].lineage.execution_job_id).toBe(state.jobId);
  expect(snapshots[0].lineage.execution_fence_job_id).toBe(state.jobId);
  expect(job.result.output_snapshot.id).toBe(snapshots[0].id);
  const workers = (await api(page, "/runtime/workers?project_id=default")).body;
  expect(workers.some((worker: { worker_name?: string }) =>
    worker.worker_name === firstWorkerName)).toBe(true);
  expect(workers.some((worker: { worker_name?: string }) =>
    worker.worker_name === replacementWorkerName)).toBe(true);
  const readiness = (await api(page, "/health/ready")).body;
  expect(readiness.migration.status).toBe("PASS");
  writeFileSync(statePath, JSON.stringify({
    ...state,
    verification: {
      attempt: job.attempt,
      claimCount: job.events.filter((event: { event_type: string }) => event.event_type === "job.claimed").length,
      requeueCount: job.events.filter((event: { event_type: string }) => event.event_type === "job.requeued").length,
      successCount: job.events.filter((event: { event_type: string }) => event.event_type === "job.succeeded").length,
      outputSnapshotId: snapshots[0].id,
      outputRows: snapshots[0].row_count,
      databaseHead: readiness.migration.database_head,
      runtimeHead: readiness.migration.runtime_head,
    },
  } satisfies WorkerRecoveryState), { encoding: "utf8", mode: 0o600 });
});
