"""Take the worst of at least six latency observations, mechanically.

The measurement contract says:

    Latency gates are measured on an otherwise idle host, and the reading is
    the worst of at least six observations.

Nothing implemented it. Every latency harness recorded one run's p95, the
evidence envelope had no field for how many observations produced the number,
and the "worst of six" quoted in `GOAL_TIER_B_2026-08-03.md` was a person
running a script six times and reporting the slowest. An auditor reading a gate
file could not tell that from a single lucky run, because the file did not say.

The rule exists because of a specific wrong diagnosis. The collaboration gate
was recorded as breaching and the cause was read as its p95 window; six runs on
a quiet host then spread 6.791 ms, and the three observations that had produced
the breach turned out to have been taken while the machine was building images
and running suites. A latency threshold with no stated quiescence condition
measures the machine's mood as much as the system.

This is the same arrangement `durability_rehearsals.py` and `chaos_rehearsals.py`
already use, reused rather than reinvented: each run appends one observation,
the gate is derived from the union at the current head, and no single run can
decide the verdict.

Two halves of the rule, and they are not equally enforceable:

  * **worst of at least six** is now a threshold. `observations_min` sits in the
    gate file beside the reading it qualifies.
  * **on an otherwise idle host** is *reported*, not gated. Nothing portable
    tells a Python process whether the machine beside it is busy, and gating on
    spread would fail a system that is legitimately variable. So every
    observation is kept and the spread is published: a wide spread is the
    signature of a noisy host, which is exactly what the earlier misdiagnosis
    looked like, and now it is visible in the file instead of discoverable by
    re-running.

  python oms/latency_observations.py status
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OBSERVATIONS = REPO_ROOT / "docs" / "latency-observations.jsonl"

REQUIRED_OBSERVATIONS = 6

# Named rather than inferred. Several gates carry a `_seconds_max` threshold and
# are not latency gates: RPO measures a data-loss interval, RTO a recovery, and
# durability and chaos measure recovery work. Each of those already takes the
# worst across a stated minimum number of rehearsals or samples spread over a
# window, which is this rule by another route. What distinguishes the five below
# is that a single run used to decide the number.
LATENCY_GATES = (
    "collaboration",
    "identity",
    "mixed_workload",
    "ontology_scale",
    "pipeline_scale",
)


def record(
    gate: str,
    readings: Dict[str, float],
    harness: str,
    *,
    observed_head: Optional[str] = None,
    observations_file: Optional[Path] = None,
) -> Dict[str, Any]:
    """Append one observation. Every run contributes; none decides.

    `observed_head` is `alembic_version` read from the database the run actually
    measured, where the harness can read one. It is optional because not every
    latency gate measures a database directly -- identity measures a browser run
    against two replicas -- but when it is given it is checked, and when it is
    absent the row says so rather than implying a check that did not happen.
    """
    if gate not in LATENCY_GATES:
        raise ValueError(f"unknown latency gate {gate!r}; expected one of {LATENCY_GATES}")
    numeric = {key: float(value) for key, value in readings.items()
               if isinstance(value, (int, float))}
    if not numeric:
        raise ValueError(f"{harness} recorded no numeric latency reading for {gate!r}")

    from tier_b_evidence import current_head

    head = current_head()
    if observed_head is not None and observed_head != head:
        raise ValueError(
            f"This run measured a database at {observed_head!r} while the repository "
            f"declares {head!r}. Recording it would pool two schemas into one reading."
        )
    path = Path(observations_file) if observations_file else DEFAULT_OBSERVATIONS
    entry = {
        "gate": gate,
        "at": int(time.time()),
        "harness": harness,
        "migration_head": head,
        "observed_migration_head": observed_head,
        "readings": numeric,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")
    return entry


def load(observations_file: Path) -> List[Dict[str, Any]]:
    if not observations_file.exists():
        return []
    rows = []
    for line in observations_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def at_head(rows: List[Dict[str, Any]], gate: str, head: str) -> List[Dict[str, Any]]:
    """This gate's observations at this head, and only those.

    An observation that named the database it measured must have named this
    head; one that could not name a database is kept on the repository head
    alone. Pooling readings across schemas would let a fast measurement of an
    old schema qualify a new one.
    """
    return [
        row for row in rows
        if row.get("gate") == gate
        and row.get("migration_head") == head
        and row.get("observed_migration_head") in (None, head)
        and isinstance(row.get("readings"), dict)
    ]


def summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The worst of each reading, never the mean, plus what the spread says.

    A mean lets one quiet run bury one taken while the machine was busy, which
    is the direction that hides a breach. The distribution is published whole so
    the reverse case -- a single noisy observation condemning a healthy system --
    is arguable from the file rather than only from someone's memory of the run.
    """
    keys = sorted({key for row in rows for key in row.get("readings", {})})
    worst: Dict[str, float] = {}
    spread: Dict[str, float] = {}
    distribution: Dict[str, List[float]] = {}
    for key in keys:
        values = sorted(float(row["readings"][key]) for row in rows if key in row["readings"])
        if not values:
            continue
        worst[key] = round(values[-1], 3)
        spread[key] = round(values[-1] - values[0], 3)
        distribution[key] = [round(value, 3) for value in values]
    return {
        "observations": len(rows),
        "worst": worst,
        "observation_spread": spread,
        "observation_distributions": distribution,
        "observed_by": sorted({row.get("harness") for row in rows if row.get("harness")}),
    }


def observed_worst(
    gate: str,
    readings: Dict[str, float],
    harness: str,
    *,
    observed_head: Optional[str] = None,
    observations_file: Optional[Path] = None,
) -> Tuple[Dict[str, Any], int]:
    """Record this run, then return (measurements, count) for the whole set.

    The returned measurements carry the *worst* value seen for each reading at
    this head, so a harness merges them over its own single-run numbers rather
    than reporting what it happened to see this time.
    """
    record(gate, readings, harness,
           observed_head=observed_head, observations_file=observations_file)
    path = Path(observations_file) if observations_file else DEFAULT_OBSERVATIONS

    from tier_b_evidence import current_head

    rows = at_head(load(path), gate, current_head())
    summary = summarize(rows)
    measurements = dict(summary["worst"])
    measurements["observations"] = summary["observations"]
    measurements["observation_spread"] = summary["observation_spread"]
    measurements["observation_distributions"] = summary["observation_distributions"]
    return measurements, summary["observations"]


def shortfall(count: int) -> str:
    """Why a gate is not being emitted yet, in the words an operator needs.

    Emitting below the required count would be worse than not emitting. A gate
    short of its observations fails its own threshold, a recorded FAIL at the
    same head is sticky by design, and the sixth run could then not promote it
    without an explicit supersede. Five honest runs would lock the gate they
    were accumulating toward.
    """
    return (
        f"{count} of {REQUIRED_OBSERVATIONS} observations recorded at this head. "
        f"Run the harness {REQUIRED_OBSERVATIONS - count} more time(s) on an idle "
        "host; the gate is emitted from the worst of the set, and is deliberately "
        "not written before then."
    )


def status(observations_file: Optional[Path] = None) -> int:
    from tier_b_evidence import current_head

    path = Path(observations_file) if observations_file else DEFAULT_OBSERVATIONS
    head = current_head()
    rows = load(path)
    print(f"Latency observations at {head}\n")
    ready = 0
    for gate in LATENCY_GATES:
        current = at_head(rows, gate, head)
        summary = summarize(current)
        count = summary["observations"]
        ready += 1 if count >= REQUIRED_OBSERVATIONS else 0
        mark = "ready" if count >= REQUIRED_OBSERVATIONS else "short"
        widest = max(summary["observation_spread"].values(), default=0.0)
        print(f"  {mark:<6} {gate:<16} {count} of {REQUIRED_OBSERVATIONS}"
              + (f", widest spread {widest}" if count else ""))
    print(f"\n{ready} of {len(LATENCY_GATES)} latency gates have enough observations.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("status",))
    parser.add_argument("--observations-file", default=None)
    args = parser.parse_args()
    path = Path(args.observations_file) if args.observations_file else None
    return status(path)


if __name__ == "__main__":
    raise SystemExit(main())
