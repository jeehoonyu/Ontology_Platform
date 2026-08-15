# The Pilot Window

The last three Tier B gates — availability, RPO and RTO — need one thing this repository
cannot supply: **seven consecutive days of a machine that stays up**.

**A window is open.** It started `2026-08-15T03:48Z` and closes `2026-08-22T03:48Z`, at
head `0042_stream_outer_joins`. `docs/SCHEMA_FREEZE.json` is open until one day past that
— a freeze that lapses before the collection it protects protects nothing, and the previous
one would have, by three hours.

**The supervisor now survives a reboot.** `scripts/start-pilot-supervisor.ps1` runs from a
Startup-folder entry, `ontology-pilot-supervisor.cmd`, because `Register-ScheduledTask` and
`schtasks /Create` are both denied to this account. It waits for Docker, brings the project
up if it is missing, waits for the API to serve, and starts the supervisor — or declines,
noting why, if a window is not open, has already closed, or is already being supervised.
Every attempt appends to `supervisor-launcher.log`, so a morning that finds no ticks can be
told from a morning that finds no launcher.

The previous window started `2026-08-14T02:53Z` and was **lost after 3.6 hours**. Nothing
was aggregated, so there was no failed gate — and nothing to show for a day.

What happened, in the order it happened:

1. **23:29 on 08-13** — the supervisor stopped, 3h 36m and 109 backups in. It was a host
   process started from a terminal; nothing outlived that terminal.
2. **05:54 on 08-14** — the first RTO rehearsal came due. Nothing ran it. `recovery_attempts`
   is 0, and `rto-rehearsals.jsonl` and `rpo-samples.jsonl` were never created.
3. **12:26** — the machine rebooted. Docker restarted and the observer came back, because it
   had `restart: unless-stopped`. The API and database did not, because they did not.
4. **13:31** — powered off, unplanned, for nearly six hours. **19:12** — booted again.
5. The observer, doing exactly what the contract requires, backfilled every 30-second slot
   it had missed as unavailable: **2,541 of 2,981 slots**, 76,170 seconds against a 604.8
   second budget. Availability computes to **14.8%**.

Three lessons, none of them about the window that failed:

- **A restart policy on the observer and not on its subject measures the restart.** The
  overlay now gives the API and the database `restart: unless-stopped` too. That was a
  defect in this repository, and the reboot only revealed it.
- **A supervisor that dies with a terminal is not a supervisor.** This is the limitation
  recorded below under "What would end it early", and it ended this one within four hours.
  It must be solved before a window is worth opening again — see that section.
- **The observer surviving better than the product is worse than both of them dying.** A
  dead observer would have shown a gap. A live one recorded eight hours of downtime that
  the product, had anyone been running it, might not have had.

Two earlier attempts on the first night were abandoned before writing any evidence, and
both reasons are still worth knowing.

The first, at `2026-08-14T00:34Z`, was measuring a build whose `/health/ready` reflected
the entire schema on every call — 275 catalog round-trips, 220 ms at rest — and the
availability gate is *defined* on that endpoint answering within 2,000 ms. It had already
crossed the limit twice, spending 60 seconds of a 604.8-second weekly budget in two hours,
a rate no seven-day run survives. The endpoint now answers in 4–5 ms. Its journals are kept
as `evidence-abandoned-20260813`; an abandoned run is not a failed gate, because nothing was
aggregated and no evidence file was written, but deleting it would hide that the window was
started three times.

The second was discarded over one slot. **The availability journal is the window's clock,
not the manifest.** `summarize()` counts from the journal's first sample, so bringing the
observer up alongside the API charges the API's own startup — one refused connection — to
the window as 30 seconds of downtime, 5% of the budget, for something that happened a
minute before `start` ran. Bring the observer up *last*, against an API already answering
200, and confirm the first slots are clean before opening the window.

The rest of this file is what that window is made of, so that watching it, finishing it,
or starting another one is a procedure rather than a rediscovery.

## What the seven days actually cost

Read this before starting another one, because the commitment is larger than the command.

- **7 consecutive days.** `docs/TIER_B_MEASUREMENT_CONTRACT.md` says it outright: *"the
  availability window is 7 days and cannot be compressed. Any plan implying otherwise is
  wrong."* RPO and RTO sample **across** that window, so they cannot be split out and run
  quickly either.
- **10 minutes 5 seconds of total downtime budget.** That is 99.9% of a week. Planned
  restarts count. **Observer loss counts** — the probe backfills every missed 30-second
  slot as unavailable, so the machine being briefly gone is indistinguishable from the
  product being briefly gone, deliberately.
- **No migrations.** A head change voids the window.
- **A failed run is sticky.** A recorded FAIL at the current head stands until deliberately
  superseded, which is worse than the gate simply being MISSING.

A laptop can satisfy the contract — nothing in it requires a particular host class — but a
10-minute budget is unforgiving. One reboot plus a Docker start is typically 2–5 minutes,
so the budget survives roughly one and not two.

## What is running

The window measures a **dedicated pilot stack**, not the development stack and not a
production deployment. Three containers in the Compose project `ontology_pilot_source`:

| Container | Role |
| --- | --- |
| `ontology_pilot_source_api` | the source under measurement, `127.0.0.1:18001` |
| `ontology_pilot_source_postgres` | its database, loopback `15432`, its own volume |
| `ontology_pilot_observer` | owns the availability journal, probes every 30s |

The supervisor runs on the host as `pilot_window.py run`, ticking every 30 seconds. Every
tick writes a recovery mark to the source. Every 2 minutes it takes a backup. Every 10h01m
it restores a **separate** Compose project (`ontology_pilot_recovery`, `127.0.0.1:18002`)
from fresh volumes, times the recovery, and measures how much data the recovery point lost.

Configuration lives outside the repository, in two files readable only by the account that
opened the window:

```
C:\Users\jeehoon\ontology-pilot\
  secrets\pilot-runtime.env        every PILOT_* setting, the integrity key, the image pin
  secrets\pilot-recovery-token     the bearer token, alone, never in a command line
  evidence\                        the journals: availability, marks, samples, rehearsals
  backups\                         24 retained recovery points
```

### Why the numbers are what they are

- **Backups every 2 minutes, not the 5-minute default.** RPO is the age of the recovery
  point at the moment of failure, so a 5-minute backup interval produces samples of very
  nearly 300 seconds against a threshold of exactly 300. That passes on paper and fails on
  a rounding error. At 2 minutes the samples land near 120s with real margin.
- **Rehearsals every 10h01m, not 14h.** Twelve rehearsals in a week is barely more than the
  ten RPO samples the gate requires, so two failed restores would sink it. Sixteen leaves
  room. The extra minute is deliberate: a rehearsal interval that is an exact multiple of
  the backup interval always lands on a backup boundary, and every sample would then be
  taken at the same point in the cycle. Offsetting by one minute alternates them, which is
  what "varied points in the backup cycle" asks for.
- **A 254 MB dataset, not the 32 GB reference.** The reference-scale database exists for the
  query-bounds gates. A logical `pg_dump` of it cannot finish inside a two-minute recovery
  point, and the reference driver says so about itself: logical dumps suit a small pilot.
  Measured here: backup 4.5s, restore 32s, full rehearsal 33.2s against an 1800s limit.

### Watch what the gate is defined on, not only what it measures

Availability is defined as `/health/live` and `/health/ready` both answering 200 within
2,000 ms. That makes the *cost of answering* part of the measurement. The first window
found this the expensive way: `/health/ready` called `schema_health`, which reflected every
mapped table through `information_schema` on every request, and a probe that has to do 275
catalog queries fails the gate by being slow while the product behind it is perfectly
healthy. `oms/test_readiness_cost.py` now counts the statements, because a comment saying
the reflection is cached is an intention and a count is a ratchet.

Before starting a window, probe the endpoint a few times and look at the number, not just
the status code. Anything above a few tens of milliseconds at rest is a warning: the budget
is 2,000 ms, but the margin has to absorb a `pg_restore` running beside it.

### Deviations from the production reference, stated plainly

Both sides of the measurement run `AUTH_MODE=local` and a locally built image rather than
OIDC and a registry release digest, because this host runs no identity provider and no
registry. The recovery protocol that carries every RPO mark and the RTO write is
bearer-token authenticated and does not traverse the OIDC path, so the three gates this
window collects are unaffected. Identity is measured by its own gate and is not in scope
here. `provenance.environment` will read `local`, as it does for every other gate in this
repository.

`docker-compose.pilot-source.local.yml` and `docker-compose.pilot-recovery.local.yml` carry
these differences and nothing else. Everything the RTO and RPO contract constrains — a
separate project, fresh volumes on every restore, a distinct URL, checksummed artifacts,
an authenticated write at the restored head, a source that is never stopped or mutated —
is unchanged from the production reference.

## While it runs

```powershell
python oms/pilot_window.py --evidence-root C:\Users\jeehoon\ontology-pilot\evidence status
```

It reports elapsed hours, probes recorded against probes expected, RPO samples against the
10 required, RTO rehearsals against 4, and whether the observer is still writing. It fails
loudly if the migration head has drifted, because at that point the window is void and
continuing wastes the remaining days.

The supervisor's own log is `C:\Users\jeehoon\ontology-pilot\supervisor.log`, one JSON line
per tick.

### What would end it early

- **A migration.** The supervisor stops on a head change rather than pool two schemas.
- **Losing the supervisor.** It is a host process, and it dies with the terminal that
  started it. That killed the first window inside four hours. It now comes back at logon
  from a Startup-folder entry, which needs no privilege — the durable options do not exist
  here, because `Register-ScheduledTask` and `schtasks /Create` both answer "Access is
  denied", elevated or not.

  ```powershell
  # Run it by hand any time; it is idempotent and says what it decided.
  & "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\ontology-pilot-supervisor.cmd"
  Get-Content C:\Users\jeehoon\ontology-pilot\supervisor-launcher.log -Tail 5
  ```

  The launcher waits for Docker, brings the Compose project up if it is missing, waits for
  the API to serve, and starts one supervisor — declining if a window is not open, has
  already closed, or is already being supervised. Deleting the `.cmd` stops it coming back.
  On a host where task registration *is* permitted, `scripts/register-pilot-window.ps1`
  does the same thing through Task Scheduler; it registers a **logon** trigger as well as a
  boot trigger, because a task owned by an interactive account never fires at boot.
- **Docker not coming back.** All three containers carry `restart: unless-stopped` and
  Docker Desktop starts at logon here. The first window found out why the API needs that as
  much as the observer does: only the observer had it, so after a reboot the probe returned
  to a stack that was not serving and correctly recorded eight hours as downtime. A
  measurement that survives a restart better than its subject does is measuring the restart.

Losing minutes is survivable; losing the observer for a quarter of an hour is not. Losing
the *product* while the observer watches is worse than losing both.

## Finishing

```powershell
python oms/pilot_window.py --evidence-root C:\Users\jeehoon\ontology-pilot\evidence aggregate
```

Emits availability, RPO and RTO gate files under `evidence\generated`. Copy them into
`docs/` **only after all three report PASS** — an incomplete aggregate is correctly a
failure, and a recorded failure is not overwritten by a later pass.

Then close the schema freeze and stop the pilot project, both ordinary commits and one
command:

```powershell
docker compose --env-file C:\Users\jeehoon\ontology-pilot\secrets\pilot-runtime.env -f docker-compose.yml -f docker-compose.pilot-source.local.yml -p ontology_pilot_source down
```

## Starting another one

Generate new secrets — a 32+ character `PILOT_RECOVERY_TOKEN` identical on the source and
recovery APIs, and a separate 32+ character `PILOT_BACKUP_INTEGRITY_KEY` that authenticates
backup manifests without ever being written into them. Point `PILOT_EVIDENCE_ROOT` at a
**fresh** directory; `start` refuses to reopen a root that already holds a manifest, on
purpose, so two windows can never pool their samples.

Then, in order: open the freeze at the current head, bring up the source project and the
observer, run `preflight`, and only then `start`. Preflight is the step that catches a
week-long mistake in one minute — including the mistake that costs the most, a recovery
token exported into the shell but never into the API container, which disables the whole
protocol and fails every RPO mark for seven days while looking fine from outside.

Do not schedule `tick`. Neither cron nor Task Scheduler can express the 30-second cadence
the contract fixes — both round up to a minute, an unwritten slot is scored as downtime,
and a perfectly healthy deployment then measures about 50% available. Measured: **57.1%**.
The supervisor paces itself; see [`PRODUCTION_PILOT.md`](PRODUCTION_PILOT.md).
