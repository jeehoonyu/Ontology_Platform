import { expect, test, type BrowserContext, type Page } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";

const password = process.env.OIDC_SCALE_USER_PASSWORD;
const userCount = Number(process.env.OIDC_SCALE_USER_COUNT || "200");
const concurrency = Number(process.env.OIDC_SCALE_LOGIN_CONCURRENCY || "10");
const usernamePrefix = process.env.OIDC_SCALE_USERNAME_PREFIX || "oidc-scale-viewer-";
const primary = process.env.PRODUCTION_BASE_URL || "http://localhost:18000";
const peer = process.env.PRODUCTION_PEER_URL || "http://localhost:18001";
const evidencePath = process.env.OIDC_SCALE_EVIDENCE_PATH;

type IdentityResult = {
  principalId: string;
  username: string;
  durationMs: number;
};

function percentile(values: number[], fraction: number) {
  const sorted = [...values].sort((left, right) => left - right);
  return sorted[Math.max(0, Math.ceil(sorted.length * fraction) - 1)];
}

async function authenticate(context: BrowserContext, page: Page, index: number): Promise<IdentityResult> {
  const username = `${usernamePrefix}${String(index).padStart(4, "0")}`;
  const started = performance.now();
  await context.clearCookies();
  await page.goto(`${primary}/auth/login?next=${encodeURIComponent("/auth/session")}`);
  await page.locator("#username").fill(username);
  await page.locator("#password").fill(password as string);
  const sessionDocument = page.waitForResponse((response) =>
    response.url() === `${primary}/auth/session`
    && response.request().resourceType() === "document"
    && response.status() === 200,
  { timeout: 30_000 });
  await page.locator("#kc-login").click();
  const navigationSession = await (await sessionDocument).json();
  expect(navigationSession.authenticated).toBe(true);

  const primarySessionResponse = await context.request.get(`${primary}/auth/session`);
  const peerSessionResponse = await context.request.get(`${peer}/auth/session`);
  expect(primarySessionResponse.status()).toBe(200);
  expect(peerSessionResponse.status()).toBe(200);
  const primarySession = await primarySessionResponse.json();
  const peerSession = await peerSessionResponse.json();
  expect(primarySession.authenticated).toBe(true);
  expect(primarySession.display_name).toContain("Scale");
  expect(primarySession.roles).toContain("viewer");
  expect(primarySession.permissions).toEqual(["view"]);
  expect(primarySession.organization_id).toBe("pilot");
  expect(primarySession.project_ids).toContain("default");
  expect(peerSession.principal_id).toBe(primarySession.principal_id);
  expect(peerSession.permissions).toEqual(["view"]);

  const primaryRead = await context.request.get(`${primary}/artifacts`);
  const peerRead = await context.request.get(`${peer}/artifacts`);
  expect(primaryRead.status()).toBe(200);
  expect(peerRead.status()).toBe(200);
  const forbidden = await context.request.post(`${primary}/artifacts`, {
    data: { artifact_type: "workshop", display_name: `Forbidden ${username}`, state: {} }
  });
  expect(forbidden.status()).toBe(403);
  return {
    principalId: primarySession.principal_id,
    username,
    durationMs: performance.now() - started
  };
}

test("200 distinct OIDC identities authenticate across both replicas", async ({ browser }) => {
  test.skip(!password, "OIDC scale user password is required.");
  test.setTimeout(10 * 60_000);
  expect(userCount).toBeGreaterThanOrEqual(200);
  expect(concurrency).toBeGreaterThan(0);

  const primaryHealthResponse = await fetch(`${primary}/health/ready`);
  const peerHealthResponse = await fetch(`${peer}/health/ready`);
  expect(primaryHealthResponse.status).toBe(200);
  expect(peerHealthResponse.status).toBe(200);
  const primaryHealth = await primaryHealthResponse.json();
  const peerHealth = await peerHealthResponse.json();
  expect(primaryHealth.status).toBe("READY");
  expect(peerHealth.status).toBe("READY");
  expect(primaryHealth.migration.status).toBe("PASS");
  expect(peerHealth.migration.status).toBe("PASS");
  expect(primaryHealth.migration.database_head).toBe(primaryHealth.migration.runtime_head);
  expect(peerHealth.migration.database_head).toBe(primaryHealth.migration.database_head);

  const started = performance.now();
  const results: IdentityResult[] = [];
  let next = 1;
  const workers = Array.from({ length: Math.min(concurrency, userCount) }, async () => {
    const context = await browser.newContext();
    try {
      const page = await context.newPage();
      while (next <= userCount) {
        const index = next++;
        results.push(await authenticate(context, page, index));
      }
    } finally {
      await context.close();
    }
  });
  await Promise.all(workers);

  const elapsedMs = performance.now() - started;
  const durations = results.map((result) => result.durationMs);
  const evidence = {
    status: "PASS",
    authorization_flow: "authorization_code_pkce",
    identities: results.length,
    unique_principals: new Set(results.map((result) => result.principalId)).size,
    replicas_verified: [primary, peer],
    role: "viewer",
    organization_id: "pilot",
    project_id: "default",
    mutation_denials: results.length,
    concurrency,
    elapsed_seconds: Number((elapsedMs / 1000).toFixed(3)),
    login_p50_ms: Number(percentile(durations, 0.5).toFixed(3)),
    login_p95_ms: Number(percentile(durations, 0.95).toFixed(3)),
    login_p95_limit_ms: 15_000,
    migration_head: primaryHealth.migration.database_head
  };
  expect(evidence.identities).toBe(userCount);
  expect(evidence.unique_principals).toBe(userCount);
  expect(evidence.login_p95_ms).toBeLessThan(evidence.login_p95_limit_ms);
  if (evidencePath) {
    const absolute = resolve(evidencePath);
    mkdirSync(dirname(absolute), { recursive: true });
    writeFileSync(absolute, `${JSON.stringify(evidence, null, 2)}\n`, "utf8");
  }
});
