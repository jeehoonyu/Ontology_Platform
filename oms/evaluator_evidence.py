"""Pure validation for independent Connect-to-Report evaluator evidence.

The runtime produces these bundles, but the verifier deliberately has no database
or FastAPI dependency. External teams and CI can therefore validate exported
evidence without trusting the server process that rendered the UI.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


SCHEMA_VERSION = 1
KIND = "ontologyos.external_evaluator.connect_to_report"
REQUIRED_STEPS = ("connect", "transform", "model", "analyze", "approve", "act", "report")


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def seal_bundle(payload: Dict[str, Any]) -> Dict[str, Any]:
    sealed = dict(payload)
    sealed.pop("bundle_hash", None)
    sealed["bundle_hash"] = sha256_json(sealed)
    return sealed


def _is_hash(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


def _is_release(value: Any) -> bool:
    text = str(value or "").lower()
    return 7 <= len(text) <= 64 and all(character in "0123456789abcdef" for character in text)


def validate_bundle(bundle: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    if bundle.get("schema_version") != SCHEMA_VERSION:
        errors.append("unsupported_schema_version")
    if bundle.get("kind") != KIND:
        errors.append("invalid_kind")
    supplied_hash = bundle.get("bundle_hash")
    unsigned = dict(bundle)
    unsigned.pop("bundle_hash", None)
    if not _is_hash(supplied_hash) or supplied_hash != sha256_json(unsigned):
        errors.append("bundle_hash_mismatch")
    if not _is_release(bundle.get("release_commit")):
        errors.append("release_commit_not_pinned")
    if not str(bundle.get("migration_head") or ""):
        errors.append("migration_head_missing")

    evaluator = bundle.get("evaluator") or {}
    for field in ("team_id", "organization_id", "deployment_id"):
        if not str(evaluator.get(field) or "").strip():
            errors.append(f"evaluator_{field}_missing")
    if not _is_hash(evaluator.get("identity_hash")):
        errors.append("evaluator_identity_hash_invalid")
    if not _is_hash(evaluator.get("principal_hash")):
        errors.append("evaluator_principal_hash_invalid")
    if evaluator.get("external_team_confirmation") is not True:
        errors.append("external_team_not_confirmed")

    dataset = bundle.get("dataset") or {}
    if dataset.get("own_data_confirmation") is not True:
        errors.append("own_data_not_confirmed")
    if dataset.get("provenance_verified") is not True:
        errors.append("own_data_provenance_unverified")
    if not _is_hash(dataset.get("content_hash")):
        errors.append("dataset_content_hash_invalid")
    if int(dataset.get("row_count") or 0) <= 0:
        errors.append("dataset_empty")

    workflow = bundle.get("workflow") or {}
    steps = {str(item.get("id")): item for item in workflow.get("steps") or [] if isinstance(item, dict)}
    for step_id in REQUIRED_STEPS:
        if (steps.get(step_id) or {}).get("status") != "complete":
            errors.append(f"workflow_step_incomplete:{step_id}")
        if not str((steps.get(step_id) or {}).get("evidence_id") or ""):
            errors.append(f"workflow_step_evidence_missing:{step_id}")

    report = bundle.get("report") or {}
    if not _is_hash(report.get("content_hash")) or report.get("content_hash") != sha256_json(report.get("payload") or {}):
        errors.append("report_hash_mismatch")
    qualification = bundle.get("qualification") or {}
    if qualification.get("qualifies") is not True or qualification.get("reasons"):
        errors.append("bundle_not_qualifying")
    return sorted(set(errors))


def validate_corpus(bundles: Iterable[Dict[str, Any]], minimum_teams: int = 2) -> Tuple[Dict[str, Any], List[str]]:
    rows = list(bundles)
    errors: List[str] = []
    for index, bundle in enumerate(rows):
        errors.extend(f"bundle[{index}]:{error}" for error in validate_bundle(bundle))
    if len(rows) < minimum_teams:
        errors.append(f"qualifying_bundle_count:{len(rows)}<{minimum_teams}")

    uniqueness_fields = {
        "team": [str((row.get("evaluator") or {}).get("team_id") or "") for row in rows],
        "organization": [str((row.get("evaluator") or {}).get("organization_id") or "") for row in rows],
        "deployment": [str((row.get("evaluator") or {}).get("deployment_id") or "") for row in rows],
        "identity": [str((row.get("evaluator") or {}).get("identity_hash") or "") for row in rows],
        "principal": [str((row.get("evaluator") or {}).get("principal_hash") or "") for row in rows],
        "dataset": [str((row.get("dataset") or {}).get("content_hash") or "") for row in rows],
    }
    if len(rows) >= minimum_teams:
        for label, values in uniqueness_fields.items():
            if len(set(values)) != len(values):
                errors.append(f"independence_violation:{label}")
        releases = {str(row.get("release_commit") or "") for row in rows}
        heads = {str(row.get("migration_head") or "") for row in rows}
        if len(releases) != 1:
            errors.append("release_commit_mismatch")
        if len(heads) != 1:
            errors.append("migration_head_mismatch")

    summary = {
        "schema_version": SCHEMA_VERSION,
        "bundle_count": len(rows),
        "minimum_teams": minimum_teams,
        "distinct_teams": len(set(uniqueness_fields["team"])),
        "distinct_organizations": len(set(uniqueness_fields["organization"])),
        "distinct_deployments": len(set(uniqueness_fields["deployment"])),
        "distinct_datasets": len(set(uniqueness_fields["dataset"])),
        "release_commit": rows[0].get("release_commit") if rows else None,
        "migration_head": rows[0].get("migration_head") if rows else None,
        "status": "PASS" if not errors else "FAIL",
    }
    return summary, sorted(set(errors))


def load_bundles(paths: Iterable[Path]) -> List[Dict[str, Any]]:
    bundles: List[Dict[str, Any]] = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"{path} does not contain a JSON object")
        bundles.append(payload)
    return bundles
