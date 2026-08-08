"""Emit the Tier B identity gate from an OIDC scale run.

The measurements come from a browser: `frontend/tests/production/oidc-scale.spec.ts`
drives 200 distinct PKCE logins against two replicas and writes what it observed
to the path in OIDC_SCALE_EVIDENCE_PATH. That file is raw measurement, not a
verdict, and this turns it into gate evidence.

It exists because until 2026-08-08 nothing did. `tier-b-identity-evidence.json`
carried a well-formed envelope, named this spec and the provisioner in its
`harness` field, and had counted as a passing gate since head 0038 -- with no
code anywhere producing it. It was written by hand, which satisfies every check
the auditor performs while proving only that someone typed numbers that pass.

Two things this deliberately does not do:

  It ignores the spec's own `status` field. The spec sets "PASS" as a literal
  before any threshold is consulted, and a harness that records its own verdict
  is the arrangement the envelope exists to prevent. The status here is derived
  from the numbers by `write_evidence`.

  It refuses to emit on a partial run rather than filling gaps with defaults.
  A missing `mutation_denials` defaulted to zero would breach loudly, but a
  missing `login_p95_ms` defaulted to zero would pass silently, and no rule that
  depends on which key went missing is worth trusting.

  python oms/identity_scale_evidence.py --run docs/oidc-scale-run.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

REPO_ROOT = Path(__file__).resolve().parent.parent

LOGIN_P95_LIMIT_MS = 15_000.0
REQUIRED_IDENTITIES = 200
REQUIRED_REPLICAS = 2

# Every measurement the gate judges. Absent any one of them, there is no run to
# report on.
REQUIRED_KEYS = (
    "identities",
    "unique_principals",
    "mutation_denials",
    "replicas_verified",
    "login_p95_ms",
)


def _replica_count(value: Any) -> int:
    """The spec records which replicas it verified; the gate counts them.

    It writes a list of replica URLs. Converting that to a number is exactly the
    kind of step that, done by hand into a hand-written evidence file, is where
    a 2 appears without two replicas behind it.
    """
    if isinstance(value, (list, tuple, set)):
        return len({str(item) for item in value})
    if isinstance(value, bool):
        raise ValueError("replicas_verified must be a list or a count, not a boolean")
    if isinstance(value, int):
        return value
    raise ValueError(f"replicas_verified is neither a list nor a count: {value!r}")


def measurements_from_run(run: Dict[str, Any]) -> Dict[str, Any]:
    absent = [key for key in REQUIRED_KEYS if run.get(key) is None]
    if absent:
        raise SystemExit(
            "The OIDC scale run is missing " + ", ".join(absent) + ". "
            "No evidence is written for a partial run: a gap filled with a default "
            "is indistinguishable from a measurement once it is in the file."
        )
    measurements = {
        "identities": int(run["identities"]),
        "unique_principals": int(run["unique_principals"]),
        "mutation_denials": int(run["mutation_denials"]),
        "replicas_verified": _replica_count(run["replicas_verified"]),
        "login_p95_ms": float(run["login_p95_ms"]),
    }
    for optional in ("login_p50_ms", "concurrency", "elapsed_seconds", "authorization_flow"):
        if run.get(optional) is not None:
            measurements[optional] = run[optional]
    return measurements


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--run", default=os.environ.get("OIDC_SCALE_EVIDENCE_PATH"),
        help="the JSON the oidc-scale Playwright profile wrote")
    args = parser.parse_args()

    if not args.run:
        raise SystemExit(
            "Pass --run, or set OIDC_SCALE_EVIDENCE_PATH to the file the oidc-scale "
            "Playwright profile wrote. This does not invent a run."
        )
    path = Path(args.run)
    if not path.exists():
        raise SystemExit(f"No OIDC scale run at {path}. Run the oidc-scale profile first.")

    run = json.loads(path.read_text(encoding="utf-8"))
    measurements = measurements_from_run(run)
    print(json.dumps(measurements, indent=2, sort_keys=True))

    from tier_b_evidence import write_evidence

    gate_path, status, breaches = write_evidence(
        "identity",
        thresholds={
            "identities_min": REQUIRED_IDENTITIES,
            "unique_principals_min": REQUIRED_IDENTITIES,
            "mutation_denials_min": REQUIRED_IDENTITIES,
            "replicas_verified_min": REQUIRED_REPLICAS,
            "login_p95_ms_max": LOGIN_P95_LIMIT_MS,
        },
        measurements=measurements,
        harness="oms/identity_scale_evidence.py",
        entry_points=[
            "authorization_code_pkce against Keycloak, via frontend/tests/production/oidc-scale.spec.ts",
            "two independently addressed API replicas",
        ],
        request_shapes=[
            "200 distinct PKCE logins",
            "server-side mutation denial per authenticated viewer",
        ],
        notes=(
            f"Derived from the oidc-scale run at {path.name}. The run's own "
            f"'status' field is ignored; the verdict comes from the thresholds."
        ),
    )
    print(f"\nTier B evidence {status}: {gate_path.name}")
    for breach in breaches:
        print(f"  breach: {breach}")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
