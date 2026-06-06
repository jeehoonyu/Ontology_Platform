import os
import tempfile
import uuid

tmpdir = tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'sentinel_graph.db')}"

from app import models, models_action, schemas  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.main import (  # noqa: E402
    bootstrap_sentinel_domain,
    create_sentinel_case,
    create_sentinel_finding,
    create_sentinel_task,
    decide_approval,
    draft_sentinel_report,
    execute_action,
    get_case_graph,
    get_case_provenance,
    get_case_timeline,
    get_graph_neighbors,
    get_graph_shortest_path,
    get_missing_sentinel_evidence,
    get_sentinel_summary,
    ingest_sentinel_evidence,
    run_eval_suite,
    suggest_sentinel_next_steps,
    summarize_sentinel_case,
)


models.Base.metadata.create_all(bind=engine)
models_action.Base.metadata.create_all(bind=engine)


def main():
    db = SessionLocal()
    try:
        bootstrap = bootstrap_sentinel_domain(schemas.SentinelBootstrapRequest(actor="test"), db)
        assert bootstrap["domain"] == "sentinel_operations_graph"
        assert "sentinel_case" in bootstrap["object_types"]

        case = create_sentinel_case(
            schemas.SentinelCaseCreate(
                id="case_line4_pump",
                title="Line 4 Pump Investigation",
                description="Investigate repeated pump vibration and missing seal-kit evidence.",
                owner="ops_analyst",
                sensitivity="internal",
                actor="ops_analyst",
            ),
            db,
        )
        assert case["id"] == "case_line4_pump"

        evidence = ingest_sentinel_evidence(
            "case_line4_pump",
            schemas.SentinelEvidenceIngestRequest(
                id="evidence_vendor_email",
                title="Vendor email",
                text=(
                    "Case Note: Pump seal kit shortage. Contact ops@example.com. "
                    "Reference WO_4100. Follow-up date 2026-07-01. Estimated cost $1,250.00."
                ),
                source_uri="mail://ops/vendor/123",
                extraction_schema={"work_order": {"pattern": r"Reference\s+([A-Z]+_\d+)"}},
                actor="ops_analyst",
            ),
            db,
        )
        assert evidence["evidence"]["id"] == "evidence_vendor_email"
        assert any(entity["properties"]["name"] == "ops@example.com" for entity in evidence["entities"])
        entity_id = evidence["entities"][0]["id"]

        task = create_sentinel_task(
            "case_line4_pump",
            schemas.SentinelTaskCreate(
                id="task_verify_inventory",
                title="Verify seal-kit inventory",
                description="Confirm stock level and reorder lead time.",
                priority="high",
                actor="ops_analyst",
            ),
            db,
        )
        assert task["properties"]["status"] == "OPEN"

        finding = create_sentinel_finding(
            "case_line4_pump",
            schemas.SentinelFindingCreate(
                id="finding_part_shortage",
                title="Seal kit shortage may delay repair",
                summary="Evidence indicates part shortage and vendor follow-up requirement.",
                confidence=0.82,
                actor="ops_analyst",
            ),
            db,
        )
        assert finding["properties"]["confidence"] == 0.82

        graph = get_case_graph("case_line4_pump", db=db)
        assert len(graph["nodes"]) >= 5
        assert any(edge["link_type_id"] == "evidence_mentions_entity" for edge in graph["edges"])

        timeline = get_case_timeline("case_line4_pump", db)
        assert len(timeline["timeline"]) >= 2

        provenance = get_case_provenance("case_line4_pump", db)
        assert provenance["provenance"]
        assert all("confidence" in item for item in provenance["provenance"])
        assert any(item["source_id"] == "evidence_vendor_email" for item in provenance["provenance"])

        neighbors = get_graph_neighbors(schemas.SentinelGraphQuery(object_id="case_line4_pump", depth=2), db)
        assert any(node["id"] == entity_id for node in neighbors["nodes"])

        path = get_graph_shortest_path(
            schemas.SentinelPathQuery(source_id="case_line4_pump", target_id=entity_id),
            db,
        )
        assert path["found"] is True
        assert path["object_ids"][0] == "case_line4_pump"
        assert path["object_ids"][-1] == entity_id

        summary = summarize_sentinel_case(
            "case_line4_pump",
            schemas.SentinelCopilotRequest(actor="ops_analyst"),
            db,
        )
        assert "evidence item" in summary["summary"]

        missing = get_missing_sentinel_evidence(
            "case_line4_pump",
            schemas.SentinelCopilotRequest(actor="ops_analyst"),
            db,
        )
        assert missing["complete"] is True

        suggestions = suggest_sentinel_next_steps(
            "case_line4_pump",
            schemas.SentinelCopilotRequest(actor="ops_analyst"),
            db,
        )
        assert suggestions["suggestions"][0]["title"] == "Draft case report for review"

        report = draft_sentinel_report(
            "case_line4_pump",
            schemas.SentinelCopilotRequest(actor="ops_analyst"),
            db,
        )
        assert report["object_type_id"] == "sentinel_report"
        assert report["properties"]["status"] == "DRAFT"

        approval = execute_action(
            schemas.ActionExecutionRequest(
                action_type_id="publish_sentinel_report",
                parameters={"report_id": report["id"], "approval_note": "Approved for maintenance leadership review."},
                idempotency_key=f"publish-{uuid.uuid4()}",
                actor="ops_analyst",
            ),
            db,
        )
        assert approval.status == "REQUIRES_APPROVAL"
        decide_approval(
            approval.approval_request_id,
            schemas.ApprovalDecisionRequest(actor="case_manager", decision="APPROVED"),
            db,
        )
        published = execute_action(
            schemas.ActionExecutionRequest(
                action_type_id="publish_sentinel_report",
                parameters={"report_id": report["id"], "approval_note": "Approved for maintenance leadership review."},
                idempotency_key=f"publish-approved-{uuid.uuid4()}",
                actor="ops_analyst",
                approval_request_id=approval.approval_request_id,
            ),
            db,
        )
        assert published.status == "SUCCESS"
        refreshed_report = db.query(models.ObjectInstance).filter_by(id=report["id"]).first()
        assert refreshed_report.properties["status"] == "PUBLISHED"

        eval_run = run_eval_suite("sentinel_analyst_eval", db)
        assert eval_run.status == "SUCCESS"
        assert eval_run.score == 100

        sentinel_summary = get_sentinel_summary(db)
        assert sentinel_summary["object_counts"]["sentinel_case"] == 1
        assert db.query(models_action.AuditLog).count() >= 12

        print("Sentinel operations graph scenario passed")
    finally:
        db.close()
        engine.dispose()
        tmpdir.cleanup()


if __name__ == "__main__":
    main()
