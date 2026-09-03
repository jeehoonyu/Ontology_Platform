# Goal — The backlog does not run dry, and nothing measured goes unowned

Stated 2026-08-29. This goal does not complete.

[`GOAL_STANDING.md`](GOAL_STANDING.md) is the discipline that keeps a claim from outliving
its proof. This is the discipline that keeps the *work* from running out silently — the
other half of the same idea, and the one nothing enforced.

## The finding

`audit_iteration_state.next_step` chooses the next step by a stated ordering, and its own
docstring is careful about what that is worth: it picks the next step *within goals already
stated*, and "never decides what the project should care about; that judgement stays with a
person." When a goal's conditions are all met it prints **State a new goal** and stops.

Every goal in this repository so far was opened because somebody noticed something. That
makes one person's attention the single point of failure for the whole discipline, and it
fails in the worst possible way: **a backlog that has run dry looks exactly like a project
with nothing left to do.** Green checks, an empty next step, and no way to tell the
difference.

It is also unnecessary, because the backlog was already written down and nobody was reading
it. Thirteen ratchets run on every push and each records a number. Six of those numbers are
not zero. Each is a stated distance from a stated target, produced by a check that already
runs. Nobody had ever aggregated them, so four of the six were owned by no condition in any
document — measured every push, reported to nobody, aging without ever becoming work.

## The mechanism

`oms/audit_frontier.py`, the thirteenth check in the pre-push hook.

- **It reports** the frontier: every non-zero ceiling, sorted by distance, and which
  condition owns it. "What should we do next" now has an answer that does not depend on who
  is looking.
- **It gates** one thing: a non-zero ceiling that no open condition names. Owning a gap
  costs one row in a goal document, which is the cheapest commitment this project has and
  the mechanism everything else here runs on.

A threshold is not a distance, and the audit says so: `repeat_ceiling: 6` means no route may
repeat a statement shape more than six times, not that six things need fixing. Reading a
limit as a debt would inflate the frontier with work nobody owes.

**This goal is the owner of last resort.** A gap with no better home lands here, which is
what makes the mechanism self-feeding: the ratchets propose, a person disposes, and nothing
falls through because falling through fails the build.

## The frontier at statement time

| distance | measure | owned by |
| --- | --- | --- |
| 401 | `unscoped_reads_ceiling` | `GOAL_TENANCY_2026-08-27` T2 |
| 75 | `unauthorized_mutating_ceiling` | `GOAL_REPAIR_2026-08-23` R6 |
| 32 | `raw_empty_ceiling` | K2, below |
| 23 | `unrecorded_ceiling` | K3, below |
| 10 | `unprovenanced_ceiling` | K4, below |
| 1 | `ontology_type_coupling_ceiling` | K5, below |

The bottom four were found by the mechanism on its first run. None of them is new work in the
sense of newly created; all four are old measurements that had never been claimed.

## Conditions

| # | Condition | Threshold | Baseline 2026-08-29 | State |
| --- | --- | --- | --- | --- |
| **K1** | Every measured gap is owned by a stated condition | 0 unowned | 6 of 6 unowned when first measured | **Met** — `oms/audit_frontier.py` gates it on every push; all six are now claimed |
| **K2** | Hand-written empty states are replaced by the shared primitive | `raw_empty_ceiling` at 0 | 32 | **Open** |
| **K3** | Every evidence file records the third-party code that produced it | `unrecorded_ceiling` at 0 | 23 of 24 | **Open** |
| **K4** | Every evidence file records the migration head it was taken at | `unprovenanced_ceiling` at 0 | 10 | **Open** |
| **K5** | No UI surface couples to a concrete ontology type | `ontology_type_coupling_ceiling` at 0 | 1 — `frontend/src/workspaces/OntologyManager.tsx` | **Open** |
| **K6** | No ratchet sits at a ceiling nobody has ever lowered | `unmoved_ceiling` at 0 | 2 of 17: `ontology_type_coupling_ceiling` recorded five times and never fell, `raw_empty_ceiling` twice | **Open** — measured now rather than asserted. `oms/audit_ratchet_motion.py` reads each ceiling at every commit that touched its baseline and asks whether it ever fell; `oms/test_ratchet_motion.py`; fifteenth check in the pre-push hook |
| **K7** | A completing goal's last condition names its successor | the frontier is consulted before a goal is closed | done by hand today, and only because someone remembered | **Open** |
| **K8** | No ratchet's ceiling stands above what it currently measures | every ceiling equals its measurement | not measured; `unauthorized_mutating_ceiling` stood at 75 while the count had been 71 since before the branch that found it | **Open** — 5 of 27 audits announce an unlocked improvement and 22 say nothing, so the uniform check needs every audit to report its current value in one shape first |

## K8 caught its author, one commit later

The commit that closed the observability checks lowered the unscoped-read measurement from
364 to 361 and shipped with the ceiling still recorded at 364. Three counts of slack, created
by the person who had just written the condition warning about slack, in the very next commit.

Nothing failed. The audit printed "Ratchet held, and improved: 364 -> 361", the hook passed,
and the gate went on permitting three reads to come back with nothing to show for it. That is
the whole argument for K8 in one incident: re-recording a lowered ceiling is a second,
separate action, and it is the boring half of the work, so it is the half that gets skipped.
It cannot be fixed by remembering harder.

## The slack K6 does not catch

K6 asks whether a ceiling has ever fallen. It does not ask whether it has fallen *far
enough*, and the difference is a gate that is looser than it reads.

`unauthorized_mutating_ceiling` was recorded at 75. The measurement was 71, and had been 71
since before the branch that noticed. Every run in between printed "Ratchet held" and passed,
while quietly permitting four mutating handlers to lose their permission again with nothing
to show for it. The ratchet was not broken and not ignored; it was simply four higher than
the truth, because improving a number and re-recording it are two actions and only the first
is interesting.

That is K8, and it is deliberately not implemented yet. Five audits already print "Ratchet
held, and improved" when they find slack, and the hook could grep for that line tomorrow --
but 22 others say nothing at all, and a gate covering a fifth of the ratchets while reading
like it covers all of them is worse than the gap it papers over. The prerequisite is a
common way for an audit to state what it measured, not a regex over prose that five of them
happen to share.

## Non-completion rule

Inherited unchanged, and it applies to this document oddly: K1 is *met* and must stay met, so
this goal is never finished, only held. Progress here is reported as the frontier shrinking,
never as a status word.

## What this deliberately does not do

It does not decide what matters. The ordering is by measured distance, which is a proxy for
importance and a poor one — 401 unscoped reads are not four hundred times more urgent than
one coupled UI file. What it removes is the failure where nobody is *told* the gap exists.
The judgement stays exactly where `audit_iteration_state` left it, with a person.

It also does not create ratchets. A gap only appears here once some check counts it, so the
frontier is bounded by what the project has chosen to measure — and the honest reading of an
empty frontier is not "we are done" but "we are measuring too little." The audit says so in
that case, rather than congratulating anyone.
