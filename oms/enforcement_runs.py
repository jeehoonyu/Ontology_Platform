"""Record when each enforcement check ran, so its silence stops reading as success.

Every gate in this repository records what it measured, at which head, and when.
No *check* recorded anything. `audit_evidence_corpus.py` printed "Ratchet held"
and exited 0 with no timestamp, no head, and no memory, so the question "when did
the query-bounds ratchet last hold?" had no answer anywhere.

That is the Tier B envelope's own argument one level up. A gate without
provenance cannot be shown to be stale, so it never expires. A check without
provenance cannot be shown to have stopped running, so its silence is
indistinguishable from its success -- which is exactly what happened here:
GitHub Actions never completed a run on this repository, fourteen attempts over
nineteen days, and nothing noticed because nothing was watching the watchers.

Scope is deliberately the auditors, not the harnesses. `verify_*` and
`benchmark_*` scripts already record their runs -- those records are called
evidence files, and they carry a migration head and a capture time. What had no
record was the code that judges them.

  python oms/audit_enforcement.py
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RUNS = REPO_ROOT / "docs" / "enforcement-runs.json"

# Each check this repository expects to run, and where it is supposed to run.
# A check absent from here is not audited; a check here that has never run is
# reported as NEVER, which is the state this file exists to make visible.
DECLARED: Dict[str, Dict[str, str]] = {
    "audit_evidence_corpus": {
        "purpose": "evidence without a migration head can never be shown stale",
        "runs_in": "suite",
    },
    "audit_extensibility": {
        "purpose": "the next object type must not cost more than the last",
        "runs_in": "suite",
    },
    "audit_query_bounds": {
        "purpose": "no read materializes an object type before filtering it",
        "runs_in": "suite",
    },
    "audit_route_coverage": {
        "purpose": "typed routes stay reachable through /api/v1",
        "runs_in": "suite",
    },
    "validate_docs_conformance": {
        "purpose": "documentation states what the product actually does",
        "runs_in": "suite",
    },
    "validate_schema_freeze": {
        "purpose": "a migration cannot land while a pilot window is collecting",
        "runs_in": "suite",
    },
    "validate_tier_b_evidence": {
        "purpose": "every Tier B gate is current, provenanced and threshold-checked",
        "runs_in": "suite",
    },
    "validate_external_evaluations": {
        "purpose": "external evaluator submissions carry their own provenance",
        "runs_in": "suite",
    },
}

CURRENT, STALE, NEVER = "CURRENT", "STALE", "NEVER"


def _environment() -> str:
    """Where this process is running, as far as it can tell.

    Recorded because "it passes on my machine" and "it passes in CI" are
    different claims, and for nineteen days this repository could only ever have
    made the first one.
    """
    if os.getenv("GITHUB_ACTIONS", "").strip().lower() == "true":
        return "ci"
    return "local"


def load(runs_file: Optional[Path] = None) -> Dict[str, Any]:
    path = Path(runs_file) if runs_file else DEFAULT_RUNS
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        # An unreadable record is not a run. Treating it as one would be the
        # same mistake as trusting an unparseable evidence file.
        return {}
    return payload if isinstance(payload, dict) else {}


def record(check: str, *, verdict: str, head: Optional[str] = None,
           runs_file: Optional[Path] = None, at: Optional[int] = None) -> Dict[str, Any]:
    """Store this check's latest run.

    Latest rather than append-only, deliberately. The chaos and durability
    journals append because each rehearsal is separate evidence; here the
    question is only "when did this last run", and an append-only file would add
    a line to every diff on every local invocation. One entry per check keeps the
    record honest without making it noise.
    """
    if check not in DECLARED:
        raise ValueError(f"undeclared enforcement check {check!r}; add it to DECLARED")
    if head is None:
        from tier_b_evidence import current_head

        head = current_head()
    path = Path(runs_file) if runs_file else DEFAULT_RUNS
    runs = load(path)
    runs[check] = {
        "verdict": verdict,
        "migration_head": head,
        "at": int(time.time()) if at is None else int(at),
        "environment": _environment(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(runs, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return runs[check]


def classify(runs: Dict[str, Any], head: str) -> Dict[str, Dict[str, Any]]:
    """CURRENT, STALE or NEVER for every declared check."""
    report: Dict[str, Dict[str, Any]] = {}
    for check, declaration in sorted(DECLARED.items()):
        entry = runs.get(check)
        if not isinstance(entry, dict) or not entry.get("migration_head"):
            report[check] = {"state": NEVER, "detail": "no run has ever been recorded",
                             **declaration}
            continue
        if entry["migration_head"] != head:
            report[check] = {
                "state": STALE,
                "detail": f"last ran at {entry['migration_head']}",
                "last_run": entry, **declaration,
            }
            continue
        report[check] = {
            "state": CURRENT,
            "detail": f"{entry.get('verdict', '?')} in {entry.get('environment', '?')}",
            "last_run": entry, **declaration,
        }
    return report


def recording(check: str, main: Callable[[], int]) -> int:
    """Run a check's `main` and record that it ran, whatever the outcome.

    Recorded on failure too. Whether the check passed is the verdict; whether it
    ran at all is the thing this file tracks, and a failing check has certainly
    run. Recorded on an exception for the same reason -- a check that crashed is
    a check that executed and needs looking at, not a check that is silently
    absent.
    """
    verdict, code = "ERROR", 1
    try:
        code = int(main() or 0)
        verdict = "PASS" if code == 0 else "FAIL"
        return code
    except SystemExit as exit_request:  # argparse and `raise SystemExit(...)`
        raw = exit_request.code
        code = 0 if raw is None else (raw if isinstance(raw, int) else 1)
        verdict = "PASS" if code == 0 else "FAIL"
        raise
    finally:
        try:
            record(check, verdict=verdict)
        except Exception as error:  # never let bookkeeping mask the check itself
            print(f"[enforcement-runs] could not record {check}: {error}")
