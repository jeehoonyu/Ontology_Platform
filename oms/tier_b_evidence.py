"""Emit Tier B gate evidence in the shape docs/TIER_B_MEASUREMENT_CONTRACT.md fixes.

Harnesses call write_evidence() instead of hand-assembling a payload, so every
gate records the same envelope: the thresholds it was judged against, the
measurements, and the provenance needed to tell later whether it went stale.

compare() lives here rather than in the validator so the harness that writes a
verdict and the auditor that reads it cannot disagree about what a threshold
means.
"""
from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS = REPO_ROOT / "docs"
VERSIONS = REPO_ROOT / "oms" / "alembic" / "versions"


def current_head() -> str:
    """The revision no other migration declares as its down_revision."""
    revisions, parents = set(), set()
    for path in VERSIONS.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        found = re.search(r'^revision(?::\s*[^=]+)?\s*=\s*"([^"]+)"', text, re.MULTILINE)
        parent = re.search(r'^down_revision(?::\s*[^=]+)?\s*=\s*"([^"]+)"', text, re.MULTILINE)
        if found:
            revisions.add(found.group(1))
        if parent:
            parents.add(parent.group(1))
    heads = revisions - parents
    if len(heads) != 1:
        raise RuntimeError(f"expected exactly one migration head, found {sorted(heads)}")
    return heads.pop()


def compare(thresholds: Dict[str, Any], measurements: Dict[str, Any]) -> List[str]:
    """Return one message per threshold the measurements do not satisfy.

    Threshold keys carry their direction as a suffix so neither the harness nor
    the auditor has to infer it from the gate name.
    """
    breaches: List[str] = []
    for key, limit in sorted(thresholds.items()):
        if key.endswith("_max"):
            name = key[:-4]
            ok = lambda value, bound: value <= bound  # noqa: E731
        elif key.endswith("_min"):
            name = key[:-4]
            ok = lambda value, bound: value >= bound  # noqa: E731
        else:
            breaches.append(f"{key} has no _max/_min direction")
            continue
        if name not in measurements:
            breaches.append(f"{name} not measured")
        elif not ok(measurements[name], limit):
            breaches.append(f"{name}={measurements[name]} vs {key}={limit}")
    return breaches


def _git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=15, check=False,
        )
        return result.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def write_evidence(
    gate_id: str,
    *,
    thresholds: Dict[str, Any],
    measurements: Dict[str, Any],
    harness: str,
    notes: str = "",
    output_dir: Path | None = None,
) -> Tuple[Path, str, List[str]]:
    """Write tier-b-<gate_id>-evidence.json and return (path, status, breaches).

    status is PASS only when every threshold is satisfied. A harness cannot
    record PASS by asserting it; the verdict is derived from the numbers.

    output_dir exists so tests can exercise emission without writing into
    docs/. Gate evidence must come from a real run, and a test writing a file
    the auditor would count is indistinguishable from evidence until someone
    reads the provenance.
    """
    breaches = compare(thresholds, measurements)
    status = "PASS" if not breaches else "FAIL"
    payload = {
        "gate_id": gate_id,
        "goal": "GOAL_2026-08-03",
        "tier": "B",
        "status": status,
        "thresholds": thresholds,
        "measurements": measurements,
        "provenance": {
            "migration_head": current_head(),
            "git_commit": _git_commit(),
            "captured_at": int(time.time()),
            "harness": harness,
            "host": {
                "platform": platform.system().lower(),
                "release": platform.release(),
                "cpu_count": os.cpu_count(),
            },
        },
    }
    if breaches:
        payload["breaches"] = breaches
    if notes:
        payload["notes"] = notes

    destination = DOCS if output_dir is None else Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / f"tier-b-{gate_id.replace('_', '-')}-evidence.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path, status, breaches
