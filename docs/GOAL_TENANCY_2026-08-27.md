# Goal — A permission is not a tenancy check

Stated 2026-08-27 on `tenancy-measurement`, the day after R6 closed privilege.

Subordinate to [`GOAL_STANDING.md`](GOAL_STANDING.md) and successor to
[`GOAL_REPAIR_2026-08-23.md`](GOAL_REPAIR_2026-08-23.md), whose remaining conditions stay
open and are not restated here. That goal repaired what was broken. This one names what was
never built.

## The finding

R6 took 258 mutating handlers with no permission down to 75, and the number is real. It is
also narrower than it sounds, and the narrowing was visible while the work was being done:
nine of the modules flagged their own tenancy holes to the agents choosing their permission.

A permission is a **tier**. It says an editor may edit. It says nothing about *whose rows*.
A caller holding `edit` on their own project, hitting a handler that selects by id alone,
reads and writes another project's data with a permission that looks entirely correct — and
`audit_auth_coverage`, which asks only whether a route checks *something*, reports the route
as covered.

Measured 2026-08-27, for the first time:

| | |
| --- | --- |
| ORM tables | 271 |
| project-scoped (carry a `project_id`) | 122 |
| tenancy substrate or global (correctly have none) | 149 |
| reads of a project-scoped model | 1,086 |
| **reads naming no project within six lines** | **401**, across 64 modules |

The worst are not obscure: `runtime.py` 39, `asset_reliability_scenario.py` 28,
`system_hardening.py` 26, `platform_runtime.py` 22, `stream_processing.py` 19.

## What the 401 is, and is not

It is a ratchet, not a verdict. Six lines of proximity is a coarse proxy for *this read is
scoped*, and it is wrong in both directions — it clears a read whose filter mentions
`project_id` for an unrelated reason, and it flags a read whose id was already authorised by
`semantic_scope.owned_row` three lines earlier. Every site still needs a person.

What it can honestly say is that the count fell, and that a new unscoped read cannot arrive
unnoticed. That is the same bargain `audit_query_bounds` and `audit_auth_coverage` make, and
it is worth stating plainly because a measure that claims more than it checks is the defect
this repository keeps finding in itself.

## Outcome

A caller cannot read or write rows belonging to a project they do not hold, through any
route, whatever permission they carry.

## In scope

1. A census of unscoped reads, ratcheted downward, with a suite home.
2. The read paths that carry the most of them.
3. The routes that authorise from their own request body rather than from a principal.
4. Object mutation through an application runtime that skips the approval gate its siblings
   enforce.
5. One decision about *where* tenancy is enforced — per query, or at a chokepoint the way
   R3 did for object writes.

## Explicitly out of scope

- Row-level security in the database. This is application-enforced scoping; moving it into
  Postgres policies is a different project with a different failure mode.
- The `/api/v1` typed migration, which Tier C already reads correctly as a rewrite.
- Multi-region or cross-organisation isolation. Projects within one deployment.

## Conditions

| # | Condition | Threshold | Baseline 2026-08-27 | State |
| --- | --- | --- | --- | --- |
| **T1** | The unscoped-read census exists, is ratcheted, and runs on every push | exists and gates | did not exist | **Met** — `oms/audit_tenancy_scope.py`, ceiling 401; `oms/test_tenancy_scope.py`, 18 assertions; twelfth check in the pre-push hook |
| **T2** | The five worst modules name a project on every scoped read | `unscoped_reads_ceiling` at 0 | `unscoped_reads_ceiling` 401 (tenancy-scope): `runtime` 39, `asset_reliability_scenario` 28, `system_hardening` 26, `platform_runtime` 22, `stream_processing` 19 | **Open** |
| **T3** | No route authorises from a value in its own request body | 0 | 2: `POST /cipher/decrypt` read `principal` from the body; `cipher_ops` bulk transform did the same | **Met** — both authorise the calling principal. Naming a different one is delegation and now costs `administer`. `oms/test_cipher.py` asserts an editor is refused and an administrator is not |
| **T4** | A listener cannot be created with authentication disabled | 0 | `ListenerCreate.auth_type` defaulted to `"none"`, `create_listener` permitted it, `_check_listener_auth` returned True for it unconditionally | **Met** — `auth_type` is required, so silence is a 422; `"none"` still exists and now costs `administer`. `oms/test_webhooks_ops.py` asserts both, and that an administrator still can |
| **T5** | Object mutation through an app runtime performs the approval gate | 2 of 2 runtimes | `workshop_runtime` did; `slate_runtime` and `automate_ops._run_action_effect` did not | **Met** — both stage an `ApprovalRequest` for a high-risk action instead of mutating, and name the caller rather than `"slate"` or nobody. `oms/test_slate_carbon.py` and `oms/test_automate_action_effect.py` assert the object is untouched and the request names who asked |
| **T6** | Object-type mutation is project-scoped and names its actor | 2 routes | `PUT`/`DELETE /ontology/object-types/{id}` called neither `assert_project` nor `object_type_for`, and audited as `"system"` | **Met** — both resolve through `semantic_scope.object_type_for` and audit the caller; `PUT` additionally refuses to change `__manager.project_id`, which three modules read as the owning project. `oms/test_ontology_core.py` asserts all three |
| **T7** | The nine modules R6 deferred as per-route are gated | 9 of 9 | 0 of 9; 75 mutating handlers remain | **Open** |
| **T8** | Tenancy is enforced somewhere a reviewer can point at | one named mechanism | 401 reads each responsible for their own scoping | **Open** — the R3 question, asked of tenancy |

## What T5 could not close

`slate_runtime` now resolves its ActionType through `semantic_scope.owned_row`, so a slate app
can no longer drive another project's action. `automate_ops` cannot do the same, and the
reason is worth recording rather than working around: **`AtmAutomation` carries no
`project_id`**, exactly like `SlateApp`. There is no project to scope the lookup to.

So the approval gate is closed in both and the scope is closed in one. Adding the column is a
migration and belongs to T2, where the same shape will come up again — a table that holds
tenant work without recording which tenant.

## Non-completion rule

Inherited unchanged: no condition is marked met without objective evidence, partial progress
is reported as a measurement rather than a status word, and `unavailable` is not a pass.

T1 is claimed against a census that runs in the suite and a ratchet that fails the build when
the count rises — not against the census having been written.

## The ordering that binds

**T8 before T2.** Closing 134 sites one query at a time, and then deciding tenancy belongs at
a chokepoint, throws the 134 away. R3 learned this on the write path: seven scattered sites
became one door, and the three findings it closed were all the same fact seen three times. The
same question is open here and should be answered before the grind starts, not after.

T3, T4, T5 and T6 are independent of that ordering and independent of each other. Each is a
specific hole with a named route, and none is large.
