"""Decision Intelligence project ownership migration is repeatable and recoverable."""
import os
import tempfile

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


temporary = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
database_url = f"sqlite:///{os.path.join(temporary.name, 'decision-project-scope.db')}"
config = Config(os.path.join(os.path.dirname(__file__), "alembic.ini"))
config.set_main_option("sqlalchemy.url", database_url)

command.upgrade(config, "0033_async_plugin_execution")
engine = create_engine(database_url)
with engine.begin() as connection:
    connection.execute(text("INSERT INTO object_types (id, project_id, display_name, description, properties, created_at, updated_at) VALUES ('alpha-asset', 'alpha', 'Asset', '', '{}', 1, 1)"))
    connection.execute(text("INSERT INTO object_instances (id, project_id, object_type_id, properties, source_asset_id, lineage, created_at, updated_at) VALUES ('alpha-object', 'alpha', 'alpha-asset', '{}', NULL, '{}', 1, 1)"))
    connection.execute(text("INSERT INTO decision_rules (id, display_name, description, object_type_id, expression, output_property, severity, recommended_actions, active, created_at, updated_at) VALUES ('alpha-rule', 'Rule', '', 'alpha-asset', '{}', NULL, 'high', '[]', 1, 1, 1)"))
    connection.execute(text("INSERT INTO decision_scorecards (id, display_name, description, object_type_id, features, thresholds, recommended_actions, active, created_at, updated_at) VALUES ('alpha-scorecard', 'Scorecard', '', 'alpha-asset', '[]', '{}', '[]', 1, 1, 1)"))
    connection.execute(text("INSERT INTO object_snapshots (id, object_id, object_type_id, properties, lineage, event_type, actor, source_type, source_id, created_at, seq) VALUES ('alpha-snapshot', 'alpha-object', 'alpha-asset', '{}', '{}', 'created', 'migration', NULL, NULL, 1, 1)"))
    connection.execute(text("INSERT INTO entity_resolution_jobs (id, object_type_id, fields, status, created_at, completed_at, candidate_count) VALUES ('alpha-job', 'alpha-asset', '[]', 'COMPLETED', 1, 1, 1)"))
    connection.execute(text("INSERT INTO entity_candidates (id, job_id, object_type_id, object_ids, score, reasons, status, merged_object_id, created_at, decided_at) VALUES ('alpha-candidate', 'alpha-job', 'alpha-asset', '[\"alpha-object\"]', 90, '[]', 'PENDING', NULL, 1, NULL)"))

for _ in range(2):
    command.upgrade(config, "head")

with engine.connect() as connection:
    assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0038_explicit_schema_baseline"
    for table in ("decision_rules", "decision_scorecards", "decision_runs", "object_snapshots", "entity_resolution_jobs", "entity_candidates", "decision_scenarios"):
        assert "project_id" in {column["name"] for column in inspect(connection).get_columns(table)}, table
        assert f"ix_{table}_project_id" in {index["name"] for index in inspect(connection).get_indexes(table)}, table
    for table, row_id in (
        ("decision_rules", "alpha-rule"),
        ("decision_scorecards", "alpha-scorecard"),
        ("object_snapshots", "alpha-snapshot"),
        ("entity_resolution_jobs", "alpha-job"),
        ("entity_candidates", "alpha-candidate"),
    ):
        project_id = connection.execute(text(f"SELECT project_id FROM {table} WHERE id = :id"), {"id": row_id}).scalar_one()
        assert project_id == "alpha", (table, project_id)

command.downgrade(config, "0033_async_plugin_execution")
with engine.connect() as connection:
    assert "project_id" not in {column["name"] for column in inspect(connection).get_columns("decision_rules")}

command.upgrade(config, "head")
with engine.connect() as connection:
    assert connection.execute(text("SELECT project_id FROM decision_rules WHERE id = 'alpha-rule'")).scalar_one() == "alpha"
    assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0038_explicit_schema_baseline"

engine.dispose()
temporary.cleanup()
print("Decision Intelligence project-scope migration verified.")
