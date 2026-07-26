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

  const onboarding = await page.evaluate(async (suffix) => {
    const request = async (path: string, method = "GET", body?: unknown) => {
      const response = await fetch(path, {
        method,
        headers: body ? { "content-type": "application/json" } : undefined,
        body: body ? JSON.stringify(body) : undefined
      });
      const payload = await response.json();
      return { status: response.status, body: payload };
    };
    const jobId = `pilot-import-${suffix}`;
    const datasetId = `pilot-assets-${suffix}`;
    const draftId = `pilot-assets-draft-${suffix}`;
    const objectTypeId = `pilot_asset_${suffix}`;
    const created = await request("/imports/csv", "POST", {
      id: jobId,
      project_id: "default",
      filename: "organization-assets.csv",
      display_name: "Organization Assets",
      content: `asset_id,name,status,latitude,longitude\norg-asset-1-${suffix},Main Pump,DEGRADED,37.79,-122.40\norg-asset-2-${suffix},Backup Pump,RUNNING,37.78,-122.41\n`
    });
    const validated = await request(`/imports/jobs/${jobId}/validate`, "POST", { template: "asset" });
    const generated = await request(`/imports/jobs/${jobId}/generate-ontology-draft`, "POST", {
      draft_id: draftId,
      object_type_id: objectTypeId,
      promote_dataset_id: datasetId,
      include_actions: true,
      create_pipeline_graph: true
    });
    const draftValidation = await request(`/ontology-generator/drafts/${draftId}/validate`, "POST");
    const applied = await request(`/ontology-generator/drafts/${draftId}/apply`, "POST", {});
    const delivered = applied.status === 200
      ? await request(`/pipeline-builder/graphs/${applied.body.pipeline_graph_id}/deliver`, "POST", {})
      : { status: 0, body: {} };
    const objects = await request(`/objects/${objectTypeId}`);
    const detail = await request(`/imports/jobs/${jobId}`);
    const outsideProject = await request("/imports/csv", "POST", {
      project_id: "outside-project",
      content: "asset_id,name\nforbidden,Forbidden Asset\n"
    });
    return { created, validated, generated, draftValidation, applied, delivered, objects, detail, outsideProject };
  }, adminMutation.body.id.replace(/[^a-zA-Z0-9]/g, "").slice(-12));
  expect(onboarding.created.status).toBe(201);
  expect(onboarding.created.body.project_id).toBe("default");
  expect(onboarding.validated.body.validation.status).toBe("READY");
  expect(onboarding.generated.status).toBe(200);
  expect(onboarding.generated.body.draft.draft.__project_id).toBe("default");
  expect(["PASS", "WARN"]).toContain(onboarding.draftValidation.body.status);
  expect(onboarding.applied.status).toBe(200);
  expect(onboarding.delivered.status).toBe(200);
  expect(onboarding.objects.body).toHaveLength(2);
  expect(onboarding.detail.body.project_id).toBe("default");
  expect(onboarding.outsideProject.status).toBe(403);
  expect(onboarding.outsideProject.body.detail.project_id).toBe("outside-project");

  const tenantBoundary = await page.evaluate(async () => {
    const response = await fetch("/tenancy/organizations", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ id: "outside", display_name: "Outside Organization" })
    });
    return { status: response.status, body: await response.json() };
  });
  expect(tenantBoundary.status).toBe(403);
  expect(tenantBoundary.body.detail).toContain("another organization");

  const loadProbe = await page.evaluate(async (artifactId) => {
    const started = performance.now();
    const responses = await Promise.all(Array.from({ length: 50 }, () => fetch(`/artifacts/${artifactId}`)));
    const bodies = await Promise.all(responses.map((response) => response.json()));
    return {
      statuses: responses.map((response) => response.status),
      nodeCounts: bodies.map((body) => body.state?.widgets?.length ?? -1),
      elapsedMs: performance.now() - started
    };
  }, adminMutation.body.id);
  expect(loadProbe.statuses).toEqual(Array(50).fill(200));
  expect(loadProbe.nodeCounts).toEqual(Array(50).fill(1));
  expect(loadProbe.elapsedMs).toBeLessThan(15_000);

  const sharedArtifact = await page.evaluate(async () => {
    const response = await fetch("/artifacts", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        artifact_type: "pipeline",
        display_name: "Cross-replica collaboration",
        state: {
          nodes: [{ id: "source", type: "input", position: { x: 80, y: 120 }, data: { label: "Source", nodeType: "input_dataset" } }],
          edges: []
        },
        layout: {}
      })
    });
    return response.json();
  }) as { id: string; lock_version: number };
  const joinedPrimary = await page.evaluate(async (artifactId) => {
    const response = await fetch(`/artifacts/${artifactId}/collaboration/join`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ client_id: "production-primary-client" })
    });
    return response.json();
  }, sharedArtifact.id) as { event_cursor: number; participant_token: string };

  const peer = await page.context().newPage();
  await peer.goto("http://localhost:18001/workspace/pipeline");
  const peerSession = await peer.evaluate(async () => (await fetch("/auth/session")).json());
  expect(peerSession.authenticated).toBe(true);
  const joinedPeer = await peer.evaluate(async (artifactId) => {
    const response = await fetch(`/artifacts/${artifactId}/collaboration/join`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ client_id: "production-peer-client" })
    });
    return response.json();
  }, sharedArtifact.id) as { participant_token: string };

  await page.evaluate(({ artifactId, cursor }) => {
    const holder = window as unknown as {
      crossReplicaEvent?: Promise<Record<string, unknown>>;
      crossReplicaStream?: EventSource;
    };
    holder.crossReplicaEvent = new Promise((resolve, reject) => {
      const stream = new EventSource(`/artifacts/${artifactId}/collaboration/stream?after=${cursor}`);
      holder.crossReplicaStream = stream;
      const timeout = window.setTimeout(() => {
        stream.close();
        reject(new Error("Timed out waiting for a cross-replica collaboration event"));
      }, 15_000);
      stream.addEventListener("artifact.commands", (raw) => {
        window.clearTimeout(timeout);
        stream.close();
        resolve(JSON.parse((raw as MessageEvent<string>).data));
      });
      stream.onerror = () => {
        window.clearTimeout(timeout);
        stream.close();
        reject(new Error("Cross-replica collaboration stream disconnected"));
      };
    });
  }, { artifactId: sharedArtifact.id, cursor: joinedPrimary.event_cursor });

  const peerEdit = await peer.evaluate(async ({ artifactId, participantToken, lockVersion }) => {
    const response = await fetch(`/artifacts/${artifactId}/collaboration/commands`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        participant_token: participantToken,
        expected_lock_version: lockVersion,
        idempotency_key: "production-cross-replica-edit",
        commands: [{
          command_id: "production-add-filter",
          command: "add_node",
          payload: { node: { id: "filter", type: "transform", position: { x: 320, y: 120 }, data: { label: "Filter", nodeType: "filter" } } }
        }],
        message: "Edit through peer API"
      })
    });
    return { status: response.status, body: await response.json() };
  }, { artifactId: sharedArtifact.id, participantToken: joinedPeer.participant_token, lockVersion: sharedArtifact.lock_version });
  expect(peerEdit.status).toBe(200);
  const crossReplicaEvent = await page.evaluate(async () => {
    const holder = window as unknown as { crossReplicaEvent?: Promise<Record<string, unknown>> };
    return holder.crossReplicaEvent;
  });
  expect(crossReplicaEvent?.artifact_id).toBe(sharedArtifact.id);
  expect(crossReplicaEvent?.lock_version).toBe(2);
  const synchronized = await page.evaluate(async (artifactId) => (await fetch(`/artifacts/${artifactId}`)).json(), sharedArtifact.id);
  expect(synchronized.lock_version).toBe(2);
  expect(synchronized.state.nodes).toHaveLength(2);
  const crossReplicaReplay = await page.evaluate(async ({ artifactId, participantToken, lockVersion }) => {
    const response = await fetch(`/artifacts/${artifactId}/collaboration/commands`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        participant_token: participantToken,
        expected_lock_version: lockVersion,
        idempotency_key: "production-cross-replica-edit",
        commands: [{
          command_id: "production-add-filter",
          command: "add_node",
          payload: { node: { id: "filter", type: "transform", position: { x: 320, y: 120 }, data: { label: "Filter", nodeType: "filter" } } }
        }],
        message: "Retry peer edit through primary API"
      })
    });
    return { status: response.status, body: await response.json() };
  }, { artifactId: sharedArtifact.id, participantToken: joinedPrimary.participant_token, lockVersion: sharedArtifact.lock_version });
  expect(crossReplicaReplay.status).toBe(200);
  expect(crossReplicaReplay.body.idempotent_replay).toBe(true);
  expect(crossReplicaReplay.body.lock_version).toBe(2);

  const durableJobRequest = {
    project_id: "default",
    job_type: "report.generate",
    subject_type: "artifact",
    subject_id: sharedArtifact.id,
    payload: { format: "markdown", artifact_id: sharedArtifact.id },
    idempotency_key: `cross-replica-job-${sharedArtifact.id}`
  };
  const [primaryJob, peerJob] = await Promise.all([
    page.evaluate(async (body) => {
      const response = await fetch("/jobs", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body)
      });
      return { status: response.status, body: await response.json() };
    }, durableJobRequest),
    peer.evaluate(async (body) => {
      const response = await fetch("/jobs", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body)
      });
      return { status: response.status, body: await response.json() };
    }, durableJobRequest)
  ]);
  expect(primaryJob.status).toBe(201);
  expect(peerJob.status).toBe(201);
  expect(primaryJob.body.id).toBe(peerJob.body.id);
  expect([primaryJob.body.idempotent_replay, peerJob.body.idempotent_replay].sort()).toEqual([false, true]);
  expect(primaryJob.body.idempotency_receipt_id).toBe(peerJob.body.idempotency_receipt_id);

  const changedJobRequest = await page.evaluate(async (body) => {
    const response = await fetch("/jobs", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ ...body, payload: { ...body.payload, format: "json" } })
    });
    return { status: response.status, body: await response.json() };
  }, durableJobRequest);
  expect(changedJobRequest.status).toBe(409);
  expect(changedJobRequest.body.detail.message).toContain("different job request");

  const chaosJob = await page.evaluate(async (artifactId) => {
    const response = await fetch("/jobs", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        project_id: "default",
        job_type: "chaos.recovery",
        subject_type: "artifact",
        subject_id: artifactId,
        payload: { rehearsal: "abandoned-worker-lease" },
        max_attempts: 2,
        timeout_seconds: 300,
        idempotency_key: `chaos-recovery-${artifactId}`
      })
    });
    return { status: response.status, body: await response.json() };
  }, sharedArtifact.id);
  expect(chaosJob.status).toBe(201);

  const abandonedClaim = await peer.evaluate(async (jobId) => {
    const response = await fetch("/jobs/claim", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        worker_id: "production-abandoned-worker",
        project_id: "default",
        supported_job_types: ["chaos.recovery"],
        job_id: jobId,
        lease_seconds: 10
      })
    });
    return { status: response.status, body: await response.json() };
  }, chaosJob.body.id);
  expect(abandonedClaim.status).toBe(200);
  expect(abandonedClaim.body.job.status).toBe("RUNNING");
  const abandonedToken = abandonedClaim.body.job.lease_token as string;

  await page.waitForTimeout(10_500);
  const [primaryRecoverySummary, peerRecoverySummary] = await Promise.all([
    page.evaluate(async () => (await fetch("/jobs/summary")).json()),
    peer.evaluate(async () => (await fetch("/jobs/summary")).json())
  ]);
  expect(primaryRecoverySummary.reaped_stale_jobs + peerRecoverySummary.reaped_stale_jobs).toBe(1);
  const requeuedJob = await page.evaluate(async (jobId) => (await fetch(`/jobs/${jobId}`)).json(), chaosJob.body.id);
  expect(requeuedJob.status).toBe("QUEUED");
  expect(requeuedJob.attempt).toBe(2);
  expect(requeuedJob.events.filter((event: { event_type: string }) => event.event_type === "job.requeued")).toHaveLength(1);

  const replacementClaim = await page.evaluate(async (jobId) => {
    const response = await fetch("/jobs/claim", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        worker_id: "production-replacement-worker",
        project_id: "default",
        supported_job_types: ["chaos.recovery"],
        job_id: jobId,
        lease_seconds: 30
      })
    });
    return { status: response.status, body: await response.json() };
  }, chaosJob.body.id);
  expect(replacementClaim.status).toBe(200);
  expect(replacementClaim.body.job.attempt).toBe(2);

  const staleCompletion = await peer.evaluate(async ({ jobId, leaseToken }) => {
    const response = await fetch(`/jobs/${jobId}/complete`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ lease_token: leaseToken, result: { invalid: true } })
    });
    return { status: response.status, body: await response.json() };
  }, { jobId: chaosJob.body.id, leaseToken: abandonedToken });
  expect(staleCompletion.status).toBe(409);

  const recoveredCompletion = await page.evaluate(async ({ jobId, leaseToken }) => {
    const response = await fetch(`/jobs/${jobId}/complete`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ lease_token: leaseToken, result: { recovered: true } })
    });
    return { status: response.status, body: await response.json() };
  }, { jobId: chaosJob.body.id, leaseToken: replacementClaim.body.job.lease_token as string });
  expect(recoveredCompletion.status).toBe(200);
  expect(recoveredCompletion.body.status).toBe("SUCCEEDED");
  expect(recoveredCompletion.body.result.recovered).toBe(true);

  const recoveryEvidence = await page.evaluate(async (jobId) => {
    const [job, observation, events] = await Promise.all([
      fetch(`/jobs/${jobId}`).then((response) => response.json()),
      fetch(`/runtime/observability/jobs/${jobId}`).then((response) => response.json()),
      fetch("/ops/events?source=runtime").then((response) => response.json())
    ]);
    return { job, observation, events };
  }, chaosJob.body.id);
  expect(recoveryEvidence.job.events.filter((event: { event_type: string }) => event.event_type === "job.claimed")).toHaveLength(2);
  expect(recoveryEvidence.job.events.filter((event: { event_type: string }) => event.event_type === "job.succeeded")).toHaveLength(1);
  expect(recoveryEvidence.observation.spans.some((span: { name: string }) => span.name === "recovery")).toBe(true);
  expect(recoveryEvidence.events.some((event: { event_type: string; subject_id: string }) => event.event_type === "job.requeued" && event.subject_id === chaosJob.body.id)).toBe(true);
  await peer.close();

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
    const importAttempt = await fetch("/imports/csv", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ project_id: "default", content: "asset_id,name\nforbidden,Forbidden\n" })
    });
    return { read: read.status, edit: edit.status, detail: await edit.json(), importStatus: importAttempt.status };
  });
  expect(viewerAccess.read).toBe(200);
  expect(viewerAccess.edit).toBe(403);
  expect(viewerAccess.importStatus).toBe(403);
  expect(viewerAccess.detail.detail).toContain("Permission 'edit' is required");
});
