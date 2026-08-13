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

MODULE_ROOT = Path(__file__).resolve().parent
if (MODULE_ROOT.parent / "frontend" / "package.json").exists():
    # Source checkout: this module lives under <repo>/oms while evidence belongs
    # in the repository-level docs directory.
    REPO_ROOT = MODULE_ROOT.parent
    VERSIONS = REPO_ROOT / "oms" / "alembic" / "versions"
else:
    # Production image: the harness and Alembic tree both live under /app.
    REPO_ROOT = MODULE_ROOT
    VERSIONS = MODULE_ROOT / "alembic" / "versions"
DOCS = REPO_ROOT / "docs"


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


def database_head(connectable: Any) -> str:
    """The migration head of the database a harness actually measured.

    `current_head()` above reads the repository's migration files: it reports
    what the code declares, which is not the same claim. A fixture left at an
    older schema, or a DATABASE_URL pointing somewhere stale, produces numbers
    that get stamped with today's head and no way to tell from the file.

    That is not theoretical. The durability rehearsals default to a container
    whose volume sits nine migrations back; the runs on 2026-08-08 reached the
    right database only because an operator passed environment overrides.
    """
    from sqlalchemy import text

    with connectable.connect() as connection:
        head = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
    if not head:
        raise RuntimeError(
            "The measured database has no alembic_version row, so the schema it "
            "was on cannot be established. Migrate it before measuring."
        )
    return str(head)


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
        elif measurements[name] is None:
            # A harness that could not take a reading records None. Comparing it
            # would raise and abort the run before any evidence was written, so
            # the gate would vanish instead of failing. Absent is a breach.
            breaches.append(f"{name} not measured (recorded as null)")
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


def build_evidence_provenance(
    harness: str,
    *,
    observed_head: str | None = None,
    entry_points: List[str] | None = None,
    request_shapes: List[str] | None = None,
) -> Dict[str, Any]:
    """Build the canonical provenance envelope for raw and gate evidence.

    ``observed_head=None`` is intentional for a harness that measures no
    migrated database. It must never be replaced with the repository head by
    implication.
    """
    return {
        "migration_head": current_head(),
        "observed_migration_head": observed_head,
        "git_commit": _git_commit(),
        "captured_at": int(time.time()),
        "harness": harness,
        "entry_points": list(entry_points or []),
        "request_shapes": list(request_shapes or []),
        "host": {
            "platform": platform.system().lower(),
            "release": platform.release(),
            "cpu_count": os.cpu_count(),
        },
    }


def write_evidence(
    gate_id: str,
    *,
    thresholds: Dict[str, Any],
    measurements: Dict[str, Any],
    harness: str,
    entry_points: List[str] | None = None,
    request_shapes: List[str] | None = None,
    observed_head: str | None = None,
    notes: str = "",
    output_dir: Path | None = None,
    supersede: bool = False,
) -> Tuple[Path, str, List[str]]:
    """Write tier-b-<gate_id>-evidence.json and return (path, status, breaches).

    status is PASS only when every threshold is satisfied. A harness cannot
    record PASS by asserting it; the verdict is derived from the numbers.

    `entry_points` and `request_shapes` are condition B7 and the third standing
    invariant: a measurement is evidence only for the path it traverses. The
    ontology-scale gate posted realistic filtered queries to a real endpoint for
    months and still missed a defect that made the Object Explorer allocate
    21.9 GB, because `/api/v1/objects/query` and `/object-explorer/query` are
    two different implementations of a typed read and the gate only ever
    exercised the first. Naming the routes a run actually called is what makes
    that visible in the file rather than discoverable by reading the harness.

    output_dir exists so tests can exercise emission without writing into
    docs/. Gate evidence must come from a real run, and a test writing a file
    the auditor would count is indistinguishable from evidence until someone
    reads the provenance.
    """
    head = current_head()
    if observed_head is not None and observed_head != head:
        # Refused rather than recorded as a breach: a breach is a measurement
        # that failed, and this is a measurement whose subject is unknown. There
        # is no threshold to fail, because nothing here says what was measured.
        raise RuntimeError(
            f"{harness} measured a database at {observed_head!r} while the repository "
            f"declares {head!r}. Writing this would stamp a schema the run never "
            "touched. Migrate the fixture, or measure the database that matches."
        )
    breaches = compare(thresholds, measurements)
    status = "PASS" if not breaches else "FAIL"
    payload = {
        "gate_id": gate_id,
        "goal": "GOAL_2026-08-03",
        "tier": "B",
        "status": status,
        "thresholds": thresholds,
        "measurements": measurements,
        "provenance": build_evidence_provenance(
            harness,
            observed_head=observed_head,
            entry_points=entry_points,
            request_shapes=request_shapes,
        ),
    }
    if breaches:
        payload["breaches"] = breaches
    if notes:
        payload["notes"] = notes

    destination = DOCS if output_dir is None else Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / f"tier-b-{gate_id.replace('_', '-')}-evidence.json"

    # A gate that passes only after repeated attempts has not passed. The
    # measurement contract says so, and nothing enforced it: every harness
    # rewrites its evidence file on every run, so re-running after a failure
    # silently replaced the failure with the latest result. That is not a
    # hypothetical -- a diagnostic run of the collaboration harness overwrote a
    # recorded FAIL with a PASS while merely sampling the distribution.
    #
    # A recorded failure at the same head therefore stands. The later attempt is
    # kept alongside it so the record shows what happened, and the caller still
    # sees FAIL. Promoting a gate requires supersede=True, which is a deliberate
    # statement that the cause was fixed rather than out-waited.
    if not supersede and path.exists():
        try:
            previous = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            previous = None
        if (
            isinstance(previous, dict)
            and previous.get("status") == "FAIL"
            and status == "PASS"
            and (previous.get("provenance") or {}).get("migration_head")
            == payload["provenance"]["migration_head"]
        ):
            attempts = list(previous.get("later_passing_attempts") or [])
            attempts.append({
                "captured_at": payload["provenance"]["captured_at"],
                "measurements": measurements,
            })
            previous["later_passing_attempts"] = attempts
            previous["note_on_later_attempts"] = (
                "This gate failed at this head and later runs passed. The failure "
                "stands: a gate that passes only after repeated attempts has not "
                "passed. Re-emit with supersede=True once the cause is fixed."
            )
            path.write_text(json.dumps(previous, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            return path, "FAIL", list(previous.get("breaches") or [])

    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path, status, breaches
