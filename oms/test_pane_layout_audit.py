"""The count of panes a person can move, and a ratchet that runs upward.

Also this check's home: `audit_pane_layout` declares `every suite run`.

M1 of `GOAL_PANES_2026-09-11.md`. The ask was panes that move around. The answer
the code gives is that **none of them do**: every pane on every screen is a fixed
grid track decided at build time, and the only layout anyone can change and keep
is node positions on the platform graph.

Most ratchets here are ceilings — a number that may fall and must not rise. This
one is a floor. A pane that stopped being movable is a person's layout taken
away, and that is the regression worth refusing.

The goal document predicted "roughly fourteen" regions before the scan existed.
It is 21. The prediction is left in the goal and the number is recorded here,
because an estimate corrected by a measurement is the point of writing the
measurement first.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from audit_pane_layout import (  # noqa: E402
    BASELINE, PRIMITIVE, REFERENCE, compare, render, scan, totals,
)

checks = 0


def check(condition, message):
    global checks
    assert condition, message
    checks += 1


screens = scan()
regions, movable, resizable = totals(screens)

# --- the live tree -------------------------------------------------------------
check(regions >= 15, f"only {regions} pane region(s) found; the scan has stopped seeing them")
check(len(screens) >= 10, sorted(screens))
check("workspaces/PipelineBuilder.tsx" in screens, sorted(screens)[:6])
check("workspaces/VisualBuilder.tsx" in screens, sorted(screens)[:6])

# `Panel` renders a labelled section at runtime, and there are dozens of them.
# Counting those would bury the regions this is about under a number nobody
# could act on, so the primitive's own file is skipped and `<Panel>` usages are
# never matched -- only literal `<aside>` and `<section>` elements are.
check(PRIMITIVE not in screens, f"{PRIMITIVE} defines the primitive and is not a screen")

# A screen on `PaneHost` offers splitters, drawn by the host. The scan looked for
# the splitter in the screen's own file, missed it in the primitive it skips, and
# reported the pipeline builder as not resizable from M3 to M7.
check(screens["workspaces/PipelineBuilder.tsx"]["resizable"],
      "a screen on PaneHost reads as offering no splitter")
check(not any("<Panel" in name for entry in screens.values() for name in entry["fixed"]),
      "a `<Panel>` usage was counted as a pane region")

# A dialog is a different interaction with different rules; the command palette
# is `role="dialog"` with `aria-modal` and must not read as a pane.
palette = screens.get("App.tsx", {})
check("command-palette" not in palette.get("fixed", []),
      f"the modal command palette was counted as a pane: {palette}")
check("sidebar" in palette.get("fixed", []), f"the app sidebar is a pane region: {palette}")

# --- the floor ratchet ---------------------------------------------------------
import json  # noqa: E402

check(BASELINE.exists(), f"no baseline at {BASELINE}")
baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
check(baseline["movable"] <= movable,
      f"movable panes fell from {baseline['movable']} to {movable}")

# The gate must actually bite. A floor that never refuses anything is a number
# printed next to a claim, which is what this repository keeps learning.
losing = dict(baseline)
losing["movable"] = movable + 1
ok, failures, _ = compare(screens, losing)
check(not ok and any("ratchet runs the other way" in f for f in failures),
      f"a fallen movable count did not fail the gate: {failures}")

# And the half-migrated screen must fail too: some panes moving and some not,
# with nothing on screen saying which, is worse than none moving.
mixed_screens = {"workspaces/Demo.tsx": {"fixed": ["old-rail"], "movable": ["new-rail"],
                                         "resizable": False}}
mixed_baseline = {"movable": 1, "screens": {"workspaces/Demo.tsx": {"fixed": [],
                                                                    "movable": ["new-rail"]}}}
ok, failures, _ = compare(mixed_screens, mixed_baseline)
check(any("grew a fixed-track region" in f for f in failures),
      f"a screen mixing `Pane` with a new fixed track did not fail: {failures}")

# --- rendering is a pure function of the scan ---------------------------------
text = render(screens)
check(render(screens) == text, "rendering twice gives the same bytes")
check("| Screen | Movable | Fixed track | Resizable |" in text, text[:200])
check(f"**{movable} of {regions}**" in text, "the reference does not lead with the count")

# --- the gate ------------------------------------------------------------------
ok, failures, notes = compare(screens, baseline)
check(ok, failures)
check(REFERENCE.exists(), f"no reference at {REFERENCE}")
check(REFERENCE.read_text(encoding="utf-8") == text,
      "the committed reference is stale; run --write")

print(f"Pane layout gate verified: {checks} assertions passed "
      f"({movable} of {regions} regions movable across {len(screens)} screens).")
