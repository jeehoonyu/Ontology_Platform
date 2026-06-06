import os
import tempfile
import uuid

tmpdir = tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'maintenance_copilot.db')}"

from app import models, models_action, schemas  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.main import (  # noqa: E402
    bootstrap_maintenance_domain,
    decide_approval,
    execute_action,
    get_maintenance_summary,
    run_agent_session,
    run_automation,
    run_eval_suite,
    run_logic_function,
)


models.Base.metadata.create_all(bind=engine)
models_action.Base.metadata.create_all(bind=engine)


def main():
    db = SessionLocal()
    try:
        bootstrap = bootstrap_maintenance_domain(
            schemas.DomainBootstrapRequest(actor="test", run_pipelines=True),
            db,
        )
        assert bootstrap["domain"] == "maintenance_copilot"
        assert len(bootstrap["pipeline_runs"]) == 5
        assert all(run["status"] == "SUCCESS" for run in bootstrap["pipeline_runs"])

        summary = get_maintenance_summary(db)
        assert summary["object_counts"]["facility"] == 1
        assert summary["object_counts"]["asset"] == 2
        assert summary["object_counts"]["technician"] == 1
        assert summary["object_counts"]["part"] == 1
        assert summary["object_counts"]["work_order"] == 2
        assert any(item["id"] == "wo_pump_urgent" for item in summary["open_work_orders"])
        priority_by_work_order = {item["id"]: item["priority"] for item in summary["open_work_orders"]}
        assert priority_by_work_order["wo_pump_urgent"] == "critical"
        assert priority_by_work_order["wo_chiller_inspect"] == "normal"

        automation_run = run_automation("maintenance_critical_work_order_monitor", db=db)
        assert automation_run.status == "TRIGGERED"
        assert automation_run.effect_result["status"] == "APPROVAL_REQUESTED"

        agent_session = run_agent_session(
            "maintenance_ops_agent",
            schemas.AgentSessionCreate(user_prompt="Please escalate work order for urgent pump issue"),
            db,
        )
        assert agent_session.status == "ACTION_PROPOSED"
        assert agent_session.proposed_actions[0]["action_type_id"] == "escalate_work_order"

        assignment = execute_action(
            schemas.ActionExecutionRequest(
                action_type_id="assign_technician",
                parameters={"work_order_id": "wo_pump_urgent", "technician_id": "tech_amy"},
                idempotency_key=f"assign-{uuid.uuid4()}",
                actor="dispatcher",
            ),
            db,
        )
        assert assignment.status == "SUCCESS"
        work_order = db.query(models.ObjectInstance).filter_by(id="wo_pump_urgent").first()
        assert work_order.properties["assigned_technician_id"] == "tech_amy"
        assert work_order.properties["status"] == "ASSIGNED"

        approval = execute_action(
            schemas.ActionExecutionRequest(
                action_type_id="create_purchase_request",
                parameters={
                    "purchase_request_id": "pr_seal_kit_1",
                    "part_id": "part_seal_kit",
                    "quantity": 2,
                    "reason": "Pump repair requires seal kit and inventory is below reorder point.",
                },
                idempotency_key=f"purchase-{uuid.uuid4()}",
                actor="maintenance_ops_agent",
            ),
            db,
        )
        assert approval.status == "REQUIRES_APPROVAL"
        decide_approval(
            approval.approval_request_id,
            schemas.ApprovalDecisionRequest(actor="manager", decision="APPROVED"),
            db,
        )
        purchase = execute_action(
            schemas.ActionExecutionRequest(
                action_type_id="create_purchase_request",
                parameters={
                    "purchase_request_id": "pr_seal_kit_1",
                    "part_id": "part_seal_kit",
                    "quantity": 2,
                    "reason": "Pump repair requires seal kit and inventory is below reorder point.",
                },
                idempotency_key=f"purchase-approved-{uuid.uuid4()}",
                actor="maintenance_ops_agent",
                approval_request_id=approval.approval_request_id,
            ),
            db,
        )
        assert purchase.status == "SUCCESS"
        purchase_request = db.query(models.ObjectInstance).filter_by(id="pr_seal_kit_1").first()
        assert purchase_request.properties["status"] == "PENDING_APPROVAL"

        logic_run = run_logic_function(
            "maintenance_triage_logic",
            schemas.LogicRunRequest(
                inputs={
                    "prompt": "Escalate critical maintenance risk",
                    "work_order_id": "wo_pump_urgent",
                    "reason": "Production-impacting pump risk.",
                },
                actor="test",
            ),
            db,
        )
        assert logic_run.status == "ACTION_PROPOSED"
        assert logic_run.proposed_actions[0]["action_type_id"] == "escalate_work_order"

        eval_run = run_eval_suite("maintenance_ops_agent_eval", db)
        assert eval_run.status == "SUCCESS"
        assert eval_run.score == 100
        assert db.query(models_action.AuditLog).count() >= 10

        print("Maintenance copilot scenario passed")
    finally:
        db.close()
        engine.dispose()
        tmpdir.cleanup()


if __name__ == "__main__":
    main()
