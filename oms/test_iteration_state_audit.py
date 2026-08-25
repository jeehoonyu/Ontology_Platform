"""The iteration gate reads the backlog, and refuses the ways it goes quiet.

This file is also the check's home: `audit_iteration_state` declares `every suite
run`, and the gate it implements fails any check whose declaration names a place
it does not run. It caught itself on its first execution, which is the strongest
argument available that the rule works.

The rules under test, each exercised against a document or registry that breaks
it:

  gate   a goal document declaring conditions in a shape nothing can parse
  gate   a check whose declared cadence names a home it does not have
  gate   a condition with no recorded state, ratcheted to zero
  gate   a baseline with no recorded date, ratcheted to zero
  note   which conditions are open, how old each baseline is, what to do next

The three shapes a condition is written in — table row, bullet, heading — are all
read, because the interface is *identifiable and stateful*, not *one syntax*. Two
of the oldest goals use the heading form and carry their state inside it; those
documents' narrative is the most valuable thing in them and restructuring it to
satisfy a parser would have been the wrong trade.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import audit_iteration_state as audit  # noqa: E402
from iteration_state import (BLOCKED, MET, OPEN, UNRECORDED, Baseline,  # noqa: E402
                             Condition, Report, build, cadence_gaps,
                             conditions_in, next_step, read_baselines)

checks = 0


def check(condition, message):
    global checks
    assert condition, message
    checks += 1


# --- all three shapes are read, and each carries its state -------------------
bullet = conditions_in("- **G1 — A gate that opens a browser.** **Met** — it exists.\n"
                       "- **G4 — Decide what touch is owed.** **Open** — needs a decision.\n",
                       "doc.md")
check([c.identifier for c in bullet] == ["G1", "G4"], bullet)
check(bullet[0].state == MET and bullet[1].state == OPEN, bullet)

table = conditions_in("| **C1** | A CI run provisions a runner | >= 1 run | 0 of 14 | **Blocked** |\n",
                      "doc.md")
check(len(table) == 1 and table[0].identifier == "C1", table)
check(table[0].state == BLOCKED, table)

heading = conditions_in("### B2 — No route can materialize an object set — **met**\n"
                        "### B5 — Predicate pushdown is not dialect-specific\n", "doc.md")
check([c.identifier for c in heading] == ["B2", "B5"], heading)
check(heading[0].state == MET, heading)
check(heading[1].state == UNRECORDED, "a heading with no state must read unrecorded")
# The state marker is stripped from the title rather than left in it.
check("met" not in heading[0].title.lower(), heading[0].title)

# A tier is a condition too; the oldest goal declares three of them.
tiers = conditions_in("### Tier B — Production pilot accepted — **Open**\n", "doc.md")
check(tiers and tiers[0].identifier == "TierB", tiers)

# Prose that merely mentions an identifier is not a condition.
check(conditions_in("C1 was diagnosed on 2026-08-13 and is a billing block.\n", "d.md") == [],
      "narrative text must not be mistaken for a declared condition")


def report_of(conditions, gaps=(), baselines=(), unparsed=()):
    return Report(conditions=list(conditions), cadence_gaps=list(gaps),
                  baselines=list(baselines), unparsed=list(unparsed))


def counts_of(report):
    return audit.summarise(report)


DATED = Baseline("dated.json", "2026-08-17T00:00:00Z", "0042", 1.0)
UNDATED = Baseline("undated.json", None, None, None)
CLEAN = [Condition("d.md", "A1", "something", MET)]
BASE = {"unrecorded_ceiling": 0, "undated_baselines_ceiling": 0}

ok, failures, _notes = audit.compare(counts_of(report_of(CLEAN, baselines=[DATED])), BASE)
check(ok and not failures, failures)

# --- gate: a document nothing can parse --------------------------------------
blind = audit.compare(counts_of(report_of(CLEAN, unparsed=["GOAL_X.md"])), BASE)
check(not blind[0], "a goal declaring unparseable conditions must fail")
check(any("invisible to the backlog" in f for f in blind[1]), blind[1])

# --- gate: a check that does not run where it says ---------------------------
lying = audit.compare(counts_of(report_of(CLEAN, gaps=["x: declares `every push`"])), BASE)
check(not lying[0], "a mis-declared cadence must fail")

# --- gate: a condition with no state, ratcheted to zero ----------------------
silent = audit.compare(
    counts_of(report_of(CLEAN + [Condition("d.md", "A2", "unstated", UNRECORDED)],
                        baselines=[DATED])), BASE)
check(not silent[0], "an unrecorded condition must fail once the ceiling is zero")
check(any("may fall and must never rise" in f for f in silent[1]), silent[1])

# --- gate: an undated baseline, ratcheted to zero ----------------------------
stale = audit.compare(counts_of(report_of(CLEAN, baselines=[DATED, UNDATED])), BASE)
check(not stale[0], "an undated baseline must fail once the ceiling is zero")

# --- note: an improvement asks for the baseline to be lowered ----------------
better = audit.compare(counts_of(report_of(CLEAN, baselines=[DATED])),
                       {"unrecorded_ceiling": 3, "undated_baselines_ceiling": 0})
check(better[0], better[1])
check(any("lock the improvement in" in n for n in better[2]), better[2])

# --- the ordering that picks the next step -----------------------------------
check("parseable form" in next_step(report_of(CLEAN, unparsed=["GOAL_X.md"])),
      "an unreadable document outranks everything else")
check("do not say whether they are done" in
      next_step(report_of([Condition("d.md", "A2", "x", UNRECORDED)])),
      "unrecorded state outranks a cadence gap")
check("correct its declared cadence" in
      next_step(report_of(CLEAN, gaps=["audit_x: declares `every push`"])),
      "a cadence gap outranks an undated baseline")
check("cannot be shown to be stale" in
      next_step(report_of(CLEAN, baselines=[UNDATED])), "undated outranks an open condition")
check("Take A2" in next_step(report_of([Condition("d.md", "A2", "the work", OPEN)],
                                       baselines=[DATED])),
      "with nothing else owed, the next step is an open condition")
check("State a new goal" in next_step(report_of(CLEAN, baselines=[DATED])),
      "with nothing open at all, the answer is to state a new goal")

# --- the live tree ------------------------------------------------------------
live = build()
check(not live.unparsed, f"unparseable goal documents: {live.unparsed}")
check(len(live.conditions) > 40, len(live.conditions))
check(not [c for c in live.conditions if c.state == UNRECORDED],
      "every condition in the tree must carry a state")
check(not cadence_gaps(), f"checks that do not run where they say: {cadence_gaps()}")

baselines = read_baselines()
check(len(baselines) >= 9, len(baselines))
check(not [b for b in baselines if not b.recorded_at],
      f"undated baselines: {[b.name for b in baselines if not b.recorded_at]}")

# This gate's own baseline is subject to this gate: it must be dated, and it was
# not on the first run, which is how the rule proved itself.
check(audit.BASELINE.exists(), f"no baseline at {audit.BASELINE}")
recorded = json.loads(audit.BASELINE.read_text(encoding="utf-8"))
check(recorded["unrecorded_ceiling"] == 0, recorded)
check(recorded["undated_baselines_ceiling"] == 0, recorded)
check(recorded.get("provenance", {}).get("recorded_at"), recorded)

# The whole gate, applied to the live tree -- not a subset of it.
#
# Everything above checks one of the audit's readings at a time, and between them
# they covered five of the six: unparsed documents, unrecorded conditions, cadence
# gaps, undated baselines, and the gate's own baseline. The sixth -- a baseline
# past the shelf life it declares -- was tested against synthetic reports and never
# against this repository.
#
# That gap had a shape. `overdue` fires only when a head-bound baseline records a
# migration head that is no longer current, so it is unreachable until someone adds
# a revision, and until R14 nobody could: twenty-seven scripts pinned the head. The
# first revision past that lock left four baselines stale, `audit_iteration_state`
# exited 1 saying so, and nothing noticed -- the audit declares `every suite run`,
# this is its suite home, and its home inspected the report instead of judging it.
live_ok, live_failures, _live_notes = audit.compare(
    counts_of(live), json.loads(audit.BASELINE.read_text(encoding="utf-8")))
check(live_ok, f"the gate holds against this tree: {live_failures}")

open_now = [c for c in live.conditions if c.state in (OPEN, BLOCKED)]
print(f"Iteration state gate verified: {checks} assertions passed "
      f"({len(live.conditions)} conditions, {len(open_now)} open or blocked, "
      f"{len(baselines)} baselines all dated).")
