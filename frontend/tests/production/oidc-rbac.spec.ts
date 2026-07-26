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
    return { read: read.status, edit: edit.status, detail: await edit.json() };
  });
  expect(viewerAccess.read).toBe(200);
  expect(viewerAccess.edit).toBe(403);
  expect(viewerAccess.detail.detail).toContain("Permission 'edit' is required");
});
