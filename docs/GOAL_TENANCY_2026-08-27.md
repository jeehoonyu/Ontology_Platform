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
| **T1** | The unscoped-read census exists, is ratcheted, and runs on every push | exists and gates | did not exist | **Met** — `oms/audit_tenancy_scope.py`, ceiling 396; `oms/test_tenancy_scope.py`, 18 assertions; twelfth check in the pre-push hook |
| **T2** | Every unscoped read that has a principal in hand uses the accessor | `authorized_reference` at 0 | `unscoped_reads_ceiling` 396, of which `authorized_reference` is 103, after `ontology_core`'s undo went from 5 to 2 | **Open** — the census now separates the three repairs (103 swap, 230 thread, 63 contain, the last of them T9) instead of quoting one number that hid them |
| **T3** | No route authorises from a value in its own request body | 0 | 2: `POST /cipher/decrypt` read `principal` from the body; `cipher_ops` bulk transform did the same | **Met** — both authorise the calling principal. Naming a different one is delegation and now costs `administer`. `oms/test_cipher.py` asserts an editor is refused and an administrator is not |
| **T4** | A listener cannot be created with authentication disabled | 0 | `ListenerCreate.auth_type` defaulted to `"none"`, `create_listener` permitted it, `_check_listener_auth` returned True for it unconditionally | **Met** — `auth_type` is required, so silence is a 422; `"none"` still exists and now costs `administer`. `oms/test_webhooks_ops.py` asserts both, and that an administrator still can |
| **T5** | Object mutation through an app runtime performs the approval gate | 2 of 2 runtimes | `workshop_runtime` did; `slate_runtime` and `automate_ops._run_action_effect` did not | **Met** — both stage an `ApprovalRequest` for a high-risk action instead of mutating, and name the caller rather than `"slate"` or nobody. `oms/test_slate_carbon.py` and `oms/test_automate_action_effect.py` assert the object is untouched and the request names who asked |
| **T6** | Object-type mutation is project-scoped and names its actor | 2 routes | `PUT`/`DELETE /ontology/object-types/{id}` called neither `assert_project` nor `object_type_for`, and audited as `"system"` | **Met** — both resolve through `semantic_scope.object_type_for` and audit the caller; `PUT` additionally refuses to change `__manager.project_id`, which three modules read as the owning project. `oms/test_ontology_core.py` asserts all three |
| **T7** | The nine modules R6 deferred as per-route are gated | 9 of 9 | 0 of 9; 75 mutating handlers remain | **Open** |
| **T8** | Tenancy is enforced somewhere a reviewer can point at | one named mechanism | 401 reads each responsible for their own scoping | **Met** — `oms/app/semantic_scope.py`. It already existed, with typed accessors for the six models the reads concentrate in, at 118 call sites. The question was not what to build but why 396 reads bypass it, and the census now answers that per site |
| **T9** | A worker reads only the project of the work it was handed | one named mechanism | 63 reads with no caller to authorize and no rule that replaces one | **Open** — `semantic_scope` cannot serve these: its accessors authorize a principal and a worker loop has none. Every model reached from one carries `project_id`, so the scope exists and only the filter is missing |
| **T10** | No table holds tenant work without recording which tenant | `tenant_orphan_ceiling` at 0 | 52 of 271 tables reach no project, directly, through a declared foreign key, or through the `<stem>_id` convention this schema mostly uses instead, and 189 route handlers serve them | **Open** — the cause the other conditions measure the symptom of. `oms/audit_tenant_orphans.py`, `oms/test_tenant_orphans.py`, fourteenth check in the pre-push hook |
| **T11** | An object type's project is recorded in one place | one spelling | two: the `ObjectType.project_id` column, read by 14 modules, and `properties.__manager.project_id`, read by 11, with 6 modules reading both | **Open** — a row whose two spellings disagree belongs to different projects depending on which module reaches it, so neither can be used to scope a read until they are reconciled |

## What stopped T2 going further, and why T11 exists

Threading the project through `_logic_object_rows` looked like the next mechanical step:
the parameter exists, `workshop_runtime._resolve_one` and `_render_widget` already take a
`project_id`, and they simply were not passing it on. Doing so broke
`test_workshop_tenancy`, and the break was correct.

`workshop_runtime` guards each read with `_assert_object_type_project`, which reads the
type's project from `properties.__manager.project_id`. The filter added underneath it read
`ObjectInstance.project_id`, a column. In that suite's fixture the type's `__manager` says
`alpha-workshop` while its own `project_id` column says `default`, so the guard passed and
the filter matched nothing: a console rendering one row rendered none.

Neither value is wrong. They are two recordings of the same fact that nothing keeps in
agreement, and which one governs depends on which module reaches the row first. Scoping a
read means choosing one, and choosing wrongly hides a tenant's own data as readily as
leaving the read unscoped exposes another's. `POST /objects` shows what agreement looks
like -- it calls `assert_project` and then refuses with a 409 when the type's project
differs from the object's -- but it compares columns, and the modules reading `__manager`
never see that check.

`render_workshop_module` in `apps.py` was fixed rather than reverted because it compares
two columns and never consults `__manager`, so this ambiguity does not reach it. The
changes to `workshop_runtime` and `runtime` were reverted. T2 cannot honestly close the
`for_each`, `object_query` and `object_aggregate` blocks until T11 does.

## What T2 could not close, and why T10 exists

`render_workshop_module` resolved each widget's `object_type_id` across every project, so
anyone who could view a module received another tenant's instance ids and row counts. The
ids come from the module definition rather than from the caller, so authorizing the module
proved nothing about what they named. That one was repairable in an afternoon, because
`WorkshopModule` carries a `project_id` to confine the resolution to.

The identical defect in `render_document` is not repairable at all. `NotepadDocument`
records no project, and neither does anything it reaches, so there is no value to filter
on. The fixture written for the workshop fix exposed it by accident: a row seeded in
`tenant-b` appeared in the notepad render's `sample_ids` two hundred lines away.

That is the same shape T5 recorded for `SlateApp` and `AtmAutomation`, and counting it
properly turned up 52 tables carrying 189 route handlers between them. It is not a backlog
item behind T2 — it is underneath it.
A read cannot be scoped to a project the row never named, no accessor can be written for
such a table, and `_logic_object_rows` already demonstrates how far that reaches: it grew
a `project_id` parameter, and four of its twenty-one call sites pass one.

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

**T8 came first, and the answer was already in the tree.** `oms/app/semantic_scope.py` has
carried typed accessors for the six project-scoped models these reads concentrate in —
`object_for`, `object_type_for`, `asset_for`, `link_for`, `link_type_for`, `pipeline_for` —
plus `owned_row`, `accessible_query` and `assert_project`, and 118 call sites already use
them. There was no chokepoint to design. The open question was never *where* tenancy is
enforced; it was why 396 reads do not go through the door that exists.

The census answers that now, and the answer is three different repairs, not one grind:

- **103 sites** sit in a function that already declares a `principal`. Swapping the raw read
  for the typed accessor is mechanical and local.
- **230 sites** sit in a private helper below such a function. The helper took `db` and an id
  from its caller and has nobody to authorize, so repairing one means threading a principal
  down or lifting the read up — a change to a call graph, not a swap.
- **63 sites** are in modules with no request surface at all, and those are T9. There is no
  caller to authorize, so the question stops being permission and becomes containment.

Reporting these as one number of 401 was itself the defect this document warns about
elsewhere: a measure that claims more than it checks. The first module opened under the new
split showed why. Five of `ontology_core`'s reads looked identical, and they were not — three
resolved an id out of a reversal payload and then wrote through it, which let a log in one
project rewrite another project's object under a permission that looked correct, while two
were existence checks on a primary key before an insert, where adding a project filter would
have turned a skipped restore into a duplicate-key error. The three are fixed and
`oms/test_ontology_core_ext.py` fails without the fix; the two are commented so the next
reader does not "fix" them.

T3, T4, T5 and T6 were independent of that ordering and independent of each other. Each was a
specific hole with a named route, and none was large.
