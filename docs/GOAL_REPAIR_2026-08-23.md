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
| **R2** | A CI run provisions a runner and executes at least one step | >= 1 completed run | 0 of 69 | **Met** — 2026-08-25. Runners provision; jobs execute 9 to 25 steps against 0 for all 69 runs before. The repository was made public, so hosted runners are free and unmetered |
| **R3** | Every `ObjectInstance` write passes one chokepoint that validates and records a change event | 7 of 7 sites | 4 of 7 validated, 5 of 7 recorded a change | **Met** — 7 of 7, ceiling 7 -> 0. `oms/audit_object_writes.py` fails the build on a new direct construction; `oms/test_object_writes.py`, 26 assertions |
| **R4** | Declared property constraints are enforced on write | 6 of 6 kinds | 0 of 6 — `enum`, `pattern`, `minimum`, `maximum`, `min_length`, `max_length` stored, never checked | **Met** — 6 of 6, plus the two halves that made the fix inert: `base_type` is read where `type` is absent, and an archived property is no longer enforced. `oms/test_property_constraints.py`, 41 assertions |
| **R5** | Valid time is implemented, or withdrawn from the API and the README | no unproven claim | `valid_to` hardcoded `None`; `valid_from` never supplied by any caller | **Met** — implemented. Intervals close, `valid_from` is a caller's business time, and a correction makes the two axes disagree. `oms/test_valid_time.py`, 12 assertions |
| **R6** | Authorization coverage is measured, ratcheted, and falling | ceiling recorded, then lowered | 42 modules with zero `require_permission`, holding 388 routes; no ratchet existed | **Open** — measured and ratcheted: 1,012 non-public handlers, 282 mutating ones unauthorized, now **262**. `oms/audit_auth_coverage.py` fails the build when the count rises; `oms/test_auth_coverage.py`, 574 assertions |
| **R7** | Every Tier A sub-condition is computed rather than asserted | 8 of 8 | 6 of 8; `check_alembic_postgres` and `check_images` were constant returns | **Met** — 8 of 8 compute; `oms/test_tier_a_computed.py`, 47 assertions; reintroducing either stub fails it. Compose now renders here, and the postgres chain names what it needs |
| **R8** | No claim in the documentation lacks an implementation behind it | 0 | 6 named | **Open** — 2 of 6 removed (`AgentStudio.py`, `ontology_value_types`). Of the remaining four, one has a dispatcher written in JSON, one is a design decision about a P0 witness, one is cheaper to wire than to delete, and one has an honest replacement that is redder than the fabrication |
| **R9** | No release gate decides on a hash-derived metric | 0 gates | 1 — `_evaluate_submission_checks` thresholds `sha256(objective_id:algorithm)` | **Open** |
| **R10** | The unbounded-read scan sees the write paths | scan covers writes | ceiling records 0 while inspecting a 2-entry dict; 7 unbounded sites known and unseen | **Open** — widen the scan before fixing |
| **R13** | The request-cost ratchet can see the route whose cost defect created it | POST measured | GET only; `POST /pipeline-builder/workers/run-next` is outside it | **Open** |
| **R14** | A new alembic revision does not redden the suite | 0 tests pinning the head literal | 27 of 243 asserted `version == "0042_stream_outer_joins"` after `upgrade head`; 55 files repo-wide | **Met** — 0 pins. Proven by adding a throwaway revision and re-running everything: 6 of 243 at the moved head, the same 6 as at `0042`. `oms/test_migration_head_not_pinned.py`, 259 files scanned |
| **R12** | The suite passes on a host that is not the one it was written on | 243 of 243 | 237 of 243; six encoded Windows or x86 assumptions, one of them a product defect | **Met** — **243 of 243**, `verify.py` 21 of 21 in 12.0 min. Tier A went from 5 met / 1 unmet to **7 met / 0 unmet** |
| **R11** | Approvals are consumed, and idempotency keys are tenant-scoped and expiring | both | an approval is reusable with a fresh key; keys have no project and no TTL | **Open** |

## R2: the first CI run in this repository's history

The block was exactly what `GOAL_2026-08-13` diagnosed, still, five days later and on a
fresh dispatch: *"The job was not started because recent account payments have failed or
your spending limit needs to be increased."* Every job, 0 steps.

Two smaller things had to move first. The workflow triggered only on `push` to `master` and
on `pull_request`, so eighteen commits on a branch produced no run at all and *"is a runner
available today?"* could only be answered by merging something; `workflow_dispatch` answers
it without merging. And the repository went public, which makes hosted runners free and
unmetered — chosen over paid minutes and over a self-hosted runner on a laptop.

Before the switch, `foundry-docs-full/`, `foundary-images/`, `foundry-docs/README.md` and
the ten topic directories were removed from the working tree **and from all 288 commits**:
118 files of notes derived from Palantir's documentation, in Palantir's palette under
`PALANTIR · FOUNDRY` headers, plus five screenshots of the Foundry product UI showing a real
object catalog. This project's own analysis stayed — `VALIDATION_MATRIX.md`,
`VALIDATION_REPORT.md`, `COVERAGE.md`. No credential appears in any of the 3,795 objects
scanned beforehand.

### What running it found

Runners provision and steps execute — 9 to 25 per job. The frontend job passes. The rest is
the first honest look at steps that had only ever been typed by hand:

| Job | First run | Second run |
| --- | --- | --- |
| Frontend type, build, dependency audit | **success** | **success** |
| PostgreSQL migration chain | failed on a pinned head | failed later, at the mixed-workload benchmark |
| Backend, conformance, SQLite migrations | failed on a UI readiness assertion | **cancelled at the 20-minute job budget** |
| Production container and Compose | plugin egress `403 Forbidden` | same |

Two were ours and are fixed. **`ci.yml` pinned the migration head** in an inline assertion —
R14's exact defect, in the one file my gate did not scan, so the file that runs the gates
carried what the gates exist to stop. The gate scans `.github/workflows/` now.
And `test_human_ui_readiness` asserted `/workspace/*` serves the React shell, which is true
only once the bundle is built; the backend job set up Node and never used it, so the
assertion could not hold there and passed locally only because someone had built for another
reason.

Three remain, and all three are the same kind of discovery: **a budget or an environment
that has never been exercised.** The backend job's `timeout-minutes: 20` was written without
a run to size it against and the suite does not fit. The mixed-workload benchmark and the
egress rehearsal have never executed anywhere but their author's machine. None of these is a
regression; each is a number or an assumption meeting reality for the first time, which is
what C1 was opened to make possible.

## R12: the six, and what each was really hiding

Every one was a host assumption, and three of them were hiding a check that had never run.

| Was | Really |
| --- | --- |
| `test_s3_snapshot_pipeline` | **A product defect.** `_parquet_manifest_metadata` compared an unresolved base against resolved children, so on macOS — where `/var` is a symlink to `/private/var` — it rejected the Parquet file it had just written. Worse, the bare `except Exception` reported a path bug as *"Registered snapshot is not valid Parquet"*, naming a file that was perfectly valid. Both sides are resolved now, and a file genuinely outside the directory says so in its own words. |
| `test_signed_plugin_runtime` | **A sandbox check that never ran off Windows.** The escape attempt opened `C:/Windows/System32/drivers/etc/hosts`. On Windows that path exists, so the sandbox denies it and the case proves something. Everywhere else the open failed with `FileNotFoundError` *before the sandbox was consulted*. It now opens a path that exists on the host, and the denial is real: `PermissionError: Plugin filesystem access is outside the sandbox`. |
| `test_recovery_scripts` | **Two shims, one platform.** It invoked `powershell.exe`, which exists only on Windows, and stubbed docker with a `docker.cmd` batch file that POSIX `PATH` lookup can never resolve as `docker` — so the scripts found the *real* docker and tried to reach a daemon. It resolves `pwsh` now and writes an executable POSIX shim beside the `.cmd`. |
| `test_dependency_provenance` | SQLAlchemy declares `greenlet` for `platform_machine` in `{aarch64, …}`; Apple Silicon reports `arm64`, so the *exact* pins resolved to a different closure per platform — inside the file whose entire subject is that a measurement names the code that produced it. Declared explicitly. |
| `test_plugin_executor_production_rehearsal` | `import yaml`, and PyYAML was undeclared — the same defect `requirements.txt` already records for httpx, found the same way. |
| `test_partitioned_snapshot_pipeline` | `removeprefix("file:///")` leaves `C:/…` on Windows and a *relative* `var/…` on POSIX. It now calls `data_plane._file_uri_path`, the product's own helper, instead of keeping a second copy of the rule. |

## Tier A: 8 met, 0 unmet, 0 unavailable — met

| Sub-condition | 2026-08-18 | now |
| --- | --- | --- |
| validation matrix | met | met |
| documentation conformance | met | met |
| backend suite passes sequentially | met | **met** — 243 of 243 |
| alembic twice on postgres, with downgrade | unavailable | **met** |
| production compose renders and images build | unavailable | **met** — the model renders and all three images build: application, plugin executor, egress proxy |
| browser matrix, attributable skips | **unmet** | **met** — 0 failures, 136 attributable skips |
| alembic twice on sqlite | met | met |
| frontend typechecks, builds, audits clean | met | met |

**Tier A is met**, and recorded as such in its own contract,
[`GOAL_2026-08-03.md`](GOAL_2026-08-03.md). Nothing about the product's features changed to
get there. What changed is that the suite could finally run somewhere else (R12), and that
PostgreSQL and Docker were present for the first time.

One last thing the run exposed. `audit_tier_a`'s verdict was a single unconditional line —
*"Tier A is not claimable while {n} of 8 are unmet or unavailable"* — formatted with the
count. So a complete run printed **"not claimable while 0 of 8 are unmet or unavailable"**:
the gate built to compute the tier could not report the one answer it existed to find. That
is the shape of the two constant checkers R7 replaced, surviving in the sentence that
reports them. It can say it now.

PostgreSQL was installed here to earn its row. It runs on port 5433 and is not registered as
a login service, so it stops with `pg_ctl -D /opt/homebrew/var/postgresql@16 stop`.

## Moving the head found the staleness gate running nowhere

The first revision past R14 immediately invalidated four head-bound baselines, which is
correct — their measurements describe a schema that no longer exists.
`audit_iteration_state` said so and **exited 1**. Nothing noticed.

Its cadence is `every suite run` and its suite home is
`oms/test_iteration_state_audit.py`, which applied five of the audit's six readings to the
live tree — unparsed documents, unrecorded conditions, cadence gaps, undated baselines, and
the gate's own baseline — and tested the sixth only against synthetic reports. The sixth is
`overdue`, and it can fire only when a head-bound baseline records a head that is no longer
current, which was **unreachable until R14**: nobody could add a revision while twenty-seven
scripts pinned the head. The check was untestable in practice, so its home inspected the
report instead of judging it, and that read as covered.

That is `test_check_homes.py`'s own thesis one level further down — *it matters that they
are executed here rather than inspected*. The live gate is now applied whole; re-staling one
baseline fails the suite.

All four were then re-earned by measuring, not by re-stamping:

| Baseline | How it was re-earned |
| --- | --- |
| `query-bounds` | static AST scan, re-run |
| `request-cost` | 150 routes re-measured against a scratch database |
| `suite-cost` | a real census — 3,579 requests over 688 route+method pairs, which also dropped the stale `/value-types` rows |
| `browser-evidence` | a real Playwright run, 4 viewports |

### The browser matrix passes here

Running it took four attempts, and the first three failures were worth more than the run.
`playwright.config.ts` and `evaluator.spec.ts` both defaulted to `python`, which is not a
command on this machine — the **third and fourth** instances of the assumption R1 fixed in
the hook, one of which surfaced as `spawnSync python ENOENT`, a test reporting a missing
interpreter as a product failure. Four more failures were mine: I ran `npm run build`
instead of `measure_browser_evidence.py --build`, so the bundle carried no provenance.

And one was a defect this repository cannot currently catch: my first fix to
`evaluator.spec.ts` shipped a `ReferenceError` because **`frontend/tsconfig.json` includes
only `src`**, so `npm run build`'s `tsc --noEmit` never typechecks the Playwright specs. A
type error in a test is found only by running it.

The result: **134 passed, 0 failures, 2 flaky**, 136 skips all attributable. `audit_tier_a`
reports *"browser matrix passes with attributable skips: now met"* — the single `unmet` that
had blocked Tier A since 2026-08-18.

The Tier A baseline is deliberately **not** re-recorded. The same run reports `backend suite
passes sequentially` as unmet, because the sequential run carries the six R12 host failures.
Those six pass on the machine the tier was last measured on, so writing this host's answer
into the tier's record would turn a portability gap into a permanent regression. It is
reported here instead: Tier A on this machine is 5 met, 1 unmet, 2 unavailable, and the
unmet one is R12.

## The first revision past R14

`ontology_value_types` is gone: 765 lines, two tables, seven routes, a constraint engine
covering nine families, and an immutable version-snapshot classifier — none of it reachable.
Its one integration point was a `value_type_id` on a property spec, and no route, migration,
frontend file, script or SDK ever wrote one, so its own consumer scan could only return
empty.

`0043_drop_orphaned_value_types` is the first revision added since R14 removed the head
pins. It applies twice idempotently and survives a downgrade/upgrade round trip, and it
deliberately does not name `ix_value_types_id` or `ix_value_type_versions_id`:
`0041_drop_redundant_pk_indexes` derives redundant primary-key indexes from the live schema
and has already taken them, so naming them would fail on any database at that head.

One number is worth stating rather than passing quietly. `test_api_v1_route_coverage.py`
floors the generated alias count at 890; it was 897 before this and is **exactly 890** now.
That is coincidence — the floor happened to carry seven of margin and this removed seven
routes — not a designed boundary. The next legitimate removal will need the floor lowered
deliberately, with the reason recorded, which is the normal way a ratchet moves.

Reported drift, not gated: `docs/suite-cost-baseline.json` still names the `/value-types`
routes. `audit_suite_cost` is declared `manual: needs a full suite census (~20 min)` and was
not re-run here, so the next census is expected to drop them.

## R14: the schema could not move

Twenty-seven suite scripts asserted the head as a literal immediately after `upgrade head`,
and `scripts/rehearse-recovery.ps1` seeded a synthetic `alembic_version` row with the same
string. The effect was not a safety net but a lock: **any new revision reddened
twenty-seven scripts at once**, none of them for a reason connected to what the revision
did — and that lock was quietly blocking three of the five items under R8, two of which
need a table dropped.

No new helper was needed. `tier_b_evidence.current_head()` already reads the chain and
returns the single head, and `audit_evidence_corpus` already used it. The 24 mechanical
sites now call it.

Three sites were not mechanical, and the distinction between them is the rule worth keeping:

- **`scripts/rehearse-recovery.ps1`** seeded a pinned head into a fake database. The value is
  only meaningful as *whatever this repository currently declares* — the rehearsal proves
  backup and restore preserve the schema version, not that the version is any particular
  string. It now reads the head. *Unverified on this machine: there is no PowerShell here,
  and the test that guards it is one of the six R12 host failures.*
- **`test_pipeline_worker_recovery_contract.py`** compared a committed evidence file's head
  to the literal. Staleness already has an owner that treats it as a reported ratchet rather
  than a broken build — `audit_evidence_corpus` reads every `docs/*evidence*.json` and
  reports CURRENT / STALE. The test now asserts the head's *shape* and that the declared
  head equals the observed one, which is the thing no staleness report would catch.
- **`test_external_evaluator_evidence.py`** built a synthetic bundle; it now describes the
  tree it is tested against.

The gate forbids only the **head**, and the first draft got that wrong — forbidding every
revision id reported 60 offenders, all of them correct. A migration test seeds a database at
an older revision on purpose; `0003_platform_job_leases` is the starting point of the
upgrade being tested and will never move. The head is the one id that changes whenever
anyone adds a revision, so it is the only one a literal can go stale against.

**Proven rather than asserted.** A throwaway `0043` revision was added, the whole suite and
every static audit re-run against the moved head, and the revision removed: 6 failures of
243, the same six as at `0042`.

## R8: five of the six were not deletable, and finding that out was the work

Twelve agents traced every consumer of the six candidates and then tried to refute each
verdict. **Four of six verdicts were overturned by the refutation pass**, which is the
justification for having run it: every one of those four would have been a broken build.

**`AgentStudio.py` — removed.** Inert as claimed: no importer, no test, no CI step. But not
free-standing — `oms/Dockerfile:20` copied it into the production image, so deleting the
file alone would have broken the container build, `docker compose up --build`, the CI
container job, the production-acceptance rehearsal, *and* the `check_images` checker written
two commits earlier for R7. The Dockerfile line went with it, along with four documentation
claims that told readers to run it. Its replacement text was checked against the running
app rather than written from memory — the first draft named a response key
(`staged_actions`) and an agent id (`maintenance_copilot`) that do not exist, which is
exactly the defect being repaired.

**`action_outbox` — do not delete.** The premise said rows are written and never read. That
is false twice over. Ten application call sites read the table as the ledger of the last
executed action — `asset_reliability_scenario` and `industrial_workflow` build workflow
state, proof reports and the Command Center's execution-evidence panel from it, and
`outbox_event_id` is the only execution handle `POST /actions/execute` returns to a client.
And the dispatcher does exist; it is simply not written in Python.
`debezium-connector.json:13` captures `public.action_outbox`, and `docker-compose.yml:106`
runs the connector. What is missing is not the consumer but the status transition.

**`ontology_value_types` — blocked by R14.** Genuinely unwired: nothing writes the linking
key through any route. But dropping two tables needs a revision past `0042`, and 27 test
scripts assert that literal head immediately after `upgrade head`.

**`system_migration_records` — blocked, and the honest version is redder.** Twelve
consumers, including `/project/validate`, `/project/readiness`, `/ui-state/validation` and
the React Validation workspace, plus two whole test files. The refutation's finding is the
one that matters: a truthful `/system/migrations` returns no head on every SQLite
`create_all` fixture in this repo, so replacing the fabrication turns three green tests red.
The fabrication is worth removing and it is not a deletion.

**The shadowed interface check — one assertion away.**
`oms/test_api_v1_route_coverage.py:22` asserts `len(authoritative) >= 4`, and the count is
exactly 4. The shallow handler is authoritative *only because* it claimed the `/api/v1`
shape first; removing it drops the count to 3 and fails the build. Worse, the other three
entries are the `/automations` duplicates — fixing all four the same way drives the bucket
to 0 and leaves a **P0** row in `VALIDATION_MATRIX.md` with no witness. That is a design
decision about what evidence the P0 claim rests on, not a deletion.

**The schedule endpoints — cheaper to wire than to delete.** Inert as described, with no
consumer anywhere including the vanilla UI. But bare deletion strands `GET /builds` and
`GET /schedules/{id}/metrics`, and dropping the table needs a revision — R14 again. One
correction to the premise: `POST /project/import` also writes `builds` rows, so fabricated
`success` rows propagate through snapshot export/import and survive either fix until they
are purged.

## Authorization, counted before it is closed

The census counts **handlers, not routes**, because `api_v1_compat` clones every eligible
legacy route into `/api/v1` reusing the same endpoint object -- counting routes would report
a surface twice its real size and halve the apparent severity of every gap. It takes its
public paths from `production_auth.PUBLIC_PREFIXES`, which is now a module constant used by
the middleware itself, so the audit cannot judge a route the gate exempts.

| | |
| --- | --- |
| non-public handlers | 1,012 |
| authorized | 535 → **568** |
| unauthorized | 477 → 444 |
| **unauthorized and mutating** (the gate) | 282 → **262** |

Mutating handlers are gated; unauthorized reads are reported and not gated, because several
are deliberately public and the rest are a larger argument than one ratchet should try to
win. A handler counts as authorized only when **every** route reaching it authorizes -- one
gated on its legacy path and open on its generated twin is an open handler, and the
optimistic reading would have called it covered.

The first twenty closed are `admin_auth` and `admin_directory`, mounted with
`administer` at the include site rather than on twenty signatures. That mechanism was
available all along: nothing in this codebase used `APIRouter(dependencies=...)` or
`include_router(..., dependencies=...)`, so it was unused rather than unsuitable.

**This closes authorization, not tenancy.** Several of these tables carry no `project_id` at
all, so a gated route can still read across tenants. That is a separate condition and must
not be mistaken for finished here.

## Valid time: implemented rather than withdrawn

The plan offered both, and said retraction was smaller. Reading the code changed the
answer. `_query_source` has always filtered `valid_from <= t AND (valid_to IS NULL OR
valid_to > t)` -- the correct half-open predicate, written correctly, the whole time. The
read side was finished. Only the write side was missing, in two ways:

- **No caller ever supplied a business time.** `valid_from=` appeared once in the whole
  backend, as the recorder's own default of `now`. Every event had
  `valid_from == transaction_time`, so the axes moved together and `as_of_valid_time`
  could not answer anything `as_of_transaction_time` did not answer identically.
- **No interval was ever closed.** `valid_to` was written as `None` at the only write site
  and set to a non-NULL value nowhere, so the predicate's second half was dead code.

Withdrawing would have meant deleting a working query planner to match a missing parameter.
Both gaps are now closed at the chokepoint, and the claim is testable: an object is silver
in January and gold from June; an auditor in December records that it was really bronze all
along. *What we believe now about March* is bronze; *what we believed in June about March*
is silver. One object, one question, two answers, one per axis.

What is deliberately not implemented is interval splitting. A correction effective before an
existing interval supersedes rather than divides it, and `_close_prior_interval` says so in
its docstring rather than implying more. The cost is bounded too: the close is skipped
entirely at version 1, so a bulk hydrate of new objects pays nothing for it and the numbers
below still hold.

## What history costs on a bulk hydrate

Measured by `oms/measure_object_write_cost.py`, recorded in
`docs/object-write-cost-evidence.json`, at 100 and 1,000 records because a repeat count
means nothing until you know how it moves with the data.

| records | history | statements | outbox rows | ms |
| --- | --- | --- | --- | --- |
| 1,000 | no | 1,005 | 0 | 238 |
| 1,000 | yes | 2,010 | 1,000 | 498 |
| 1,000 | yes, project with no production environment | 3,009 | 1,000 | 729 |

Measured first at **+1,005 statements per 1,000 records** -- one extra read each, from
`_next_change_version`. `a6a4218` removed the per-object *flush* from that path and said so
plainly, *"the worst shape is now a read"*; this was that read. A bulk hydrate writes a
thousand *distinct* objects, so the pending-version map it left behind never hits.

`prime_change_versions` answers the whole batch with one grouped query before the loop
starts. The cost of history then falls to **+7 statements at 1,000 records, and +6 at 100**
-- constant, not linear -- leaving only the inserts it must do:

| records | history | statements | outbox rows | ms |
| --- | --- | --- | --- | --- |
| 1,000 | no | 1,005 | 0 | 236 |
| 1,000 | yes | **1,012** | 1,000 | 371 |
| 1,000 | yes, without the batched read | 2,010 | 1,000 | 490 |
| 1,000 | yes, project with no production environment | 2,011 | 1,000 | 608 |

So the answer to what history costs a hydrate is: two rows per object and seven statements
per batch. The remaining O(N) shape on that path is `record_object_snapshot`'s own
per-object read, which predates this work and is now the worst one left.

The third row is a separate finding. `_active_revision_id` caches the environment row per
session but caches only a *found* one, deliberately, so that a project acquiring an
environment mid-request still sees it. A project without one therefore re-queries per
record and pays a third statement. Correct, documented, and worth knowing before anyone
measures a bare project and concludes history costs 3x.

### The ratchet cannot see this route

`audit_request_cost` selects `"GET" in route.methods`. Every route it measures is a GET, so
`POST /pipeline-builder/workers/run-next` -- the route whose 1,006 outbox inserts prompted
the ratchet's own rule -- has never been measured by it. That is R13, and it is why this
measurement had to be written by hand.

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
has. Two more writers produced the same `None` afterwards, so the rule moved to the
chokepoint as `drop_unrepresentable_nulls`, narrow enough that a `json` property keeps a
null that was meant. An optional typed property is now expressible, which is what R4 was
waiting on.

R4 then found two halves that would have made it inert. The type key is spelled `type` in
the object type's column and `base_type` in the profile, and `_schema_type` read only the
first -- so pointing validation at the live schema, which R3 did, validated *nothing* for
exactly the types that had been edited. And a property retired with `status: "archived"`
kept its `required` flag, so retiring one made every later write fail against a schema
nobody meant to apply. Enforcing the six constraints without those two would have been more
validation and less checking.

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
