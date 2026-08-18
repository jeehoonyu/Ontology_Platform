# Goal — What to do next, derived rather than remembered

Stated 2026-08-17. Follows [`GOAL_BROWSER_EVIDENCE_2026-08-17.md`](GOAL_BROWSER_EVIDENCE_2026-08-17.md),
and unlike every goal before it this one is about the process rather than the product.

## The direction

Six goals have measured this product and each was chosen the same way: someone looked at the
tree, noticed something, and started. That worked. It does not continue working, because the
thing it depends on — remembering what is still owed — degrades exactly as the record grows.

The record has grown. **Eleven goal documents hold forty-five conditions**, and the project's
own first invariant is not being applied to them.

| | | |
| --- | --- | --- |
| Goal documents | 11 | |
| Documents declaring conditions | 8 | |
| Conditions declared across them | **45** | 35 were found at first; the other 10 only became visible once the parser learned a third format |
| **Conditions with a recorded completion state** | **5** | of 45 |
| Formats those conditions are written in | **3**, mutually unreadable | table row, bullet, heading |

The eight conditions of `GOAL_REQUEST_COST_2026-08-15.md` are a fair example. That goal is
finished — five defects found and fixed, a ratchet built and held — and the document contains
the word "Met" zero times. The work happened; the record of what it discharged did not. A
reader who wants to know what is open has to re-read eleven documents and reconstruct it.

**No claim outlives its proof** was written about measurements. It applies just as well to a
plan: *no open condition should outlive its record.*

## Finding 1 — the backlog is prose, in two shapes

Conditions are written either as a table

    | **C1** | A CI run provisions a runner and executes at least one step | ≥ 1 completed run | **0 of 14** |

or as a bullet

    - **G1 — A gate that opens a browser.** Register the Playwright suite ... **Met**

or as a heading, which is the form the two oldest goals use and the one this document
initially missed entirely

    ### B2 — No route can materialize an object set — **met**

The table form carries a threshold and a starting measurement, which is better, and has **no
column for whether the condition was ever satisfied**. The bullet form can say `Met` and
usually does not. Outcomes get recorded instead as prose headings elsewhere in the document —
`## C1 diagnosed 2026-08-13: it is a billing block` — which a human can follow and nothing
else can.

| Document | Table | Bullet | Marked met |
| --- | --- | --- | --- |
| `GOAL_2026-08-13.md` | 6 | 0 | 0 |
| `GOAL_REPRODUCIBILITY_2026-08-13.md` | 5 | 0 | 0 |
| `GOAL_REQUEST_COST_2026-08-15.md` | 0 | 8 | 0 |
| `GOAL_WRITE_COST_2026-08-16.md` | 0 | 5 | 2 |
| `GOAL_BROWSER_EVIDENCE_2026-08-17.md` | 0 | 6 | 3 |

## Finding 2 — a declared cadence is a claim, and nothing proves it

`check_registry.py` declares 41 checks, thirteen of them `every push`. The pre-push hook runs
nine, and four are not in it:

| Declares `every push` | Actually runs |
| --- | --- |
| `audit_dependency_provenance` | `test_reproducibility_conditions.py` |
| `validate_docs_conformance` | `test_check_homes.py` |
| `validate_external_evaluations` | `test_check_homes.py` |
| `validate_tier_b_evidence` | `test_check_homes.py` |

**The first version of this finding said those four do not run, and that was wrong.** All
four are executed by suite tests — `test_check_homes.py` exists for precisely that purpose
and is itself C2 of `GOAL_2026-08-13.md`, a condition satisfied a week ago. Checking before
asserting turned "four checks never run" into "four checks run somewhere other than where
they say", which is a much smaller problem.

It is still a real one. The registry is what a reader consults to learn when a check runs,
and for four of them it gives the wrong answer. `audit_check_coverage` verifies that every
check is *declared*; `audit_enforcement` verifies that every declared check has *ever* run.
Neither compares a declaration to the mechanism that would have to honour it, which is why
the discrepancy survived with both audits green.

So the gate distinguishes two verdicts rather than one: **unhomed**, where nothing automated
runs the check at all, and **mis-declared**, where it runs somewhere its cadence does not
name. All four here were the second kind, and all four now declare `every suite run`.

## Finding 3 — no baseline can be shown to be old

Nine baseline files hold the ratchets. **None of them records when it was measured.**

| | |
| --- | --- |
| Baseline files | 9 |
| Recording a migration head | 2 |
| **Recording when they were measured** | **0** |

`audit_evidence_corpus` already makes this argument about evidence: something with no
provenance "cannot be shown to be stale, so it never expires". The ratchet baselines are
evidence by any reasonable definition and were exempt from their own rule.

## Finding 4 — there is no command that says how things stand

Establishing the state of this repository, during this session, took: a shell loop over 228
scripts, a twenty-minute census, a browser run, and four separate audits invoked by hand.
Nothing composes them. Nothing reports which conditions are open, which checks have gone
unrun, or which baseline is oldest.

## Conditions

- **I1 — Conditions are machine-readable, and carry their state.** **Met** — `iteration_state.conditions_in`, and this line is the proof. One form across every goal
  document: an identifier, the condition, and an explicit `open` or `met`. A condition marked
  met names what discharged it. A goal document whose conditions cannot be parsed fails the
  gate — the format is the interface.
- **I2 — A declared cadence is proven, not asserted.** **Met** — four declarations corrected
  to `every suite run`, gated by `audit_iteration_state`. A check must have an automated home
  matching what it claims: `every push` in the hook, `every suite run` executed by a suite
  test. A check with no home anywhere is a different and worse verdict than one that is
  merely mis-declared, and the gate says which.
- **I3 — Every baseline is dated and headed.** **Met** — nine baselines dated from their last commit. Each records when it was measured and at what
  migration head, so it can be shown to be old rather than merely believed to be current.
- **I4 — One command reports the state of the world.** **Met** — `python oms/audit_iteration_state.py --status`. Open conditions, checks and when they
  last ran, baselines and how old they are — one table, from static files, in under a second.
- **I5 — The next step is named by a rule.** **Met** — `iteration_state.next_step`, ordering stated in its docstring. The status command ends by naming what to do
  next, chosen by a stated ordering rather than by whoever is reading. Iteration that depends
  on someone feeling motivated is not continuous.

## What this is not

Not a project-management system, and not a burndown. The conditions already exist and are
already good; what is missing is that they are unreadable in aggregate. This adds a state
field, a parser, and a gate — not a workflow.

Not an argument for automating the choice of goals. I5 names the next *step within goals
already stated*, which is a different and much smaller claim than deciding what the project
should care about. That judgement stays where it is.

And not a reason to rewrite the older documents' prose. The narrative sections are the most
valuable thing in them — they are where the reasoning and the corrections live. Only the
conditions get a common shape.
