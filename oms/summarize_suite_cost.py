"""Aggregate what `measure_suite_cost.py` recorded, without deciding anything.

Kept separate from the recorder on purpose. A census that can only be read
through its own summariser is hard to disagree with, and the raw JSONL is one
line per request precisely so someone can ask it a different question than the
one asked here.

The worst observation wins, never the mean: a route called forty times with one
expensive call is a route with an expensive call.

  python oms/summarize_suite_cost.py costs.jsonl
  python oms/summarize_suite_cost.py costs.jsonl --writes
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def load(path: Path) -> list:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def aggregate(rows: list) -> Dict[tuple, Dict[str, Any]]:
    grouped: Dict[tuple, Dict[str, Any]] = defaultdict(
        lambda: {"calls": 0, "max_queries": 0, "worst_repeat": 0, "worst_shape": None,
                 "statuses": set()})
    for row in rows:
        key = (row.get("method", "?"), row.get("route", "?"))
        entry = grouped[key]
        entry["calls"] += 1
        entry["statuses"].add(row.get("status"))
        if row.get("queries", 0) > entry["max_queries"]:
            entry["max_queries"] = row["queries"]
        if row.get("worst_repeat", 0) > entry["worst_repeat"]:
            entry["worst_repeat"] = row["worst_repeat"]
            entry["worst_shape"] = row.get("worst_shape")
    return grouped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path")
    parser.add_argument("--writes", action="store_true", help="Only POST/PUT/PATCH/DELETE")
    parser.add_argument("--top", type=int, default=20)
    args = parser.parse_args()

    rows = load(Path(args.path))
    if not rows:
        print("No requests recorded.")
        return 1
    grouped = aggregate(rows)
    if args.writes:
        grouped = {key: value for key, value in grouped.items() if key[0] in WRITE_METHODS}

    writes = sum(1 for row in rows if row.get("method") in WRITE_METHODS)
    print(f"{len(rows)} requests over {len(grouped)} route+method pairs "
          f"({writes} writes, {len(rows) - writes} reads)\n")

    print(f"top {args.top} by worst repeated shape:")
    ranked = sorted(grouped.items(), key=lambda item: (-item[1]["worst_repeat"],
                                                       -item[1]["max_queries"]))
    for (method, route), entry in ranked[:args.top]:
        if not entry["worst_repeat"]:
            break
        print(f"  x{entry['worst_repeat']:<4} {entry['max_queries']:5d} queries  "
              f"{entry['calls']:4d} calls  {method:<6} {route}")

    print(f"\ntop {args.top} by statements in one request:")
    for (method, route), entry in sorted(grouped.items(),
                                         key=lambda item: -item[1]["max_queries"])[:args.top]:
        print(f"  {entry['max_queries']:5d} queries  x{entry['worst_repeat']:<4} "
              f"{entry['calls']:4d} calls  {method:<6} {route}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
