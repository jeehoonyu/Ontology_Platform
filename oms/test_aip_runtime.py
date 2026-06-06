import os
import tempfile
import uuid

tmpdir = tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'aip_runtime.db')}"

from app import models, models_action, schemas  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.main import (  # noqa: E402
    add_thread_message,
    create_automation,
    create_action_type,
    create_agent,
    create_data_asset,
    create_eval_suite,
    create_logic_function,
    create_object_type,
    create_pipeline,
    create_thread,
    decide_approval,
    execute_action,
    extract_document,
    generate_pipeline_assist,
    generate_scheduler_cron,
    get_mcp_context,
    list_aip_tools,
    query_assist,
    run_automation,
    run_agent_session,
    run_eval_suite,
    run_logic_function,
    run_pipeline,
    transform_notepad,
)


models.Base.metadata.create_all(bind=engine)
models_action.Base.metadata.create_all(bind=engine)


def main():
    db = SessionLocal()
    try:
        create_object_type(
            schemas.ObjectTypeCreate(
                id="work_order",
                display_name="Work Order",
                description="Operational maintenance order",
                properties={
                    "title": {"type": "string", "required": True},
                    "status": {"type": "string", "required": True},
                    "priority": {"type": "string"},
                    "summary": {"type": "string"},
                },
            ),
            db,
        )

        create_data_asset(
            schemas.DataAssetCreate(
                id="raw_work_orders",
                display_name="Raw Work Orders",
                records=[
                    {
                        "id": "wo_1",
                        "title": "  Replace line pump   ",
                        "status": "OPEN",
                        "description": "Urgent pump issue affecting line 4 production throughput.",
                    },
                    {
                        "id": "wo_2",
                        "title": "Archive old report",
                        "status": "CLOSED",
                        "description": "No operational impact.",
                    },
                ],
            ),
            db,
        )

        create_pipeline(
            schemas.PipelineDefinitionCreate(
                id="hydrate_work_orders",
                display_name="Hydrate Work Orders",
                input_asset_id="raw_work_orders",
                steps=[
                    {"operation": "filter", "field": "status", "equals": "OPEN"},
                    {"operation": "normalize", "fields": ["title", "description"]},
                    {
                        "operation": "classify",
                        "field": "description",
                        "target_field": "priority",
                        "labels": {"high": ["urgent", "production"], "low": ["archive"]},
                        "default": "normal",
                    },
                    {
                        "operation": "summarize",
                        "field": "description",
                        "target_field": "summary",
                        "max_chars": 64,
                    },
                    {
                        "operation": "map_to_ontology",
                        "object_type_id": "work_order",
                        "object_id_field": "id",
                        "property_map": {
                            "title": "$title",
                            "status": "$status",
                            "priority": "$priority",
                            "summary": "$summary",
                        },
                    },
                ],
            ),
            db,
        )

        pipeline_run = run_pipeline("hydrate_work_orders", db=db)
        assert pipeline_run.status == "SUCCESS"
        assert pipeline_run.records_in == 2
        assert pipeline_run.records_out == 1

        work_order = db.query(models.ObjectInstance).filter_by(id="wo_1").first()
        assert work_order is not None
        assert work_order.properties["priority"] == "high"

        create_action_type(
            schemas.ActionTypeCreate(
                id="close_work_order",
                display_name="Close Work Order",
                parameters={
                    "work_order_id": {"type": "string", "required": True},
                    "resolution": {"type": "string", "required": True},
                },
                rules={
                    "requires_approval": True,
                    "risk_level": "high",
                    "object_mutations": [
                        {
                            "object_type_id": "work_order",
                            "object_id_param": "work_order_id",
                            "set": {"status": {"value": "CLOSED"}, "summary": "$resolution"},
                        }
                    ],
                },
            ),
            db,
        )

        create_agent(
            schemas.AgentDefinitionCreate(
                id="ops_agent",
                display_name="Operations Agent",
                allowed_object_types=["work_order"],
                allowed_actions=["close_work_order"],
                approval_required=True,
            ),
            db,
        )

        agent_session = run_agent_session(
            "ops_agent",
            schemas.AgentSessionCreate(user_prompt="Use close work order for the urgent pump issue"),
            db,
        )
        assert agent_session.status == "ACTION_PROPOSED"
        assert agent_session.proposed_actions[0]["action_type_id"] == "close_work_order"

        approval_response = execute_action(
            schemas.ActionExecutionRequest(
                action_type_id="close_work_order",
                parameters={"work_order_id": "wo_1", "resolution": "Pump replaced and verified."},
                idempotency_key=f"test-{uuid.uuid4()}",
                actor="ops_agent",
            ),
            db,
        )
        assert approval_response.status == "REQUIRES_APPROVAL"

        approved = decide_approval(
            approval_response.approval_request_id,
            schemas.ApprovalDecisionRequest(actor="supervisor", decision="APPROVED"),
            db,
        )
        assert approved.status == "APPROVED"

        idem_key = f"test-{uuid.uuid4()}"
        execution_response = execute_action(
            schemas.ActionExecutionRequest(
                action_type_id="close_work_order",
                parameters={"work_order_id": "wo_1", "resolution": "Pump replaced and verified."},
                idempotency_key=idem_key,
                actor="ops_agent",
                approval_request_id=approval_response.approval_request_id,
            ),
            db,
        )
        assert execution_response.status == "SUCCESS"
        assert execution_response.mutated_object_ids == ["wo_1"]

        cached_response = execute_action(
            schemas.ActionExecutionRequest(
                action_type_id="close_work_order",
                parameters={"work_order_id": "wo_1", "resolution": "Pump replaced and verified."},
                idempotency_key=idem_key,
                actor="ops_agent",
                approval_request_id=approval_response.approval_request_id,
            ),
            db,
        )
        assert cached_response.status == "SUCCESS_CACHED"
        assert cached_response.outbox_event_id == execution_response.outbox_event_id

        refreshed = db.query(models.ObjectInstance).filter_by(id="wo_1").first()
        assert refreshed.properties["status"] == "CLOSED"

        create_eval_suite(
            schemas.EvalSuiteCreate(
                id="ops_agent_eval",
                display_name="Operations Agent Eval",
                target_agent_id="ops_agent",
                cases=[
                    {
                        "id": "case_1",
                        "prompt": "Please close work order for pump issue",
                        "expected_actions": ["close_work_order"],
                        "expected_context_object_types": ["work_order"],
                    }
                ],
            ),
            db,
        )
        eval_run = run_eval_suite("ops_agent_eval", db)
        assert eval_run.status == "SUCCESS"
        assert eval_run.score == 100

        tools = list_aip_tools()
        tool_ids = {tool["id"] for tool in tools}
        assert {"aip_assist", "aip_logic", "aip_threads", "palantir_mcp", "document_intelligence"}.issubset(tool_ids)

        assist = query_assist(
            schemas.AssistRequest(prompt="Which AIP Logic and Thread tools can I use?"),
            db,
        )
        assert "aip_logic" in assist["referenced_tools"]
        assert assist["context_summary"]["tools"] >= 10

        mcp_context = get_mcp_context(db)
        assert mcp_context["summary"]["object_instances"] >= 1
        assert any(tool["id"] == "aip_chatbot_studio" for tool in mcp_context["tools"])

        pipeline_assist = generate_pipeline_assist(
            schemas.PipelineAssistRequest(
                prompt="Clean open records, classify priority, summarize, and hydrate ontology",
                sample_fields=["id", "status", "title", "description"],
            ),
            db,
        )
        assert any(step["operation"] == "map_to_ontology" for step in pipeline_assist["steps"])

        extraction = extract_document(
            schemas.DocumentExtractionRequest(
                text="Invoice: INV-100\nOwner: ops@example.com\nDue: 2026-07-01\nAmount: $1,250.00",
                extraction_schema={"invoice": {"pattern": r"Invoice:\s*(\S+)"}},
            ),
            db,
        )
        assert extraction["fields"]["invoice"] == "INV-100"
        assert "ops@example.com" in extraction["entities"]["emails"]

        notepad = transform_notepad(
            schemas.NotepadTransformRequest(text="teh adress needs review.", operation="spellcheck"),
            db,
        )
        assert "the address" in notepad["text"]

        cron = generate_scheduler_cron(schemas.SchedulerRequest(prompt="run every weekday morning"))
        assert cron["cron"] == "0 9 * * 1-5"

        thread = create_thread(
            schemas.ThreadCreate(title="Ops triage", owner="analyst", resources=[{"type": "object", "id": "wo_1"}]),
            db,
        )
        thread = add_thread_message(
            thread.id,
            schemas.ThreadMessageCreate(role="user", content="Show me the AIP Assist tools for this work order."),
            db,
        )
        assert len(thread.messages) == 2

        create_logic_function(
            schemas.LogicFunctionCreate(
                id="triage_logic",
                display_name="Triage Logic",
                blocks=[
                    {"type": "retrieve_context", "object_types": ["work_order"], "output": "context"},
                    {"type": "assist", "prompt": "$prompt", "output": "assist"},
                    {
                        "type": "propose_action",
                        "action_type_id": "close_work_order",
                        "parameters": {"work_order_id": "$work_order_id", "resolution": "$resolution"},
                    },
                ],
            ),
            db,
        )
        logic_run = run_logic_function(
            "triage_logic",
            schemas.LogicRunRequest(
                inputs={
                    "prompt": "close the work order",
                    "work_order_id": "wo_1",
                    "resolution": "Logic staged closure.",
                }
            ),
            db,
        )
        assert logic_run.status == "ACTION_PROPOSED"
        assert logic_run.proposed_actions[0]["action_type_id"] == "close_work_order"

        create_automation(
            schemas.AutomationDefinitionCreate(
                id="open_work_order_monitor",
                display_name="Open Work Order Monitor",
                condition={
                    "type": "object_count",
                    "object_type_id": "work_order",
                    "filters": {"status": "CLOSED"},
                    "operator": ">=",
                    "threshold": 1,
                },
                effect={
                    "type": "request_approval",
                    "action_type_id": "close_work_order",
                    "parameters": {"work_order_id": "wo_1", "resolution": "Automation review."},
                },
            ),
            db,
        )
        automation_run = run_automation("open_work_order_monitor", db=db)
        assert automation_run.status == "TRIGGERED"
        assert automation_run.effect_result["status"] == "APPROVAL_REQUESTED"

        outbox_count = db.query(models_action.OutboxEvent).count()
        audit_count = db.query(models_action.AuditLog).count()
        assert outbox_count == 1
        assert audit_count >= 10

        print("AIP runtime scenario passed")
    finally:
        db.close()
        engine.dispose()
        tmpdir.cleanup()


if __name__ == "__main__":
    main()
