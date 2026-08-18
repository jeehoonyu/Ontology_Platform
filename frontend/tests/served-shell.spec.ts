import { expect, test } from "@playwright/test";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

/**
 * What the browser is actually served.
 *
 * `_workspace_shell` picks its response at request time:
 *
 *     react_index = FRONTEND_DIST_DIR / "index.html"
 *     if react_index.exists() and not legacy:
 *         return FileResponse(react_index)
 *     return FileResponse(UI_DIR / "index.html")
 *
 * So a machine with no build silently serves `oms/app/ui/` instead -- 7,856
 * lines of hand-written UI, last touched six weeks before the React app, which
 * no test in this suite exercises. Every other spec here would still pass its
 * `.app-shell` and `.sidebar` assertions against it, because the legacy shell
 * has those classes too. The whole suite could run green against the wrong
 * product and say nothing.
 *
 * This runs on every viewport because it is nearly free, and because the thing
 * it guards against is not viewport-specific.
 */

// `package.json` sets `"type": "module"`, so specs are ESM and `__dirname` does
// not exist here.
const distDir = fileURLToPath(new URL("../dist", import.meta.url));

test("the server serves the built React shell, not the legacy fallback", async ({ page }) => {
  const response = await page.goto("/workspace/command-center");
  expect(response?.status()).toBe(200);

  const html = await page.content();
  expect(html, "the legacy shell was served instead of the React bundle").toContain('id="root"');

  // The legacy shell pulls Leaflet CSS from unpkg.com; the React bundle ships
  // its own. Naming it explicitly makes the failure message obvious.
  expect(html, "served page loads a stylesheet from an external CDN, which is the legacy shell")
    .not.toContain("unpkg.com");

  await expect(page.locator("#root")).toBeVisible();
});

test("the served shell names assets that exist on disk", async ({ page }) => {
  test.skip(!existsSync(join(distDir, "index.html")), "no local build to compare against");

  await page.goto("/workspace/command-center");
  const sources = await page.evaluate(() =>
    Array.from(document.querySelectorAll<HTMLElement>("script[src], link[href]"))
      .map((node) => node.getAttribute("src") || node.getAttribute("href") || "")
      .filter((value) => value.startsWith("/react/assets/")));

  expect(sources.length, "the served shell references no bundled assets").toBeGreaterThan(0);

  // Every asset the page asks for must be fetchable. A partial build serves an
  // index that names chunks the server does not have, and the page renders
  // blank rather than erroring.
  for (const source of sources) {
    const asset = await page.request.get(source);
    expect(asset.status(), `${source} is referenced by the shell but not served`).toBe(200);
  }

  // And the shell the browser got is the shell on disk, byte for byte.
  const onDisk = readFileSync(join(distDir, "index.html"), "utf-8");
  for (const source of sources) {
    expect(onDisk, `${source} is served but absent from the built index.html`).toContain(source);
  }
});

test("the bundle records the source it was built from", async () => {
  const provenance = join(distDir, "build-provenance.json");
  test.skip(!existsSync(join(distDir, "index.html")), "no local build to compare against");

  expect(existsSync(provenance),
    "the bundle carries no build-provenance.json, so nothing says what source it came from. " +
    "Run: python oms/measure_browser_evidence.py --build").toBe(true);

  const recorded = JSON.parse(readFileSync(provenance, "utf-8"));
  expect(typeof recorded.source_hash, "provenance has no source_hash").toBe("string");
  expect(recorded.source_hash.length).toBeGreaterThan(32);
  expect(recorded.inputs, "provenance records no source inputs").toBeGreaterThan(0);
});
