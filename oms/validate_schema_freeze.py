"""Fail the build when a migration lands during an open pilot window.

The availability, RPO, and RTO gates each need seven consecutive days at one
migration head. `pilot_window.py tick` enforces that at collection time, but only
destructively: the head changes, the window is void, and the seven days are
spent. By then the migration is merged and the only remedy is another week.

This moves the enforcement to the point where it is still cheap. While
`docs/SCHEMA_FREEZE.json` declares an open freeze, a head other than the frozen
one fails CI, so the pull request that would have voided the window is the thing
that goes red instead.

A freeze is an ordinary commit and lifting one is an ordinary commit. That is the
point: ending it early is a reviewable act with an author and a date, rather than
a migration that quietly wins a race against a measurement nobody was watching.

  python oms/validate_schema_freeze.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
FREEZE_FILE = REPO_ROOT / "docs" / "SCHEMA_FREEZE.json"

REQUIRED_KEYS = ("state", "head", "opened_at", "expires_at", "reason", "owner")
OPEN_STATES = ("open",)


def load_freeze(path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    path = path or FREEZE_FILE
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise SystemExit(f"{path} is not valid JSON: {error}")
    if not isinstance(payload, dict):
        raise SystemExit(f"{path} must contain an object")
    missing = [key for key in REQUIRED_KEYS if not payload.get(key)]
    if missing:
        # A freeze missing its own metadata is not a freeze anyone can act on:
        # there is nobody to ask and no date it ends.
        raise SystemExit(f"{path} is missing {', '.join(missing)}")
    return payload


def evaluate(freeze: Optional[Dict[str, Any]], head: str, now: int) -> tuple[int, str]:
    if freeze is None:
        return 0, "No schema freeze declared; migrations may land freely."
    state = str(freeze["state"]).lower()
    if state not in OPEN_STATES:
        return 0, f"Schema freeze is {state}; migrations may land freely."
    expires = int(freeze["expires_at"])
    if now >= expires:
        # Expiry is reported, never enforced silently. A window that ran its
        # course should be closed by a commit, not by the clock, so that the
        # evidence and the freeze that protected it agree about when it ended.
        return 1, (
            f"Schema freeze at {freeze['head']} expired {(now - expires) // 3600}h ago "
            f"({freeze['owner']}). Close it in {FREEZE_FILE.name} -- aggregate the "
            "window first if it completed."
        )
    if head != freeze["head"]:
        return 1, (
            f"Schema freeze is OPEN at {freeze['head']} and the head is now {head}.\n"
            f"  reason:  {freeze['reason']}\n"
            f"  owner:   {freeze['owner']}\n"
            f"  ends in: {(expires - now) // 3600}h\n"
            "A pilot window is collecting seven days of evidence at the frozen head. "
            "This migration voids it. Land it after the freeze closes, or close the "
            "freeze deliberately and restart the window."
        )
    remaining = (expires - now) // 3600
    return 0, (
        f"Schema freeze OPEN at {head}, {remaining}h remaining ({freeze['owner']}): "
        f"{freeze['reason']}"
    )


def main() -> int:
    import time

    from tier_b_evidence import current_head

    code, message = evaluate(load_freeze(), current_head(), int(time.time()))
    print(message)
    return code


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from enforcement_runs import recording  # noqa: E402
    sys.exit(recording("validate_schema_freeze", main))