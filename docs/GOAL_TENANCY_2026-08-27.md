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
| **T2** | Every unscoped read that returns a row a caller then uses names a project | `row_used_reference` at 0 | `row_used_reference` 204 of `unscoped_reads_ceiling` 381, of which 27 sit in a function that holds a principal and authorizes nothing | **Open** — the target is no longer the ceiling. 177 of the 384 only ask whether an id is taken, and ids here are primary keys, so scoping those turns a refused insert into a duplicate-key error. `unscoped_reads_ceiling` stays a full-coverage ratchet so a new unscoped read cannot arrive unnoticed; it is not a debt that reaches zero |
| **T3** | No route authorises from a value in its own request body | 0 | 2: `POST /cipher/decrypt` read `principal` from the body; `cipher_ops` bulk transform did the same | **Met** — both authorise the calling principal. Naming a different one is delegation and now costs `administer`. `oms/test_cipher.py` asserts an editor is refused and an administrator is not |
| **T4** | A listener cannot be created with authentication disabled | 0 | `ListenerCreate.auth_type` defaulted to `"none"`, `create_listener` permitted it, `_check_listener_auth` returned True for it unconditionally | **Met** — `auth_type` is required, so silence is a 422; `"none"` still exists and now costs `administer`. `oms/test_webhooks_ops.py` asserts both, and that an administrator still can |
| **T5** | Object mutation through an app runtime performs the approval gate | 2 of 2 runtimes | `workshop_runtime` did; `slate_runtime` and `automate_ops._run_action_effect` did not | **Met** — both stage an `ApprovalRequest` for a high-risk action instead of mutating, and name the caller rather than `"slate"` or nobody. `oms/test_slate_carbon.py` and `oms/test_automate_action_effect.py` assert the object is untouched and the request names who asked |
| **T6** | Object-type mutation is project-scoped and names its actor | 2 routes | `PUT`/`DELETE /ontology/object-types/{id}` called neither `assert_project` nor `object_type_for`, and audited as `"system"` | **Met** — both resolve through `semantic_scope.object_type_for` and audit the caller; `PUT` additionally refuses to change `__manager.project_id`, which three modules read as the owning project. `oms/test_ontology_core.py` asserts all three |
| **T7** | The nine modules R6 deferred as per-route are gated | 9 of 9 | 23 mutating handlers remain across six modules | **Open** — four routers reached the mount loop with no `ROUTER_PERMISSIONS` entry and so with `dependencies=[]`, which was 47 of the 71: `dev_toolchain` (32 routes, no `production_auth` import at all), `automate_ops`, `object_views_ops`, `lineage_ops`. The 24 left are per-route gaps in routers that gate most routes individually, and each needs a tier chosen rather than a router named. `validate_primary_key` was the first taken: it answered "is this key value in use" for any object type, naming the instances that matched |
| **T8** | Tenancy is enforced somewhere a reviewer can point at | one named mechanism | 401 reads each responsible for their own scoping | **Met** — `oms/app/semantic_scope.py`. It already existed, with typed accessors for the six models the reads concentrate in, at 118 call sites. The question was not what to build but why 396 reads bypass it, and the census now answers that per site |
| **T9** | A worker reads only the project of the work it was handed | one named mechanism | 0 such reads; the 63 this condition was opened on were misclassified | **Met** — vacuously, and the honest reading is that the condition should not have been opened. `runtime.py` was called a worker because it carries no `@router.` line, and it is called from thirty modules that do. The census now classifies by reachability from a routed module rather than by where the decorators live, and this application has no module nothing routed can reach. The 63 were helpers all along and are counted with them |
| **T10** | No table holds tenant work without recording which tenant | `tenant_orphan_ceiling` at 0 | 52 of 271 tables reach no project, directly, through a declared foreign key, or through the `<stem>_id` convention this schema mostly uses instead, and 189 route handlers serve them | **Open** — the cause the other conditions measure the symptom of. `oms/audit_tenant_orphans.py`, `oms/test_tenant_orphans.py`, fourteenth check in the pre-push hook |
| **T11** | An object type's project is recorded in one place | one spelling | two: the `ObjectType.project_id` column, read by 14 modules, and `properties.__manager.project_id`, read by 11, with 6 modules reading both | **Open** — a row whose two spellings disagree belongs to different projects depending on which module reaches it, so neither can be used to scope a read until they are reconciled |

## What the sharpened target found

Narrowing T2 from 401 undifferentiated reads to the ones that fetch a row, hold a principal
and authorize nothing turned up eight defects, each the same mistake wearing different
clothes: **an id that arrived inside something already authorized is not itself
authorized.** In every case the permission check was correct and answered a different
question than the read went on to ask.

- `undo_action_log` took ids from the log's reversal payload and wrote through them, so a
  log in one project rewrote another project's object.
- `render_workshop_module` took them from a module's widget definitions and returned another
  project's instance ids and row counts.
- `cancel_agent_task` and `retry_agent_task` took them from a task's stored graph. Both
  authorize each child before mutating it, so nothing foreign was written -- but the status
  read that decided whether to call them did not, and answered with a foreign job's status.
- `_resolve_module` took them from a Carbon workspace's `module_ids` and returned another
  project's saved sets and map layers by display name. `CarbonWorkspace` records no project
  of its own (T10), so the bound there is what the principal can see, not what the workspace
  claims.
- `merge_proposal` checks `publish` against the proposal's project and then follows
  `proposal.branch_id`, which is a pointer out of the row rather than the id that was
  checked. Merging set the status of whatever it named, so a proposal pointing at another
  project's branch closed that branch. It is also the site that justifies the tightening
  above: the looser inheritance rule would have cleared it.
- `run_export` checks `execute` against the export's project and then follows
  `export.source_asset_id`, reads `asset.records`, and writes them to the export's
  destination. `create_export` never checked that the asset it was given belonged to the
  project it was creating the export in, so the two together were a caller-chosen export of
  another project's rows -- the only one of these that moves data out of the system rather
  than returning it. Both ends are closed: creation refuses a mismatch with a 409, and the
  run is scoped as well, because exports recorded before that check still name whatever
  they name.
- `archive_stream` checks `execute` against the stream and then takes `target_asset_id`
  straight from the request body, copying the stream's payloads *into* whatever it names.
  Every other defect here disclosed data; this one writes it, putting one tenant's records
  inside another tenant's dataset.

The fourth is the one worth reading twice. `capture_package_version` takes
`object_type_ids` and `action_type_ids` **from the request body** and copies whatever they
resolve to -- properties, primary key, the full profile, each action's rules -- into a
manifest the caller then owns. The other three depended on what somebody had already
configured; this one let the caller choose. Its own suite asserted tenancy on install and
on artifacts, and never on capture, and its fixture seeded object types with no project at
all, which `POST /object-types` would have refused. With the read left bare, the assertion
added here comes back 201 with another organization's schema in the response body.

## The target T2 could not have reached

T2 asked for `unscoped_reads_ceiling` at 0. No amount of work could have delivered that,
and pursuing it would have made the code worse.

177 of the 391 reads never touch what they return. They ask whether an id is already taken
and then refuse with a 409, and ids in this schema are primary keys, so a row belonging to
another project still occupies one. Adding a project predicate to those reads does not
scope them; it blinds them, turning a correctly refused insert into a duplicate-key error
at commit time. `undo_action_log` carried both shapes three lines apart -- three reads that
wrote through the row they fetched, and two that only asked whether an id was free -- and
scoping all five would have broken restore while fixing the leak.

So the ceiling and the goal have been separated. The ceiling still counts every unscoped
read, because that is what makes a new one impossible to add unnoticed, and it is not
expected to reach zero. `row_used_reference` counts the 204 that fetch a row and then use
it, which is the population where an unscoped read hands over another tenant's data, and
that is what T2 now aims at. Of those, 27 sit in a function that holds a principal and
authorizes nothing -- the rest either delegate the check to a helper the census can see
them hand the principal to, or sit below a handler with no principal of their own.

Getting to that number took three corrections, each of which found the previous number inflated.
Classifying whole modules said 247. Asking whether the enclosing *function* holds a
principal said 103, then 83 once functions that authorize first were separated out. Naming
the authorizing helpers in a regex was never going to keep up -- every module grows its own
`_processor(db, id, principal, "execute")` -- so the census now matches the shape instead:
a variable assigned from a call that was handed the principal, and a read filtering by that
variable's `id`, has inherited the proof. Merely *mentioning* `principal` does not count,
and testing that rule is what showed why: nearly every handler passes `principal.id` to an
audit-log call, so it cleared all 83 at once.

Distinguishing the two is a heuristic -- it asks whether any attribute is read off the
result -- and like the six-line proximity rule it will be wrong about individual sites.
Being wrong about which sites is survivable. Setting a target nobody can reach is not: it
converts a goal into a permanent source of work that cannot be finished, which is the
failure mode `docs/GOAL_CONTINUOUS.md` exists to catch.

## Four routers that were never mounted with a gate

R6 gave 34 routers the permission their strongest route needs. Four never got an entry, and
`ROUTER_PERMISSIONS.get(name, [])` gave them the empty list rather than an error, so they
mounted ungated and looked exactly like the ones that had been considered.

`dev_toolchain` is the one to sit with. It serves 32 routes -- create a repository, write a
file, commit, run checks, merge -- and does not import `production_auth` at all, so there
was nothing to notice missing in the file itself. `automate_ops` (which runs automations),
`object_views_ops` and `lineage_ops` were the others. Between them, 47 of the 71 mutating
handlers the census still counted.

They are gated now by the same rule R6 used: `execute` for `automate_ops` because
`POST /automations/{id}/run` is its strongest route, `edit` for the other three. The census
falls 71 -> 24, and the 24 that remain are a different kind of work -- routers that gate
most of their routes individually and missed some, where the question is which tier a
particular route needs rather than which router was forgotten.

A default that silently means "no permission" is worth noting on its own. `.get(name, [])`
turns a missing entry into an ungated router, and the only place that shows up is a census
nobody had to run.

## A condition opened on a miscount

T9 asked for a mechanism to contain reads that have no caller to authorize, on the strength
of 63 such reads. There are none, and there never were. The census decided "worker" by
asking whether a module declares routes of its own, which is a fact about where decorators
are written rather than about who can reach the code: `runtime.py` declares none and is
called from thirty modules that do, and `domain_sentinel`, `domain_maintenance` and
`object_writes` are each reached from `main`. Every read in this application sits below a
request, and so below a principal.

The condition is closed as met, which it is, vacuously -- and the vacancy is the finding.
Its 63 reads were never a separate problem needing a second mechanism; they are helpers
below handlers, the same 230 that were already there, and they are counted with them now.
A gate answering a question nobody should have asked is worth less than no gate, because it
reports progress on a population that does not exist.

## What the residual is made of

Twenty-seven sites remain in the sharpened count, and reading all of them showed the
residual is mostly the proximity rule's blind spots rather than work:

- Thirteen are worker-endpoint handlers (`run_next_...`) re-reading the row they themselves just leased. They are request handlers like any other; "worker" here names what calls them, not a module the census cannot reach.
- `invoke_webhook` filters `WhExecution` by the `webhook_id` it just authorized.
- `get_ontology_contract_quarantine` already refuses when the asset's project differs from
  the graph's; the check simply sits further than six lines from the read.
- `query_objects` in `ontology_interfaces_ops` already bounds instances by the caller's
  accessible projects, with a comment saying why.

Recording that is the point of a residual. The next person through does not have to
rediscover that these thirteen are fine, and the count does not fall by declaring them so.

## Two refinements the census refused

Thirteen of the remaining sites are worker-endpoint handlers re-reading the row they just
leased -- `run_next_outbox_event`, `run_next_agent_job`, `run_next_pipeline_job`. Teaching
the census to clear them is easy: let a name inherit authorization from a value pulled out
of an already-authorized row, and ten of the thirteen go quiet.

That rule was written, measured, and thrown away. An id *inside* an authorized row is
exactly the thing that is not authorized, and every defect this condition turned up was one:
a reversal entry, a widget definition, a task graph, a workspace's module list, a request
body. A census carrying that rule would have reported nothing while all five were live. The
thirteen stay flagged, and the residual is cheaper than the blindness.

The same reasoning tightened a rule already in place. Inheriting from a call handed the
principal now requires the read to name that row's own `id`, not any of its attributes:
`filter(X.id == row.id)` is re-reading the row that was authorized, while
`filter(X.id == row.child_id)` is following a pointer out of it. That put two sites back
into the count, which is the direction a correction should move when the looser rule was
wrong.

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
- **63 sites** were called workers with no caller to authorize. That was wrong, and it is
  worth being precise about how: the test was whether the module itself declares routes,
  and `runtime.py` does not while thirty routed modules call into it. Classifying by
  reachability instead leaves no such module in this application, so those 63 join the
  helpers above and T9 closes without anyone doing anything.

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
