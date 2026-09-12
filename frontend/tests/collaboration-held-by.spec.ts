import { expect, test } from "@playwright/test";

/**
 * The person holding a node is visible before the conflict. M6 of
 * `GOAL_PANES_2026-09-11.md`.
 *
 * Collaboration on the artifact canvases rebases non-overlapping edits and
 * returns 409 on overlap, and until this nothing told a second editor that the
 * node they were about to move was already in someone else's hands. The first
 * page's selection now travels in its heartbeat the moment it changes, and the
 * second page marks the node.
 *
 * Both browser contexts sign in as the same local principal, so the badge's name
 * cannot tell them apart; what tells them apart is where it appears. The page
 * that selected the node must not see its own selection as someone else's.
 */
test("a second editor sees the first editor's selection on the node within seconds", async ({ browser }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-1280", "Runs once; two browser contexts on desktop.");
  const contextA = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const contextB = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const pageA = await contextA.newPage();
  const pageB = await contextB.newPage();
  try {
    const suffix = Date.now();
    const created = await pageA.request.post("/artifacts", { data: {
      artifact_type: "workshop",
      display_name: `Held-by workshop ${suffix}`,
      state: {
        nodes: [
          { id: "held", position: { x: 80, y: 80 }, data: { label: "Held metric", nodeType: "metric" } },
          { id: "free", position: { x: 320, y: 80 }, data: { label: "Free metric", nodeType: "metric" } }
        ],
        edges: [],
        widgets: []
      }
    } });
    expect(created.ok(), await created.text()).toBeTruthy();
    const artifact = await created.json() as { id: string };

    await Promise.all([pageA.goto("/workspace/workshop"), pageB.goto("/workspace/workshop")]);
    await pageA.getByLabel("Workshop artifact").selectOption(artifact.id);
    await pageB.getByLabel("Workshop artifact").selectOption(artifact.id);
    await expect(pageA.locator(".collaboration-presence")).toContainText("2 editing");
    await expect(pageB.locator(".collaboration-presence")).toContainText("2 editing");

    const heldOnB = pageB.locator('.react-flow__node[data-id="held"]');
    const freeOnB = pageB.locator('.react-flow__node[data-id="free"]');
    await expect(heldOnB).toBeVisible();
    await expect(heldOnB, "a node nobody has selected is marked as held").not.toHaveClass(/held-by-other/);

    await pageA.locator('.react-flow__node[data-id="held"]').click();

    // Eight seconds, not twenty: the selection goes out when it changes, and the
    // second page refetches presence every four. A build that waited for the
    // periodic heartbeat would show the badge after the conflict it is for.
    await expect(heldOnB, "the second editor was not told the node is selected by someone else")
      .toHaveClass(/held-by-other/, { timeout: 8_000 });
    await expect(heldOnB).toHaveAttribute("data-held-by", /.+/);
    await expect(freeOnB, "a node the first editor did not select is marked as held").not.toHaveClass(/held-by-other/);
    await expect(pageA.locator('.react-flow__node[data-id="held"]'),
                 "the editor holding the node is shown their own selection as someone else's")
      .not.toHaveClass(/held-by-other/);

    // And it lets go: the badge follows the selection away.
    await pageA.locator('.react-flow__node[data-id="free"]').click();
    await expect(heldOnB, "the badge stayed on a node the first editor let go of")
      .not.toHaveClass(/held-by-other/, { timeout: 8_000 });
    await expect(freeOnB).toHaveClass(/held-by-other/, { timeout: 8_000 });
  } finally {
    await contextA.close();
    await contextB.close();
  }
});
