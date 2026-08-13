# Reproducing a Measurement

Condition D5 of [`GOAL_REPRODUCIBILITY_2026-08-13.md`](GOAL_REPRODUCIBILITY_2026-08-13.md).

Tier B asks for evidence "reproducible by someone who did not author it". This is the path
that person follows. It is the same path that reproduced the pipeline-scale gate on
2026-08-13, and it is executable rather than described:

```bash
./scripts/reproduce-measurement.sh
```

It takes about ten minutes, most of it installing packages and generating ten million rows.
Pass a directory to keep the workspace somewhere you choose.

## What it does, and why each step is there

| Step | Why |
| --- | --- |
| 1. fresh `git clone` | nothing in a working tree can leak into the result |
| 2. isolated virtualenv | this project's own evidence was produced in a *shared global* interpreter carrying 101 packages, including ones belonging to unrelated projects |
| 3. install from `oms/requirements.lock` | **not** `requirements.txt` — see below |
| 4. compare closure digest | confirms the rebuilt environment is the one the lock describes |
| 5. run the gate | inside the clone, so committed evidence is never touched |
| 6. **check the file changed** | a crashed run leaves the committed file untouched, and comparing it to itself agrees perfectly |
| 7. compare | structure must match exactly; timings will not |

Step 3 is not a style preference. Pinning the seventeen declared dependencies still allowed
**11 of 42** transitive packages to resolve differently — `starlette` 1.2.1 against 1.6.0
among them — and the resulting interpreter **could not import the test suite at all**,
because starlette 1.6.0 requires `httpx2` where 1.2.1 requires `httpx`. Install from the
lock.

Step 6 exists because the mistake was made. On 2026-08-13 a reproduction was reported as
succeeding, with measurements matching to the last decimal. The run had crashed at import,
the evidence file was never rewritten, and the comparison was the committed file against
itself. **A reproduction that silently no-ops produces perfect agreement**, which is exactly
what a careless reader hopes to see. The script exits non-zero rather than printing that
table.

## What should and should not reproduce

Two runs on the same machine with a byte-identical dependency closure:

| | recorded | run A | run B |
| --- | ---: | ---: | ---: |
| `input_rows` | 10,000,000 | exact | exact |
| `output_partitions` | 20 | exact | exact |
| `complex_union_rows` | 20,000,000 | exact | exact |
| `geofence_total_positions` | 9,218 | exact | exact |
| `preview_p95_ms` | 1,459.595 | +17.7% | +24.5% |
| `deliver_ms` | 1,515.835 | +33.0% | +31.8% |

**Structure reproduces to the digit. Timing does not**, by roughly a fifth to a third — and
that is a floor, measured on one machine with one closure. Different hardware will be
worse.

So a differing latency is not by itself a finding, and a **differing verdict is**. The
script fails when the verdicts disagree and merely prints the deltas when they do not.

It also means a latency threshold set within about a third of a measured value cannot
distinguish a regression from the same run twice. Thresholds belong against the observed
spread, not against a single reading.

## Which gate this reproduces

`pipeline_scale`, because it is the only Tier B gate that needs no external
infrastructure — it drives DuckDB over a throwaway SQLite database.

The others need PostgreSQL, a Kafka broker, an object store, or an OCI sandbox. Each is
declared in `oms/check_registry.py` with what it requires and how often it should run, and
reproducing one means provisioning that first. `oms/audit_check_coverage.py` lists them.

## Checking the evidence you already have

`oms/audit_dependency_provenance.py` reports, for every evidence file, whether the
dependency set that produced it is the one installed now:

- **CURRENT** — the recorded closure digest matches
- **DRIFTED** — it ran against a different set, and the packages that moved are named
- **UNRECORDED** — produced before this was recorded at all

Drift is reported and never gated. Upgrading a dependency is ordinary work; what the report
gives you is the ability to ask, when a number moves, whether the library changed or the
code did.
