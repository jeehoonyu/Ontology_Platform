"""
Summarize the docs-grounded validation matrix.

This helper intentionally checks the evidence artifact, not product runtime
behavior. Runtime behavior is covered by test_docs_conformance.py.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import sys


VALID_STATUSES = {
    "MATCH",
    "LOCAL_ANALOG",
    "PARTIAL",
    "INTENTIONAL_DIFFERENCE",
    "MISSING",
}
REQUIRED_OK = {"MATCH", "LOCAL_ANALOG", "INTENTIONAL_DIFFERENCE"}


def parse_matrix(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line.startswith("|") or "---" in line or line.startswith("| Domain "):
            continue
        cells = [cell.strip().strip("`") for cell in line.strip("|").split("|")]
        if len(cells) != 7:
            continue
        rows.append(
            {
                "domain": cells[0],
                "source": cells[1],
                "behavior": cells[2],
                "evidence": cells[3],
                "status": cells[4],
                "note": cells[5],
                "priority": cells[6],
            }
        )
    return rows


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    matrix = root / "foundry-docs" / "VALIDATION_MATRIX.md"
    report = root / "foundry-docs" / "VALIDATION_REPORT.md"

    if not matrix.exists():
        print(f"Missing matrix: {matrix}")
        return 2
    if not report.exists():
        print(f"Missing report: {report}")
        return 2

    rows = parse_matrix(matrix)
    if not rows:
        print("No validation rows parsed.")
        return 2

    statuses = Counter(row["status"] for row in rows)
    unknown = sorted(status for status in statuses if status not in VALID_STATUSES)
    p0_failures = [
        row for row in rows
        if row["priority"] == "P0" and row["status"] not in REQUIRED_OK
    ]

    print("Docs conformance matrix summary")
    print(f"Rows: {len(rows)}")
    for status in sorted(statuses):
        print(f"{status}: {statuses[status]}")

    if unknown:
        print(f"Unknown statuses: {', '.join(unknown)}")
        return 1
    if p0_failures:
        print("P0 rows are not conformant:")
        for row in p0_failures:
            print(f"- {row['domain']}: {row['status']} ({row['note']})")
        return 1

    print("Required P0 conformance target satisfied.")
    return 0


if __name__ == "__main__":
    from enforcement_runs import recording  # noqa: E402
    sys.exit(recording("validate_docs_conformance", main))