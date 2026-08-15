"""Ratchet: every latency gate takes the worst of at least six observations.

The rule was in the contract from the beginning and in no harness. It survived
that way because nothing could tell the difference — a gate file records a p95
and says nothing about how many runs produced it, so a worst-of-six and a single
lucky run are the same document.

Wiring the five harnesses fixed the present. This keeps it fixed: a latency gate
whose thresholds do not carry `observations_min`, or whose harness never records
an observation, fails the audit. A sixth latency gate added later fails it too,
until it is wired, which is the case a comment would not have covered.

The check is static. It reads the harness source rather than running it, because
the reference profiles take hours and a ratchet nobody can afford to run is not
a ratchet.

  python oms/audit_latency_observations.py
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from latency_observations import LATENCY_GATES, REQUIRED_OBSERVATIONS  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
OMS = REPO_ROOT / "oms"
DOCS = REPO_ROOT / "docs"

# Latency bounds live on these suffixes. Used only to explain a finding -- the
# gate list above is what decides, because several gates carry a `_seconds_max`
# bound and are not latency gates.
LATENCY_SUFFIXES = ("_ms_max", "_seconds_max")


def emissions(path: Path) -> List[Tuple[str, List[str], Optional[int]]]:
    """Every write_evidence call in a file: (gate_id, threshold keys, line)."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return []
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.id if isinstance(node.func, ast.Name) else (
            node.func.attr if isinstance(node.func, ast.Attribute) else None)
        if name != "write_evidence" or not node.args:
            continue
        first = node.args[0]
        if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
            continue
        keys: List[str] = []
        for keyword in node.keywords:
            if keyword.arg == "thresholds" and isinstance(keyword.value, ast.Dict):
                keys = [item.value for item in keyword.value.keys
                        if isinstance(item, ast.Constant) and isinstance(item.value, str)]
        found.append((first.value, keys, getattr(node, "lineno", None)))
    return found


def records_observations(path: Path) -> bool:
    """The harness must actually record, not merely declare the threshold."""
    source = path.read_text(encoding="utf-8", errors="replace")
    return "observed_worst(" in source


def survey(root: Optional[Path] = None) -> Tuple[Dict[str, dict], List[str]]:
    """What each latency gate's harness does, and what is wrong with it.

    `root` is a parameter so the negative case is testable: an audit that has
    only ever been run against a passing tree is an assertion about one tree.
    """
    seen: Dict[str, dict] = {}
    for path in sorted((root or OMS).glob("*.py")):
        if path.name.startswith("test_") or path.name.startswith("audit_"):
            continue
        for gate, keys, line in emissions(path):
            if gate not in LATENCY_GATES:
                continue
            seen[gate] = {
                "harness": f"oms/{path.name}",
                "line": line,
                "declares_observations": "observations_min" in keys,
                "records_observations": records_observations(path),
                "latency_thresholds": [key for key in keys
                                       if key.endswith(LATENCY_SUFFIXES)],
            }
    failures = []
    for gate in LATENCY_GATES:
        entry = seen.get(gate)
        if entry is None:
            failures.append(f"{gate}: no harness emits this gate")
            continue
        if not entry["declares_observations"]:
            failures.append(
                f"{gate}: {entry['harness']} declares "
                f"{len(entry['latency_thresholds'])} latency threshold(s) and no "
                "observations_min"
            )
        if not entry["records_observations"]:
            failures.append(
                f"{gate}: {entry['harness']} never calls observed_worst, so its "
                "reading is one run's"
            )
    return seen, failures


def evidence_observations() -> List[Tuple[str, Optional[int]]]:
    """How many observations each emitted latency gate file was judged on.

    Reported, never gated. Evidence written before the rule was implemented
    carries no count, and failing on that would gate on history rather than on
    the next run -- the ratchet is that new evidence carries it, not that old
    evidence is deleted.
    """
    rows = []
    for gate in LATENCY_GATES:
        path = DOCS / f"tier-b-{gate.replace('_', '-')}-evidence.json"
        if not path.exists():
            rows.append((gate, None))
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            rows.append((gate, None))
            continue
        value = (payload.get("measurements") or {}).get("observations")
        rows.append((gate, value if isinstance(value, int) else None))
    return rows


def main() -> int:
    seen, failures = survey()
    print(f"Latency observation wiring ({REQUIRED_OBSERVATIONS} required per gate)\n")
    width = max(len(gate) for gate in LATENCY_GATES)
    for gate in LATENCY_GATES:
        entry = seen.get(gate)
        if entry is None:
            print(f"  MISSING  {gate.ljust(width)}  no harness emits this gate")
            continue
        wired = entry["declares_observations"] and entry["records_observations"]
        print(f"  {'ok' if wired else 'UNWIRED':<8} {gate.ljust(width)}  "
              f"{entry['harness']}, {len(entry['latency_thresholds'])} latency threshold(s)")

    print("\nEmitted evidence, by observations recorded (reported, not gated):")
    for gate, count in evidence_observations():
        state = "no evidence file" if count is None and not (
            DOCS / f"tier-b-{gate.replace('_', '-')}-evidence.json").exists() else (
            f"{count} observations" if count is not None
            else "predates the rule; carries no count")
        print(f"    {gate.ljust(width)}  {state}")

    if failures:
        print(f"\n{len(failures)} latency gate(s) not wired:")
        for failure in failures:
            print(f"  {failure}")
        return 1
    print(f"\nAll {len(LATENCY_GATES)} latency gates record observations and gate on them.")
    return 0


if __name__ == "__main__":
    from enforcement_runs import recording

    raise SystemExit(recording("audit_latency_observations", main))
