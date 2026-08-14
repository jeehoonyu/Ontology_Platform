# The Pilot Window

The last three Tier B gates — availability, RPO and RTO — need one thing this repository
cannot supply: **seven consecutive days of a machine that stays up**.

**A window is open.** It started `2026-08-14T00:34Z` and closes `2026-08-21T00:34Z`, at
head `0042_stream_outer_joins`, on the development workstation. `docs/SCHEMA_FREEZE.json`
is open for the duration; a migration merged before it closes fails the build rather than
silently voiding seven days of collection.

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
- **Losing the supervisor.** It is a host process. It survives this terminal closing; it
  does **not** survive a logoff or reboot on this machine, because registering a scheduled
  task is denied to this account — `Register-ScheduledTask` and `schtasks /Create` both
  answer "Access is denied", elevated or not. After any restart, bring it back with:

  ```powershell
  Start-Process python -WindowStyle Hidden -WorkingDirectory C:\Users\jeehoon\.vscode\Ontology_Platform -RedirectStandardOutput C:\Users\jeehoon\ontology-pilot\supervisor.log -ArgumentList 'oms\pilot_window.py','--evidence-root','C:\Users\jeehoon\ontology-pilot\evidence','--environment-file','C:\Users\jeehoon\ontology-pilot\secrets\pilot-runtime.env','--token-file','C:\Users\jeehoon\ontology-pilot\secrets\pilot-recovery-token','run'
  ```

  On a host where task registration is permitted, `scripts/register-pilot-window.ps1` does
  this durably; it now registers a **logon** trigger as well as a boot trigger, because a
  task owned by an interactive account never fires at boot and the boot trigger alone would
  have quietly left no supervisor running.
- **Docker not coming back.** The observer restarts with Docker Desktop, which is set to
  start at logon here. If it does not, every 30-second slot it misses is scored as
  unavailable.

Losing minutes is survivable; losing the observer for a quarter of an hour is not.

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
