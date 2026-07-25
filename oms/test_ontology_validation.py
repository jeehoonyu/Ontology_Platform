import os
import tempfile

from sqlalchemy import text

tmpdir = tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'ontology_validation.db')}"

from app import models, models_action, schemas  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.main import (  # noqa: E402
    aggregate_object_sets,
    bootstrap_maintenance_domain,
    create_link_instance,
    run_data_asset_expectations,
    search_around_object_set,
    search_object_sets,
    validate_ontology,
)


models.Base.metadata.create_all(bind=engine)
models_action.Base.metadata.create_all(bind=engine)


def main():
    db = SessionLocal()
    try:
        bootstrap = bootstrap_maintenance_domain(
            schemas.DomainBootstrapRequest(actor="validator_test", run_pipelines=True),
            db,
        )
        assert all(run["status"] == "SUCCESS" for run in bootstrap["pipeline_runs"])

        create_link_instance(
            schemas.LinkInstanceCreate(
                link_type_id="asset_has_work_order",
                source_object_id="asset_pump_4",
                target_object_id="wo_pump_urgent",
                properties={"confidence": 1.0, "source": "test"},
            ),
            db,
        )

        validation = validate_ontology(db)
        assert validation["status"] == "PASS"
        assert validation["summary"]["errors"] == 0
        assert validation["summary"]["checked"]["object_instances"] >= 7

        critical = search_object_sets(
            schemas.ObjectSetQuery(
                object_type_id="work_order",
                filters={"priority": "critical"},
                include_lineage=False,
            ),
            db,
        )
        assert critical["count"] == 1
        assert critical["objects"][0]["id"] == "wo_pump_urgent"
        assert "lineage" not in critical["objects"][0]

        aggregate = aggregate_object_sets(
            schemas.ObjectSetAggregateRequest(
                object_type_id="work_order",
                group_by="priority",
            ),
            db,
        )
        counts_by_priority = {group["group"]: group["count"] for group in aggregate["groups"]}
        assert counts_by_priority == {"critical": 1, "normal": 1}

        graph = search_around_object_set(
            schemas.ObjectSetSearchAroundRequest(
                object_ids=["asset_pump_4"],
                link_type_id="asset_has_work_order",
                direction="outgoing",
                target_object_type_id="work_order",
                depth=1,
            ),
            db,
        )
        node_ids = {node["id"] for node in graph["nodes"]}
        assert "asset_pump_4" in node_ids
        assert "wo_pump_urgent" in node_ids
        assert graph["edges"][0]["link_type_id"] == "asset_has_work_order"

        passing_expectations = run_data_asset_expectations(
            "maintenance_raw_work_orders",
            schemas.DataExpectationsRequest(
                expectations={
                    "row_count_min": 2,
                    "required_fields": ["id", "status", "title"],
                    "non_null": ["id", "status"],
                    "unique": ["id"],
                    "allowed_values": {"status": ["OPEN"]},
                    "type": {"id": "string", "status": "string", "title": "string"},
                }
            ),
            db,
        )
        assert passing_expectations["status"] == "PASS"
        assert passing_expectations["summary"]["failed"] == 0

        failing_expectations = run_data_asset_expectations(
            "maintenance_raw_work_orders",
            schemas.DataExpectationsRequest(expectations={"unique": ["status"]}),
            db,
        )
        assert failing_expectations["status"] == "FAIL"
        assert failing_expectations["summary"]["failure_count"] == 1

        # The validator must still detect corruption that originated outside the
        # application boundary, so bypass enforced FKs explicitly for this row.
        db.execute(text("PRAGMA foreign_keys=OFF"))
        db.execute(text("""
            INSERT INTO link_instances
                (id, link_type_id, source_object_id, target_object_id, properties, created_at)
            VALUES
                ('broken_asset_work_order_link', 'asset_has_work_order', 'asset_pump_4',
                 'missing_work_order', '{"source":"intentional_test_corruption"}', 0)
        """))
        db.commit()
        db.execute(text("PRAGMA foreign_keys=ON"))

        failed_validation = validate_ontology(db)
        assert failed_validation["status"] == "FAIL"
        assert any(
            issue["code"] == "link_missing_target_object"
            and issue["resource_id"] == "broken_asset_work_order_link"
            for issue in failed_validation["issues"]
        )

        print("Ontology validation and object-set scenario passed")
    finally:
        db.close()
        engine.dispose()
        tmpdir.cleanup()


if __name__ == "__main__":
    main()
