# Goal — Repair, in the order the code allows

Stated 2026-08-23 on `phase-00-enforcement`, after an external read of the tree at `000e50f`.

This goal is subordinate to [`GOAL_STANDING.md`](GOAL_STANDING.md) and continues
[`GOAL_2026-08-13.md`](GOAL_2026-08-13.md), whose C1 is still blocked. It does not restate
the tiers in [`GOAL_2026-08-03.md`](GOAL_2026-08-03.md); it names the defects standing
between the code and the claims already made about it, and orders them by dependency rather
than by severity, because three of them cannot be done correctly before another one is.

## The finding

The verification discipline here is better than the code it verifies, and the gap is not
where the documents assume. `GOAL_2026-08-13` found that the enforcement layer had never
run, and built the pre-push hook as the reachable substitute for a CI runner that billing
will not provision. That was the right move. What nothing checked afterwards is whether the
substitute runs.

It did not. `scripts/hooks/pre-push` was tracked mode `100644`, and git skips a
non-executable hook with a hint rather than an error. The only installer was
`scripts/install-hooks.ps1`. And the hook resolved `${PYTHON:-python}`, where `python` is
not a command on a stock macOS or a modern Linux. Three independent reasons, each silent,
each producing a clone on which the nine ratchets enforced nothing — and none of them
visible to a test that read the hook's contents rather than its mode.

The same shape appears one level up, in the gate that was built specifically to stop Tier A
being asserted rather than computed. `audit_tier_a.py` has eight sub-condition checkers.
Two of them — `check_alembic_postgres` and `check_images` — are single `return` statements
that emit `unavailable` unconditionally and inspect nothing. Since `unavailable` is not a
pass by that gate's own rule, **Tier A cannot be claimed by any amount of work**, on any
machine, with any infrastructure present. The commit that introduced it is titled *"Compute
Tier A instead of asserting it"*; it computes six of eight and asserts the other two.

Both are the same defect the standing goal exists to catch, applied to the layer that does
the catching: a mechanism whose silence is indistinguishable from its success.

## What is now true on a POSIX clone

Measured 2026-08-23 on macOS 15 (arm64), Python 3.12.13, Node 25.8.0, from a fresh clone:

| Thing | Before | After |
| --- | --- | --- |
| `scripts/hooks/pre-push` tracked mode | `100644` — skipped by git | `100755` |
| POSIX installer | none | `scripts/install-hooks.sh` |
| Interpreter resolution | `${PYTHON:-python}` — not a command here | venv, then `python3.12`, then `python3`, then `python`, and it says which it took |
| Hook checks passing | 0 of 9 — the hook never ran | **9 of 9** |
| Missing-dependency reporting | `FAIL`, beside real regressions | `unavailable`, counted apart, still blocking |
| `oms/verify.py --fast` | not runnable — no interpreter with the pins | **19 of 19 in 0.1 min** |
| `npm run build` | not runnable — no Node | typecheck and production build clean |
| `npm audit --omit=dev --audit-level=high` | not runnable | 0 vulnerabilities |
| `audit_tier_a.py --deep` | 5 met, 1 unmet, 2 unavailable (2026-08-18) | 4 met, **0 unmet**, 4 unavailable |

The Tier A movement is a re-measurement, not progress: `--deep` was not run on 2026-08-18,
and the sub-condition recorded `unmet` there — the browser matrix — now reports
`unavailable` because no browser report exists at this head on this machine. Nothing
regressed from `met`. The number to read is `0 unmet`.

Docker's CLI is installed here at 28.4.0 and its engine is not running, so the compose
sub-condition remains genuinely unavailable — but it would remain unavailable with the
engine running, because `check_images` never looks.

## Conditions

Ordered by dependency. R3 is the keystone: R4 and R5 are wrong to attempt before it, and
R6 and R9 must ship their measurement before their fix or the fix is unrecordable.

| # | Condition | Threshold | Baseline 2026-08-23 | State |
| --- | --- | --- | --- | --- |
| **R1** | The enforcement hook executes on a clone that is not Windows | 9 of 9 checks run | 9 of 9, tracked mode `100755` | **Met** — `oms/test_hook_installable.py`, 43 assertions; reverting the mode fails it |
| **R2** | A CI run provisions a runner and executes at least one step | ≥ 1 completed run | 0 of 69 | **Blocked** — inherits C1 of `GOAL_2026-08-13`; account billing, or a public repository, or a self-hosted runner. A decision, not work |
| **R3** | Every `ObjectInstance` write passes one chokepoint that validates and records a change event | 7 of 7 sites | 4 of 7 validated, 5 of 7 recorded a change | **Open** — 3 of 7 converted, ceiling 7 -> 4. The three that did neither are done; the four left already do one or both. Suite identical to baseline, 6 failures either side |
| **R4** | Declared property constraints are enforced on write | 6 of 6 kinds | 0 of 6 — `enum`, `pattern`, `minimum`, `maximum`, `min_length`, `max_length` stored, never checked | **Open** — after R3 |
| **R5** | Valid time is implemented, or withdrawn from the API and the README | no unproven claim | `valid_to` hardcoded `None`; `valid_from` never supplied by any caller | **Open** — after R3 |
| **R6** | Authorization coverage is measured, ratcheted, and falling | ceiling recorded, then lowered | 42 modules with zero `require_permission`, holding 388 routes; no ratchet exists | **Open** — ratchet before fix |
| **R7** | Every Tier A sub-condition is computed rather than asserted | 8 of 8 | 6 of 8; `check_alembic_postgres` and `check_images` were constant returns | **Met** — 8 of 8 compute; `oms/test_tier_a_computed.py`, 47 assertions; reintroducing either stub fails it. Compose now renders here, and the postgres chain names what it needs |
| **R8** | No claim in the documentation lacks an implementation behind it | 0 | 6 named: `action_outbox`, `AgentStudio.py`, `ontology_value_types`, `system_migration_records`, the shadowed interface check, `POST /schedules/{id}/trigger` | **Open** |
| **R9** | No release gate decides on a hash-derived metric | 0 gates | 1 — `_evaluate_submission_checks` thresholds `sha256(objective_id:algorithm)` | **Open** |
| **R10** | The unbounded-read scan sees the write paths | scan covers writes | ceiling records 0 while inspecting a 2-entry dict; 7 unbounded sites known and unseen | **Open** — widen the scan before fixing |
| **R12** | The suite passes on a host that is not the one it was written on | 240 of 240 | 234 of 240; six encode Windows or x86 assumptions, one of them a product defect | **Open** |
| **R11** | Approvals are consumed, and idempotency keys are tenant-scoped and expiring | both | an approval is reusable with a fresh key; keys have no project and no TTL | **Open** |

## The suite is green on one machine

Measured 2026-08-23 by running all 240 scripts individually on macOS 15 arm64, which
reproduces `verify.py`'s count exactly. Six fail, none of them for a reason the product
would fail in production, and none of them introduced by the commits above:

| Script | Why it fails here |
| --- | --- |
| `test_recovery_scripts.py` | executes `powershell.exe` by name |
| `test_dependency_provenance.py` | asserts `greenlet` is in the closure. SQLAlchemy declares it for `aarch64`; Apple Silicon reports `arm64`, so the pins resolve to a different closure per platform -- which is the defect D1 was opened about, in the file that checks for it |
| `test_plugin_executor_production_rehearsal.py` | `import yaml`, and PyYAML is not in `requirements.txt`. The same undeclared-import defect the file's own header records fixing for httpx on 2026-08-13 |
| `test_partitioned_snapshot_pipeline.py` | `removeprefix("file:///")` yields `C:/...` on Windows and a *relative* `var/...` on POSIX |
| `test_signed_plugin_runtime.py` | expects `PermissionError` in a denial the sandbox words differently here |
| `test_s3_snapshot_pipeline.py` | **a product defect, not a test one.** `/var` is a symlink to `/private/var` on macOS, so the snapshot path-safety check compares an unresolved parent against a resolved child and rejects its own file: *"is not in the subpath of"*. It fires on any host whose temporary directory traverses a symlink |

Five are the suite encoding its author's host. The sixth is `data_plane` rejecting a Parquet
file it just wrote, and it would do that in production on any such host.

This is R1 one layer further out. The hook ran on one machine; the suite passes on one
machine; and in both cases nothing said so, because the only host that ever ran them was the
one they were written on.

## What the first conversion found

Routing `domain_sentinel` through the chokepoint failed immediately, on its own bootstrap:
`Property 'assignee' expected string, got NoneType`. The Python signature says
`Optional[str] = None` and the ontology declares `{"type": "string"}`, so an unassigned task
wrote a `None` into a typed property and nothing objected, because nothing on that path
validated.

The property language has `required` and no `nullable`, so absence is how it says "no
value" -- which makes dropping unset keys the fix in the vocabulary the ontology actually
has. But the gap is worth recording on its own: **the type system cannot express an optional
typed property**, only a required one and an absent one. Ten arguments in that module alone
are `Optional`. That belongs to R4, and R4 should settle it before enforcing the remaining
constraint kinds, or the first `enum` on an optional property will produce the same
surprise.

## Non-completion rule

Inherited unchanged from `GOAL_2026-08-03`: no condition is marked met while it lacks
objective evidence, partial progress is reported as a measurement rather than a status word,
and `unavailable` is not a pass. R1 is claimed against a test that fails when the defect is
reintroduced, which is the only form of evidence this document accepts for a mechanism.

## What this goal deliberately excludes

- **The typed `/api/v1` migration.** `ROUTE_COVERAGE.md` reports 43 of 1,001 handlers with a
  typed twin. Tier C's own note already draws the conclusion: reading the condition broadly
  "would turn a cleanup into a rewrite." Retire the 35 dual-registered handlers, log the
  rest as scope.
- **Reopening the Tier B availability window.** Blocked on replicated infrastructure, not
  effort. Reopening before R2 settles buys a second stalled window and another closed
  schema freeze.
- **New ratchets before R1.** Nine existed and none of them ran. Ratchet count was never the
  constraint.
- **Removing the legacy shell.** `oms/app/ui/` is 6,316 lines of vanilla JS beside a
  16.7k-line React app. Real duplication, inert, and nothing above depends on it. It needs a
  reachability audit first — which features are served *only* there — because that list
  decides whether removal is a deletion or a migration.
