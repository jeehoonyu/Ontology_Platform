import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Locator, type Page } from "@playwright/test";

/**
 * Overlays hold focus while open, close on Escape, and give focus back to what opened
 * them. `GOAL_FOUNDATIONS_2026-09-25.md` A7.
 *
 * Before A7 the command palette closed on Escape but left focus nowhere, and let Tab
 * walk out behind it; Object Explorer's action dialog did not close on Escape at all.
 * Both are the Dialog primitive now. Focus handling does not change with the viewport,
 * so these run once, on desktop; each was run against a build with the behaviour it
 * defends removed, and failed, before it was believed.
 */

async function focusStaysInside(page: Page, dialog: Locator, presses: number) {
  for (let press = 0; press < presses; press += 1) {
    await page.keyboard.press("Tab");
    expect(await dialog.evaluate((node) => node.contains(document.activeElement)), `focus left the dialog after ${press + 1} Tab(s)`).toBe(true);
  }
  await page.keyboard.press("Shift+Tab");
  expect(await dialog.evaluate((node) => node.contains(document.activeElement)), "focus left the dialog on Shift+Tab").toBe(true);
}

async function axeClean(page: Page) {
  const scan = await new AxeBuilder({ page }).include("[role='dialog']").withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
  return scan.violations.filter((violation) => violation.impact === "critical" || violation.impact === "serious").map((violation) => violation.id);
}

test.describe("GOAL_FOUNDATIONS A7, Dialog", () => {
  test.beforeEach(({}, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-1280", "Focus handling is checked once, on desktop.");
  });

  test("The command palette holds focus, closes on Escape, and gives focus back", async ({ page }) => {
    await page.goto("/workspace/decision");
    const trigger = page.getByRole("button", { name: "Search and commands" });
    await trigger.click();
    const dialog = page.getByRole("dialog", { name: "Search workspaces" });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByPlaceholder("Find a workspace or capability"), "the search field has focus").toBeFocused();
    await dialog.getByPlaceholder("Find a workspace or capability").fill("decision");
    await focusStaysInside(page, dialog, 4);
    expect.soft(await axeClean(page), "axe, with the palette open").toEqual([]);
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await expect(trigger, "focus went back to the button that opened it").toBeFocused();
  });

  test("Object Explorer's action dialog closes on Escape and gives focus back", async ({ page }) => {
    expect((await page.request.post("/scenarios/asset-reliability/bootstrap", { data: {} })).ok()).toBeTruthy();
    await page.goto("/workspace/object-explorer?type=asset");
    const table = page.locator(".explorer-table");
    await expect(table).toBeVisible();
    await table.locator("tbody input[type='checkbox']").first().check();
    const action = page.locator(".explorer-action-list button:not([disabled])").first();
    await expect(action).toBeVisible();
    await action.click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    expect(await dialog.evaluate((node) => node.contains(document.activeElement)), "focus moved into the dialog").toBe(true);
    await focusStaysInside(page, dialog, 5);
    expect.soft(await axeClean(page), "axe, with the action dialog open").toEqual([]);
    await page.keyboard.press("Escape");
    await expect(dialog, "Escape closes the action dialog").toBeHidden();
    await expect(action, "focus went back to the action that opened it").toBeFocused();
  });
});
