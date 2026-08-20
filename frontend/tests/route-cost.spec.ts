import { test } from "@playwright/test";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

/**
 * What a workspace route costs to open, cold, measured in a browser.
 *
 * `audit_route_payload` answers what the *bundle* costs, computed statically from
 * the build manifest. This answers what the *screen* costs once it is running:
 * the requests it issues and the bytes they carry.
 *
 * **Each route gets a fresh browser context**, and that is the whole correctness
 * of this file. The first version reused one page for all sixteen routes, so
 * every route after the first was measured against a warm cache: `security` read
 * 454 KB on one build and 26 KB on the next, not because the screen changed but
 * because more of what it needs had already been fetched by whatever ran before
 * it. The number was a function of visit order. It was reproducible -- 16 of 16
 * identical across two runs -- and reproducibly measuring the wrong thing, which
 * is the more dangerous kind.
 *
 * Three numbers, and they are not equally trustworthy. Which may be gated is a
 * question for the measurement, answered by running it twice; see
 * `audit_route_cost.py`.
 */

const ROUTES = [
  "command-center", "ontology", "pipeline", "object-explorer", "imports",
  "map", "models", "decision", "ops", "graph", "validation", "control-panel",
  "security", "analytics", "delivery", "automate"
];

const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = join(HERE, "..", "route-cost.json");

test("measure what each workspace route costs to open", async ({ browser }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-1280", "Measured once, at one width.");
  test.setTimeout(300_000);

  const measured: Record<string, { requests: number; bytes: number; settled_ms: number }> = {};

  for (const route of ROUTES) {
    // A fresh context per route: no shared cache, no cookies carried over, so
    // the number is what this screen costs and not what the previous one left
    // behind.
    const context = await browser.newContext();
    const page = await context.newPage();

    let requests = 0;
    let bytes = 0;
    page.on("request", () => { requests += 1; });
    page.on("response", async (response) => {
      try {
        const length = response.headers()["content-length"];
        bytes += length
          ? Number(length)
          : (await response.body().catch(() => Buffer.alloc(0))).length;
      } catch {
        /* a body already gone is not worth failing a measurement over */
      }
    });

    const started = Date.now();
    await page.goto(`/workspace/${route}`);
    await page.waitForLoadState("networkidle", { timeout: 30_000 }).catch(() => {});
    measured[route] = { requests, bytes, settled_ms: Date.now() - started };

    await context.close();
  }

  // Stamp the bundle this describes. Without it the gate judged a measurement
  // taken against an older build and failed a ceiling for a change that had
  // already happened -- stale evidence, which every baseline here guards against
  // and this artifact did not.
  let bundle: string | null = null;
  try {
    bundle = JSON.parse(
      readFileSync(join(HERE, "..", "dist", "build-provenance.json"), "utf-8")
    ).source_hash ?? null;
  } catch {
    bundle = null;
  }

  mkdirSync(dirname(OUT), { recursive: true });
  writeFileSync(
    OUT,
    JSON.stringify({ bundle_source_hash: bundle, routes: measured }, null, 2) + "\n",
    "utf-8"
  );
  console.log(`ROUTE-COST ${Object.keys(measured).length} routes, bundle ${bundle?.slice(0, 12)}`);
});
