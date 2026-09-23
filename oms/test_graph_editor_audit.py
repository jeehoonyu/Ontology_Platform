"""A row that no longer describes the canvas must trip the rule, and a true one must not.

Also this check's home: `audit_graph_editor` declares `every suite run`.

X1 of `GOAL_GRAPH_2026-09-23.md`. The reference `docs/GRAPH_EDITOR_PARITY.md`
reports how many of the original's graph controls the pipeline canvas meets, and
that number is only worth something once the rules have been shown to refuse. The
assertions below run the real judge over synthetic tables.

The mutated rows are picked from the tree, not named, for the reason
`test_movement_contract_audit.py` records: a test that names today's gap to close
breaks the day that gap is closed, for a reason about the census and not the rule.
"""
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from audit_graph_editor import (  # noqa: E402
    BASELINE, CONTROLS, FILES, REFERENCE, compare, controls_of, handler_missing, render,
    state_problem,
)

checks = 0


def check(condition, message):
    global checks
    assert condition, message
    checks += 1


live_baseline = {"gaps": len(controls_of(CONTROLS, "gap")), "gap_controls": controls_of(CONTROLS, "gap"),
                 "na_controls": controls_of(CONTROLS, "na")}

# --- the live tree -----------------------------------------------------------------
ok, failures, _ = compare(live_baseline, check_reference=False)
check(ok, f"the current tree fails its own rules: {failures}")
check(len(CONTROLS) == 15, f"the goal read fifteen controls; the table has {len(CONTROLS)}")
check(all(control["file"] in FILES for control in CONTROLS.values()),
      "a row names a file the audit does not scan")

# --- a handler the file no longer has ------------------------------------------------
MAPPED = next(name for name, control in CONTROLS.items() if control.get("handler"))
renamed = copy.deepcopy(CONTROLS)
renamed[MAPPED]["handler"] = "aHandlerNobodyWrote"
ok, failures, _ = compare(live_baseline, renamed, check_reference=False)
check(not ok and any(f"{MAPPED} names `aHandlerNobodyWrote`" in f for f in failures),
      f"a row naming a handler its file does not have passes: {failures}")
check("does not scan" in handler_missing({"file": "workspaces/Elsewhere.tsx", "handler": "x"}),
      "a handler in a file outside the canvas passes")
check(handler_missing({"file": FILES[0], "handler": None}) == "", "a row with no handler is refused")
# A definition, and a whole name: a prefix of a real handler is not one.
check(handler_missing({"file": FILES[0], "handler": CONTROLS[MAPPED]["handler"][:-1]}) != "",
      "a handler found only as part of a longer name passes")

# --- a state says exactly one thing, and a met one is mapped and proven --------------
check(state_problem({"handler": "x", "state": {}}) != "", "an empty state passes")
check(state_problem({"handler": "x", "state": {"gap": "x", "test": "y"}}) != "", "two states pass")
check(state_problem({"handler": "x", "state": {"gap": "  "}}) != "", "a gap with no reason passes")
check("names no handler" in state_problem({"handler": None, "state": {"test": "pane-layout.spec.ts::x"}}),
      "a control met with no handler doing it passes")
check("does not exist" in state_problem({"handler": "x", "state": {"test": "no-such.spec.ts::x"}}),
      "a control met by a spec that does not exist passes")
check("no longer contains" in state_problem({"handler": "x",
                                             "state": {"test": "pane-layout.spec.ts::a title nobody wrote"}}),
      "a control met by a title its spec does not contain passes")

# --- the evasion path: not taken, written instead of a feature ---------------------
GAP = controls_of(CONTROLS, "gap")[0]
evaded = copy.deepcopy(CONTROLS)
evaded[GAP]["state"] = {"na": "nobody asked for it"}
ok, failures, _ = compare(live_baseline, evaded, check_reference=False)
check(not ok and any("newly declared not taken" in f for f in failures),
      "turning a gap into not taken lowers the count and passes")

# --- the ratchet ---------------------------------------------------------------------
PROVEN = "pane-layout.spec.ts::a narrow pane's menu opens with a tap and moves the pane"
improved = copy.deepcopy(CONTROLS)
improved[MAPPED]["state"] = {"test": PROVEN}
ok, failures, notes = compare(live_baseline, improved, check_reference=False)
check(ok and any("->" in note for note in notes), f"closing a gap is refused or unreported: {failures}")

met_baseline = {"gaps": len(controls_of(improved, "gap")), "gap_controls": controls_of(improved, "gap"),
                "na_controls": controls_of(improved, "na")}
regressed = copy.deepcopy(improved)
regressed[MAPPED]["state"] = {"gap": "stopped working"}
ok, failures, _ = compare(met_baseline, regressed, check_reference=False)
check(not ok and any("up from" in f for f in failures), f"a rising gap count passes: {failures}")
check(not ok and any(f"{MAPPED} is a gap the baseline does not hold" in f for f in failures),
      "a met control becoming a gap is not named")

# --- rendering -----------------------------------------------------------------------
text = render()
check(render() == text, "rendering twice gives different bytes")
check(f"**{len(controls_of(CONTROLS, 'test'))} of {len(CONTROLS)}**" in text, text[:300])
for name in CONTROLS:
    check(f"| `{name}` |" in text, f"{name} is missing from the reference")
check(REFERENCE.read_text(encoding="utf-8") == text,
      "docs/GRAPH_EDITOR_PARITY.md disagrees with the source; run --write")
check(BASELINE.exists(), "no baseline is recorded")

print(f"Graph editor audit verified: {checks} assertions passed "
      f"({len(controls_of(CONTROLS, 'test'))} of {len(CONTROLS)} controls met).")
