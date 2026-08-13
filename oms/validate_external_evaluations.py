"""Validate independent external Connect-to-Report evidence bundles."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluator_evidence import load_bundles, validate_corpus


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path, help="Evaluator bundle JSON files")
    parser.add_argument("--directory", type=Path, default=Path("docs/external-evaluations"))
    parser.add_argument("--minimum-teams", type=int, default=2)
    parser.add_argument("--allow-incomplete", action="store_true", help="Report missing evidence without failing")
    args = parser.parse_args()
    paths = args.paths or sorted(args.directory.glob("*.json"))
    try:
        bundles = load_bundles(paths)
        summary, errors = validate_corpus(bundles, minimum_teams=max(2, args.minimum_teams))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, indent=2, sort_keys=True))
        return 0 if args.allow_incomplete else 1
    print(json.dumps({**summary, "errors": errors, "files": [str(path) for path in paths]}, indent=2, sort_keys=True))
    return 0 if not errors or args.allow_incomplete else 1


if __name__ == "__main__":
    from enforcement_runs import recording  # noqa: E402
    raise SystemExit(recording("validate_external_evaluations", main))