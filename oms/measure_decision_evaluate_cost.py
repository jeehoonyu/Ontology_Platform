"""What one decision evaluation costs when it scores its whole scope.

GOAL_HONEST_UI_2026-09-11, the Decision workspace limits. The workspace used to score
the first 250 objects by id; it now scores everything up to
`decision_intelligence.EVALUATE_SCAN_CEILING` inside the request and keeps the 250
highest-risk findings. Whether that ceiling is affordable on a click is a measurement,
not an argument, so this measures it: one fresh type per size, hydrated through a
pipeline run, one rule and a two-feature scorecard, then one evaluation through the API.

  python oms/measure_decision_evaluate_cost.py
  python oms/measure_decision_evaluate_cost.py --sizes 1000,5000,10000
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", default="1000,10000", help="Comma-separated object counts")
    args = parser.parse_args()
    sizes = [int(item) for item in args.sizes.split(",") if item.strip()]

    tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'decision_evaluate_cost.db')}"
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from fastapi.testclient import TestClient
    from app.database import engine
    from app.main import app

    client = TestClient(app)

    def post(path, body, label):
        response = client.post(path, json=body)
        if response.status_code >= 300:
            raise SystemExit(f"{label}: {response.status_code} {response.text[:500]}")
        return response

    results = []
    for size in sizes:
        type_id = f"evaluate_cost_{size}"
        post("/object-types", {
            "id": type_id, "display_name": type_id, "description": "Decision evaluate cost",
            "properties": {"name": {"type": "string"}, "status": {"type": "string"}, "criticality": {"type": "string"}},
        }, "type")
        # One object in ten is degraded and high-criticality, so it scores 90.
        records = [{
            "id": f"{type_id}_{index:06d}", "name": f"Object {index}",
            "status": "DEGRADED" if index % 10 == 0 else "RUNNING",
            "criticality": "high" if index % 10 == 0 else "low",
        } for index in range(1, size + 1)]
        post("/data-assets", {"id": f"{type_id}_feed", "display_name": "feed", "kind": "dataset", "asset_schema": {}, "records": records}, "feed")
        post("/pipelines", {
            "id": f"{type_id}_hydrate", "display_name": "hydrate", "input_asset_id": f"{type_id}_feed",
            "steps": [{"operation": "map_to_ontology", "object_type_id": type_id, "object_id_field": "id",
                       "property_map": {"name": "$name", "status": "$status", "criticality": "$criticality"}, "omit_nulls": True}],
        }, "pipeline")
        started = time.perf_counter()
        run = client.post(f"/pipelines/{type_id}_hydrate/run", params={"actor": "measure"}).json()
        hydrate_seconds = time.perf_counter() - started
        if run.get("status") != "SUCCESS":
            raise SystemExit(f"hydrate {size}: {run}")
        post("/decision/rules", {
            "id": f"{type_id}_degraded", "display_name": "Degraded", "object_type_id": type_id,
            "expression": {"field": "status", "op": "eq", "value": "DEGRADED"}, "severity": "high",
        }, "rule")
        post("/decision/scorecards", {
            "id": f"{type_id}_scorecard", "display_name": "Cost scorecard", "object_type_id": type_id,
            "features": [
                {"rule_id": f"{type_id}_degraded", "weight": 60, "reason": "degraded"},
                {"field": "criticality", "op": "eq", "value": "high", "weight": 30, "reason": "high criticality"},
            ],
            "thresholds": {"medium": 35, "high": 65, "critical": 85},
        }, "scorecard")
        started = time.perf_counter()
        response = post("/decision/evaluate", {
            "object_type_id": type_id, "filters": {}, "limit": 10000, "finding_limit": 250, "persist_run": True,
        }, "evaluate")
        evaluate_seconds = time.perf_counter() - started
        body = response.json()
        results.append({
            "objects": size,
            "evaluate_seconds": round(evaluate_seconds, 3),
            "seconds_per_1000_objects": round(evaluate_seconds / max(body["object_count"], 1) * 1000, 3),
            "response_bytes": len(response.content),
            "object_count": body["object_count"],
            "objects_in_scope": body["objects_in_scope"],
            "findings_kept": len(body["findings"]),
            "hydrate_seconds": round(hydrate_seconds, 3),
        })

    print(json.dumps({"platform": sys.platform, "python": sys.version.split()[0], "results": results}, indent=2))
    engine.dispose()
    tmpdir.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
