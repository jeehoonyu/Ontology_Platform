"""Alembic adds indexed project ownership to operational resources."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile


TABLES = (
    "ops_events", "ops_alert_rules", "ops_alert_events", "ops_incidents",
    "ops_runbooks", "ops_runbook_executions", "ops_notifications", "ops_sla_policies",
    "investigation_workspaces", "investigation_evidence", "investigation_hypotheses",
    "investigation_findings", "investigation_reports", "schedules", "builds",
    "wh_webhooks", "wh_executions", "wh_credentials", "wh_outbound_apps",
    "wh_listeners", "wh_listener_events",
)

CHILD_KEYS = {
    "ops_alert_events": ("event_id", "legacy-ops_events"),
    "ops_runbook_executions": ("runbook_id", "legacy-ops_runbooks"),
    "investigation_evidence": ("investigation_id", "legacy-investigation_workspaces"),
    "investigation_hypotheses": ("investigation_id", "legacy-investigation_workspaces"),
    "investigation_findings": ("investigation_id", "legacy-investigation_workspaces"),
    "investigation_reports": ("investigation_id", "legacy-investigation_workspaces"),
    "builds": ("schedule_id", "legacy-schedules"),
    "wh_executions": ("webhook_id", "legacy-wh_webhooks"),
    "wh_listener_events": ("listener_id", "legacy-wh_listeners"),
}

with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
    database_path = Path(tmpdir) / "legacy_operational_plane.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
        connection.execute("INSERT INTO alembic_version VALUES ('0020_project_semantic_plane')")
        for table_name in TABLES:
            if table_name == "ops_events":
                connection.execute("CREATE TABLE ops_events (id VARCHAR NOT NULL PRIMARY KEY, payload JSON)")
                connection.execute("INSERT INTO ops_events VALUES (?, ?)", ("legacy-ops_events", json.dumps({"project_id": "alpha"})))
            elif table_name in CHILD_KEYS:
                key, value = CHILD_KEYS[table_name]
                connection.execute(f"CREATE TABLE {table_name} (id VARCHAR NOT NULL PRIMARY KEY, {key} VARCHAR)")
                connection.execute(f"INSERT INTO {table_name} VALUES (?, ?)", (f"legacy-{table_name}", value))
            else:
                connection.execute(f"CREATE TABLE {table_name} (id VARCHAR NOT NULL PRIMARY KEY)")
                connection.execute(f"INSERT INTO {table_name} VALUES ('legacy-{table_name}')")

    env = dict(os.environ)
    env["DATABASE_URL"] = f"sqlite:///{database_path.as_posix()}"
    root = Path(__file__).resolve().parent
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(root / "alembic.ini"), "upgrade", "head"],
        cwd=root, env=env, capture_output=True, text=True, timeout=120, check=False,
    )
    assert completed.returncode == 0, f"{completed.stdout}\n{completed.stderr}"

    with sqlite3.connect(database_path) as connection:
        version = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        for table_name in TABLES:
            project_id = connection.execute(f"SELECT project_id FROM {table_name}").fetchone()[0]
            indexes = {row[1] for row in connection.execute(f"PRAGMA index_list('{table_name}')").fetchall()}
            expected = "alpha" if table_name in {"ops_events", "ops_alert_events"} else "default"
            assert project_id == expected, (table_name, project_id)
            assert f"ix_{table_name}_project_id" in indexes, (table_name, indexes)

    assert version == "0025_ontology_schema_registry", version

print("\nOperational plane project migration verified for 21 legacy tables.")
