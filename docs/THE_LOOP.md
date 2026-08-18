# The loop

How work proceeds here, in five steps, so that continuing does not depend on remembering.

```bash
python oms/audit_iteration_state.py --status   # 1. what is owed
# 2. take the step it names
python oms/verify.py                           # 3. did it work
# 4. record the state it discharged, in the goal document
git commit && git push                         # 5.
```

## 1 — Ask what is owed

`audit_iteration_state.py --status` reads every `docs/GOAL_*.md`, the check registry and the
baselines, and prints the open conditions, any check that runs somewhere other than where it
says, how old each baseline is, and one `Next:` line.

That last line is chosen by a stated ordering, not by mood:

1. a goal document nothing can parse — everything after it is unreliable while it holds
2. a condition with no recorded state — a backlog you cannot read cannot be prioritised
3. a check whose declared cadence names a home it does not have
4. a baseline with no date, then the oldest one
5. the first open condition

It names the next step *within goals already stated*. It never decides what the project
should care about; that judgement stays with a person.

## 2 — Take the step

One condition, or one piece of one. The habit that produced everything good here is narrow:
measure before changing, and let the measurement decide the change. Three findings in the
last week were the reverse of what the reading suggested, and each was caught by measuring:

- `/project/readiness` was named a defect twice before a third measurement showed the repeated
  shape was one-time migration seeding
- four checks were reported as never running when they run in the suite and are merely
  mis-declared
- seven screens were reported as missing empty states when all seven have them, in the
  application's most common form

If a condition turns out to be wrong, correct it in the goal document and say so. A condition
is a claim, and the same rule applies to it as to any other: no claim outlives its proof.

## 3 — Verify

```bash
python oms/verify.py --fast   # static audits, seconds — before a commit
python oms/verify.py          # + the 230-script suite, ~25 min — before a push
python oms/verify.py --full   # + browser and census — before believing a number
```

Two checks report rather than gate — `validate_tier_b_evidence` and
`validate_external_evaluations` — and appear as `note`. They exit non-zero because the work
they describe is genuinely unfinished, and asserting they pass would assert otherwise. They
are required to complete, never to pass.

## 4 — Record what it discharged

Set the condition's state in its goal document: `**Met**`, `**Open**` or `**Blocked**`, and
when met, name what discharged it. This is the step that decays first and costs the most when
skipped — a finished goal with no recorded outcome is indistinguishable from an abandoned
one, which is how forty-five conditions came to carry five states between them.

`audit_iteration_state` fails if any condition has no state, so the loop cannot quietly skip
this.

## 5 — Push

The commit message carries the reasoning, including anything the work disproved. Corrections
are the most valuable thing in this repository's history and they belong in it rather than in
a person's memory.

## Cadences

| Tier | Cost | When |
| --- | --- | --- |
| `verify.py --fast` | seconds | before every commit |
| `verify.py` | ~25 min | before every push |
| `verify.py --full` | ~50 min | before recording a baseline, or believing a measurement |

Two things this does not yet do, and both are open as conditions in
[`GOAL_LOOP_2026-08-18.md`](GOAL_LOOP_2026-08-18.md): no baseline declares how long its
evidence stays current (K2), and twenty-two of forty-two checks declare a cadence naming no
trigger that exists (K3).
