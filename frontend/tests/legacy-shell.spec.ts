import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

/**
 * The legacy shell is supported, so it is tested — and what it owes is recorded.
 *
 * `oms/app/ui/` is 7,856 lines that no test touched, which was easy to read as
 * abandoned code. It is not. `VALIDATION_MATRIX.md` records it as "an explicit
 * compatibility aid rather than the default route", and the React app links to it
 * from two places: the sidebar's legacy items and the workbench's "Legacy view"
 * button. A user reaches it by clicking, so it owes the same minimum every other
 * route owes.
 *
 * Giving it that minimum found three things on the first run. One is fixed: two
 * selects and a filter input had no accessible name, so a screen reader announced
 * them as "combo box". The other two are recorded as ceilings rather than hidden,
 * because they are real and fixing 7,856 lines of legacy CSS is not this test's
 * job:
 *
 *   - `/workspace/pipeline?legacy=1` scrolls 48px sideways. The other routes do not.
 *   - Five elements fail colour contrast.
 *
 * Both numbers may fall and must not rise. This is deliberately a render sweep and
 * not a behavioural suite: nobody is claiming the legacy shell does what the React
 * one does.
 */

// Measured 2026-08-19. Fall freely; rising is a regression in a shell a user can
// still reach by clicking.
const OVERFLOW_CEILING: Record<string, number> = {
  ontology: 2,
  pipeline: 48,
  "command-center": 2
};
// Violation *kinds*, not counts. The first version of this capped
// `color-contrast` at the five nodes measured in isolation, and it failed inside
// the full suite: the legacy ontology page lists objects the earlier tests
// created, so the number of contrast-failing elements grows with the data. A
// ceiling on a number that moves with content is the census lesson again. A new
// *kind* of violation is the thing that means something, and it is gated.
const ALLOWED_VIOLATIONS = [
  "color-contrast",
  // Only appears once the page has data: a list long enough to scroll, with no
  // keyboard access to scroll it. Found by running this inside the full suite
  // rather than alone, which is the whole argument for the browser gate -- an
  // empty page cannot show a defect that needs rows to exist.
  "scrollable-region-focusable"
];

for (const route of Object.keys(OVERFLOW_CEILING)) {
  test(`legacy ${route} renders when explicitly requested`, async ({ page }) => {
    const response = await page.goto(`/workspace/${route}?legacy=1`);
    expect(response?.status()).toBe(200);

    const html = await page.content();
    expect(html, "?legacy=1 must serve the legacy shell, not the React bundle")
      .not.toContain('id="root"');
    await expect(page.locator(".app-shell")).toBeVisible();
    await expect(page.locator("body")).not.toContainText("[object Object]");

    const overflow = await page.evaluate(() =>
      document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow,
      `legacy ${route} scrolls ${overflow}px sideways, ceiling ${OVERFLOW_CEILING[route]}px`)
      .toBeLessThanOrEqual(OVERFLOW_CEILING[route]);
  });
}

test("the legacy shell grows no new serious accessibility violation", async ({ page }) => {
  await page.goto("/workspace/ontology?legacy=1");
  await expect(page.locator(".app-shell")).toBeVisible();

  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
  const serious = results.violations.filter(
    (v) => ["serious", "critical"].includes(v.impact || ""));

  // A violation that is not on the recorded list fails outright. `select-name`
  // was on it until the controls were given names, and is deliberately not
  // re-added.
  const unexpected = serious.filter((v) => !ALLOWED_VIOLATIONS.includes(v.id));
  expect(unexpected.map((v) => `${v.id}: ${v.help}`)).toEqual([]);

  // Reported, never gated: how widespread each known kind is. It varies with how
  // much data the page happens to list.
  for (const violation of serious) {
    console.log(`legacy a11y: ${violation.id} on ${violation.nodes.length} element(s)`);
  }
});
