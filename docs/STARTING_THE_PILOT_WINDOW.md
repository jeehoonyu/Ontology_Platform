# Starting the Pilot Window

The last three Tier B gates — availability, RPO and RTO — need one thing this repository
cannot supply: **seven consecutive days of a machine that stays up**. Everything else is
built, tested, and verified to pass preflight.

On 2026-08-13 the full configuration was exercised on a development host and
`pilot_window.py preflight` reported **10 of 10**. The clock was deliberately not started.
This is what that verification established, so nobody has to rediscover it.

## What the seven days actually cost

Read this before starting, because the commitment is larger than the command.

- **7 consecutive days.** `docs/TIER_B_MEASUREMENT_CONTRACT.md` says it outright: *"the
  availability window is 7 days and cannot be compressed. Any plan implying otherwise is
  wrong."* RPO and RTO sample **across** that window, so they cannot be split out and run
  quickly either.
- **10 minutes 5 seconds of total downtime budget.** That is 99.9% of a week. Planned
  restarts count. **Observer loss counts** — the probe backfills every missed 30-second
  slot as unavailable, so the machine being briefly gone is indistinguishable from the
  product being briefly gone, deliberately.
- **No migrations.** A head change voids the window. Reopen the schema freeze first
  (`docs/SCHEMA_FREEZE.json`) so a migration fails CI instead of silently ending the run.
- **A failed run is sticky.** A recorded FAIL at the current head stands until deliberately
  superseded, which is worse than the gate simply being MISSING. Do not start a window you
  expect to lose.

A laptop can satisfy the contract — nothing in it requires a particular host class — but a
10-minute budget is unforgiving. Check that the machine will not sleep (`powercfg /query
SCHEME_CURRENT SUB_SLEEP STANDBYIDLE`), will stay on mains power, and will not take an
unattended update restart. One reboot plus a Docker start is typically 2–5 minutes, so the
budget survives roughly one and not two.

## Before starting

Generate real secrets. The values below are the shape, not the values — the ones used for
the 2026-08-13 verification were obviously-labelled local placeholders and must not be
reused:

| Variable | What it is |
| --- | --- |
| `PILOT_RECOVERY_TOKEN` | bearer token for the internal recovery protocol, 32+ chars, **identical on the source and recovery APIs** |
| `PILOT_BACKUP_INTEGRITY_KEY` | separate 32+ char secret authenticating backup manifests; never written into them |
| `PILOT_EVIDENCE_ROOT` | a protected absolute directory, the same path as `PILOT_EVIDENCE_PATH` in the API's environment |

The remaining `PILOT_SOURCE_*` / `PILOT_RECOVERY_*` settings are in
`deploy/.env.production.example`. The recovery project must be a **different** Compose
project from the source, and the recovery URL a different scheme/host/port/path identity —
preflight refuses otherwise.

## Starting it

```powershell
# 1. Freeze the schema for the duration.
#    Edit docs/SCHEMA_FREEZE.json: state "open", head = current, expires_at = now + 8 days.
python oms/validate_schema_freeze.py

# 2. Start the availability observer. It owns the journal and keeps probing
#    through every recovery rehearsal; the supervisor writes no samples itself.
docker compose --env-file .env.production `
  -f docker-compose.yml -f docker-compose.production.yml `
  --profile pilot-observability up --build -d

# 3. Verify. This is the step that catches a week-long mistake in one minute.
python oms/pilot_window.py preflight `
  --target $env:PILOT_SOURCE_URL `
  --recovery-target $env:PILOT_RECOVERY_URL `
  --recovery-driver postgres-compose

# 4. Open the window, then register the supervisor so it survives a reboot.
python oms/pilot_window.py start `
  --target $env:PILOT_SOURCE_URL `
  --recovery-target $env:PILOT_RECOVERY_URL `
  --project-id operations `
  --recovery-driver postgres-compose

./scripts/register-pilot-window.ps1 `
  -EvidenceRoot $env:PILOT_EVIDENCE_ROOT `
  -TokenFile 'C:\ontology-secrets\pilot-recovery-token' `
  -EnvironmentFile 'C:\ontology-secrets\pilot-runtime.env'
Start-ScheduledTask -TaskName OntologyPilotWindow
```

Do not schedule `tick`. Neither cron nor Task Scheduler can express the 30-second cadence
the contract fixes — both round up to a minute, an unwritten slot is scored as downtime, and
a perfectly healthy deployment then measures about 50% available. Measured: **57.1%**. The
supervisor paces itself; see [`PRODUCTION_PILOT.md`](PRODUCTION_PILOT.md).

## While it runs

```powershell
python oms/pilot_window.py status
```

It reports elapsed hours, probes recorded against probes expected, RPO samples against the
10 required, RTO rehearsals against 4, and whether the observer is still writing. It fails
loudly if the migration head has drifted, because at that point the window is void and
continuing wastes the remaining days.

## Finishing

```powershell
python oms/pilot_window.py aggregate
```

Emits availability, RPO and RTO gate files under `${PILOT_EVIDENCE_ROOT}/generated`. Copy
them into `docs/` **only after all three report PASS** — an incomplete aggregate is
correctly a failure, and a recorded failure is not overwritten by a later pass.

Then close the schema freeze, which is an ordinary commit.
