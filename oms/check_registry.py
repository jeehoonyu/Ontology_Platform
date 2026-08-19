"""Every check-shaped script, what it gates, and where it is supposed to run.

Condition C2 of GOAL_2026-08-13. C5 and C6 made it visible when a *declared*
check stops running. This makes it visible when a check was never declared at
all -- which is how `audit_query_bounds` and `audit_route_coverage`, two ratchets
the standing goal names by title, came to be invoked by no workflow and no test.
They ran on 2026-08-13 only because someone typed the command.

The registry is deliberately not the source of truth for *requirements*. Those
are inferred from each script, so a script that starts needing PostgreSQL cannot
drift away from a declaration claiming it needs nothing. What is declared here is
the part no parser can know: which claim the check defends, and how often it is
expected to run.

Three homes, and the distinction between the first two is the whole point:

  suite    a test imports and executes it against the live tree
  ci       a workflow step runs it, and nothing else does
  manual   it needs infrastructure a test run cannot provide, so a human or a
           scheduled job runs it at a declared cadence

A check that needs no infrastructure and has no `suite` home is a defect, not a
declaration. The audit reports those separately, because "nobody automated this"
and "this cannot be automated here" are different problems with different fixes.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List

OMS = Path(__file__).resolve().parent
REPO_ROOT = OMS.parent
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

CHECK_PREFIXES = ("audit_", "validate_", "verify_", "rehearse_", "benchmark_")

# What each check defends, and how often it should run. Requirements are not
# listed: they are read out of the script itself by `requirements_of`.
DECLARATIONS: Dict[str, Dict[str, str]] = {
    # --- static analysis over the tree: nothing to provision -----------------
    "audit_enforcement": {"gates": "every declared check still runs", "cadence": "every push"},
    "audit_evidence_corpus": {"gates": "evidence carries a migration head", "cadence": "every push"},
    "audit_extensibility": {"gates": "the next object type costs no more than the last", "cadence": "every push"},
    "audit_latency_observations": {"gates": "a latency gate is the worst of at least six runs", "cadence": "every push"},
    "audit_query_bounds": {"gates": "no read materializes an object type before filtering", "cadence": "every push"},
    "audit_request_cost": {"gates": "no route runs one statement shape over and over", "cadence": "every suite run"},
    "audit_snapshot_scope": {"gates": "no snapshot collection is silently emptied by scoping", "cadence": "every push"},
    "audit_suite_cost": {"gates": "no route, write included, repeats a shape more than its baseline", "cadence": "manual: needs a full suite census (~20 min)"},
    "audit_browser_evidence": {"gates": "the browser suite ran against this commit's bundle and its coverage did not narrow", "cadence": "manual: needs node and a Chrome channel"},
    "audit_iteration_state": {"gates": "every goal condition carries a state, every check runs where it says, every baseline is dated", "cadence": "every suite run"},
    "audit_ui_states": {"gates": "no new hand-written empty state, and every treatment declares its reason", "cadence": "every suite run"},
    "audit_tier_a": {"gates": "no Tier A sub-condition regresses from met", "cadence": "every suite run"},
    "audit_route_coverage": {"gates": "compatibility routes have typed equivalents before retirement", "cadence": "every push"},
    "validate_docs_conformance": {"gates": "documentation states what the product does", "cadence": "every suite run"},
    "validate_schema_freeze": {"gates": "no migration lands during a pilot window", "cadence": "every push"},
    "validate_tier_b_evidence": {"gates": "Tier B gates are current and threshold-checked", "cadence": "every suite run"},
    "validate_external_evaluations": {"gates": "external evaluations carry provenance", "cadence": "every suite run"},
    "audit_check_coverage": {"gates": "every check is declared and homed", "cadence": "every push"},
    "audit_dependency_provenance": {"gates": "evidence names the third-party code that produced it", "cadence": "every suite run"},

    # --- need a database ------------------------------------------------------
    "benchmark_ontology_scale_postgres": {"gates": "Tier B ontology scale", "cadence": "manual: needs postgres"},
    "benchmark_ontology_mixed_workload_postgres": {"gates": "Tier B mixed workload", "cadence": "manual: needs postgres"},
    "benchmark_pipeline_scale": {"gates": "Tier B pipeline scale", "cadence": "manual: needs postgres for the reference run"},
    "verify_artifact_review_postgres": {"gates": "artifact review survives a real database", "cadence": "manual: needs postgres"},
    "verify_collaboration_scale_postgres": {"gates": "Tier B collaboration", "cadence": "manual: needs postgres"},
    "verify_collaboration_websocket_chaos_postgres": {"gates": "Tier B chaos, websocket process loss", "cadence": "manual: needs postgres"},
    "verify_cross_stream_join_postgres": {"gates": "cross-stream joins on a real database", "cadence": "manual: needs postgres"},
    "verify_cross_stream_outer_postgres": {"gates": "cross-stream outer joins", "cadence": "manual: needs postgres"},
    "verify_cross_stream_partition_postgres": {"gates": "Tier B chaos, partition recovery", "cadence": "manual: needs postgres"},
    "verify_cross_stream_outer_partition_postgres": {"gates": "Tier B chaos, outer-join partition recovery", "cadence": "manual: needs postgres"},
    "verify_event_stream_routing_postgres": {"gates": "durable event-to-stream routing", "cadence": "manual: needs postgres"},
    "verify_ontology_query_postgres": {"gates": "the ontology query compiler on PostgreSQL", "cadence": "manual: needs postgres and kafka"},
    "verify_stream_processing_postgres": {"gates": "stream ordering and processor fencing", "cadence": "manual: needs postgres"},

    # --- need a database and Docker ------------------------------------------
    "rehearse_ontology_scale_backup_restore": {"gates": "Tier B durability, fresh-volume restore", "cadence": "manual: needs postgres and docker"},
    "rehearse_ontology_scale_replica_failover": {"gates": "Tier B durability, replica promotion", "cadence": "manual: needs postgres and docker"},
    "rehearse_ontology_scale_recovery": {"gates": "process-restart recovery of the reference fixture", "cadence": "manual: needs postgres and docker"},
    "rehearse_pipeline_worker_recovery": {"gates": "pipeline worker loss and lease fencing", "cadence": "manual: needs postgres and object-store"},

    # --- need a broker, an object store, an OCI sandbox, or a remote service --
    "rehearse_event_kafka": {"gates": "outbox mirroring into Kafka", "cadence": "manual: needs kafka"},
    "rehearse_event_kafka_recovery": {"gates": "broker interruption and recovery", "cadence": "manual: needs kafka"},
    "rehearse_kafka_connector": {"gates": "the durable Kafka connector path", "cadence": "manual: needs kafka"},
    "benchmark_object_storage_minio": {"gates": "object-storage snapshot throughput", "cadence": "manual: needs object-store"},
    "rehearse_s3_snapshot_minio": {"gates": "S3-backed snapshot round trip", "cadence": "manual: needs object-store"},
    "rehearse_plugin_egress": {"gates": "signed-plugin egress denial and CA pinning", "cadence": "manual: needs docker and oci-sandbox"},
    "rehearse_plugin_oci": {"gates": "the hardened plugin OCI boundary", "cadence": "manual: needs oci-sandbox"},
    "rehearse_sftp_connector": {"gates": "the durable connector path against real SFTP", "cadence": "manual: needs sftp"},
}

_REQUIREMENT_PATTERNS = (
    ("postgres", re.compile(r"requires a PostgreSQL DATABASE_URL|startswith\(\"postgresql\"\)")),
    ("docker", re.compile(r'"docker"')),
    ("kafka", re.compile(r"(?i)kafka")),
    ("object-store", re.compile(r"(?i)minio|boto3|s3_client")),
    ("oci-sandbox", re.compile(r"(?i)oci|sandbox image|plugin_executor")),
    ("sftp", re.compile(r"(?i)sftp")),
)


def discover() -> List[str]:
    """Every check-shaped script in oms/, by name."""
    names = []
    for path in sorted(OMS.glob("*.py")):
        if path.name.startswith("test_"):
            continue
        if path.name.startswith(CHECK_PREFIXES):
            names.append(path.stem)
    return names


def requirements_of(name: str) -> List[str]:
    """What a check needs, read from the script rather than declared.

    Inferred so a script that grows a dependency cannot keep a declaration that
    says it needs nothing. Coarse on purpose: it decides whether a check *could*
    run in a plain test process, not how to provision it.
    """
    path = OMS / f"{name}.py"
    if not path.exists():
        return []
    source = path.read_text(encoding="utf-8", errors="replace")
    return [label for label, pattern in _REQUIREMENT_PATTERNS if pattern.search(source)]


def workflow_invocations() -> set:
    """Checks any workflow runs."""
    invoked = set()
    if not WORKFLOWS.is_dir():
        return invoked
    for path in WORKFLOWS.glob("*.yml"):
        text = path.read_text(encoding="utf-8", errors="replace")
        invoked.update(re.findall(r"python oms/([a-z_0-9]+)\.py", text))
    return invoked


def suite_executions() -> set:
    """Checks a test actually imports and runs.

    An import, not a mention. Every benchmark and verifier has a contract test
    that reads its source with `read_text` and asserts things about it -- useful,
    and not the same as running it. Counting those as a home is what made this
    surface look covered when it was not.
    """
    executed = set()
    for path in sorted(OMS.glob("test_*.py")):
        source = path.read_text(encoding="utf-8", errors="replace")
        for name in re.findall(r"^\s*(?:import\s+([a-z_0-9]+)|from\s+([a-z_0-9]+)\s+import)",
                               source, re.MULTILINE):
            executed.add(name[0] or name[1])
    return executed & set(discover())
