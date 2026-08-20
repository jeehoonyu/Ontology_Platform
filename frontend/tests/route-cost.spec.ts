import { test } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

/**
 * What a workspace route costs to open, measured in a browser.
 *
 * `audit_route_payload` answers what the *bundle* costs — bytes of JavaScript and
 * CSS, computed statically from the build manifest. That is half the question. A
 * user opening a screen also waits on the requests it issues once it is running,
 * and nothing counted those.
 *
 * Three numbers per route, and they are not equally trustworthy:
 *
 *   requests   how many network calls the route makes before it settles
 *   bytes      what those calls transferred
 *   settled_ms wall-clock to the network going quiet
 *
 * The last one is wall-clock on a loaded laptop and is recorded so it can be
 * looked at, not so it can be gated. Which of these is stable enough to gate is
 * a question for the measurement rather than for taste, so this writes all three
 * and `audit_route_cost.py` decides after comparing two runs.
 *
 * Desktop only. Measuring the same route at four widths would multiply the cost
 * of the run without changing what is being asked.
 */

const ROUTES = [
  "command-center", "ontology", "pipeline", "object-explorer", "imports",
  "map", "models", "decision", "ops", "graph", "validation", "control-panel",
  "security", "analytics", "delivery", "automate"
];

const OUT = join(dirname(fileURLToPath(import.meta.url)), "..", "route-cost.json");

test("measure what each workspace route costs to open", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-1280", "Measured once, at one width.");
  test.setTimeout(180_000);

  const measured: Record<string, { requests: number; bytes: number; settled_ms: number }> = {};

  for (const route of ROUTES) {
    let requests = 0;
    let bytes = 0;
    const count = () => { requests += 1; };
    const weigh = async (response: import("@playwright/test").Response) => {
      try {
        const length = response.headers()["content-length"];
        bytes += length ? Number(length) : (await response.body().catch(() => Buffer.alloc(0))).length;
      } catch {
        /* a response whose body is gone by the time it is read is not worth failing over */
      }
    };
    page.on("request", count);
    page.on("response", weigh);

    const started = Date.now();
    await page.goto(`/workspace/${route}`);
    // "Settled" is the network going quiet, which is the closest observable
    // proxy for the screen having finished asking for what it needs.
    await page.waitForLoadState("networkidle", { timeout: 30_000 }).catch(() => {});
    const settled = Date.now() - started;

    page.off("request", count);
    page.off("response", weigh);
    measured[route] = { requests, bytes, settled_ms: settled };
  }

  mkdirSync(dirname(OUT), { recursive: true });
  writeFileSync(OUT, JSON.stringify(measured, null, 2) + "\n", "utf-8");
  console.log(`ROUTE-COST wrote ${Object.keys(measured).length} routes to ${OUT}`);
});
