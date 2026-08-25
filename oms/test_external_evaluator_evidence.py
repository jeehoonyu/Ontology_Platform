"""External evaluator evidence rejects tampering and dependent submissions."""
from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from evaluator_evidence import KIND, SCHEMA_VERSION, load_bundles, seal_bundle, sha256_json, validate_bundle, validate_corpus
from tier_b_evidence import current_head


passed = 0


def valid_bundle(team: str, organization: str, deployment: str, identity_seed: str, dataset_seed: str):
    report_payload = {"project_id": organization, "decision": "Inspection required", "evidence_ids": [f"evidence-{team}"]}
    steps = [
        {"id": step, "status": "complete", "evidence_id": f"{team}-{step}"}
        for step in ("connect", "transform", "model", "analyze", "approve", "act", "report")
    ]
    return seal_bundle({
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "generated_at": 1_786_500_000,
        "migration_head": current_head(),
        "release_commit": "a" * 40,
        "authentication_mode": "oidc",
        "project": {"id": f"project-{team}", "object_count": 3},
        "evaluator": {
            "team_id": team,
            "organization_id": organization,
            "deployment_id": deployment,
            "identity_hash": sha256_json({"identity": identity_seed}),
            "principal_hash": sha256_json({"principal": identity_seed}),
            "external_team_confirmation": True,
        },
        "dataset": {
            "asset_id": f"asset-{team}", "snapshot_id": f"snapshot-{team}",
            "content_hash": sha256_json({"dataset": dataset_seed}), "row_count": 3,
            "storage_format": "parquet", "import_job_id": f"import-{team}",
            "source_type": "csv", "provenance_verified": True, "own_data_confirmation": True,
        },
        "workflow": {"name": "asset_reliability_connect_to_report", "steps": steps, "evidence_ids": [row["evidence_id"] for row in steps]},
        "report": {"id": f"report-{team}", "content_hash": sha256_json(report_payload), "payload": report_payload},
        "qualification": {"qualifies": True, "reasons": []},
    })


first = valid_bundle("team-alpha", "external-alpha", "deployment-alpha", "alice", "alpha-data")
second = valid_bundle("team-beta", "external-beta", "deployment-beta", "bob", "beta-data")
assert validate_bundle(first) == []
passed += 1

summary, errors = validate_corpus([first])
assert summary["status"] == "FAIL" and "qualifying_bundle_count:1<2" in errors
passed += 1

duplicate = copy.deepcopy(first)
duplicate["evaluator"] = dict(duplicate["evaluator"], identity_hash=second["evaluator"]["identity_hash"], principal_hash=second["evaluator"]["principal_hash"])
duplicate["dataset"] = dict(duplicate["dataset"], content_hash=second["dataset"]["content_hash"])
duplicate = seal_bundle(duplicate)
summary, errors = validate_corpus([first, duplicate])
assert summary["status"] == "FAIL"
assert "independence_violation:team" in errors
assert "independence_violation:organization" in errors
assert "independence_violation:deployment" in errors
passed += 4

tampered = copy.deepcopy(first)
tampered["report"]["payload"]["decision"] = "No action"
errors = validate_bundle(tampered)
assert "bundle_hash_mismatch" in errors and "report_hash_mismatch" in errors
passed += 2

incomplete = copy.deepcopy(first)
incomplete["workflow"]["steps"][-1]["status"] = "available"
incomplete["qualification"] = {"qualifies": False, "reasons": ["workflow_step_incomplete:report"]}
incomplete = seal_bundle(incomplete)
errors = validate_bundle(incomplete)
assert "workflow_step_incomplete:report" in errors and "bundle_not_qualifying" in errors
passed += 2

summary, errors = validate_corpus([first, second])
assert errors == [] and summary["status"] == "PASS"
assert summary["distinct_teams"] == summary["distinct_organizations"] == summary["distinct_deployments"] == summary["distinct_datasets"] == 2
passed += 2

with tempfile.TemporaryDirectory() as tmp:
    paths = []
    for index, bundle in enumerate((first, second)):
        path = Path(tmp) / f"team-{index}.json"
        path.write_text(json.dumps(bundle, indent=2, sort_keys=True), encoding="utf-8")
        paths.append(path)
    loaded = load_bundles(paths)
    assert loaded == [first, second]
    passed += 1
    command = [sys.executable, str(Path(__file__).with_name("validate_external_evaluations.py")), *map(str, paths)]
    strict = subprocess.run(command, capture_output=True, text=True, check=False)
    assert strict.returncode == 0 and '"status": "PASS"' in strict.stdout, strict.stdout + strict.stderr
    passed += 1

root = Path(__file__).resolve().parent.parent
assert "COPY oms/evaluator_evidence.py ./evaluator_evidence.py" in (root / "oms" / "Dockerfile").read_text(encoding="utf-8")
assert "ONTOLOGYOS_RELEASE_COMMIT" in (root / "docker-compose.production.yml").read_text(encoding="utf-8")
assert (root / "docs" / "EXTERNAL_EVALUATOR_GUIDE.md").exists()
passed += 3

print(f"External evaluator evidence verified: {passed} assertions passed.")
