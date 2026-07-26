"""Alembic upgrades legacy Agent Studio runs with durable execution evidence."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile


with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
    database_path = Path(tmpdir) / "legacy_agent.db"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY);
            INSERT INTO alembic_version (version_num) VALUES ('0003_platform_job_leases');
            CREATE TABLE agent_tool_runs (
                id VARCHAR NOT NULL PRIMARY KEY,
                agent_id VARCHAR NOT NULL,
                prompt VARCHAR NOT NULL,
                tool_calls JSON,
                proposed_actions JSON,
                answer VARCHAR,
                created_at INTEGER NOT NULL
            );
            INSERT INTO agent_tool_runs (
                id, agent_id, prompt, tool_calls, proposed_actions, answer, created_at
            ) VALUES (
                'legacy-run', 'legacy-agent', 'inspect', '[]', '[]', 'legacy answer', 1
            );
            """
        )

    env = dict(os.environ)
    env["DATABASE_URL"] = f"sqlite:///{database_path.as_posix()}"
    root = Path(__file__).resolve().parent
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(root / "alembic.ini"), "upgrade", "head"],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, f"{completed.stdout}\n{completed.stderr}"

    with sqlite3.connect(database_path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(agent_tool_runs)")}
        version = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        legacy = connection.execute("SELECT id, answer FROM agent_tool_runs WHERE id = 'legacy-run'").fetchone()
        indexes = {row[1] for row in connection.execute("PRAGMA index_list(agent_tool_runs)")}
        token_columns = {row[1] for row in connection.execute("PRAGMA table_info(admin_api_tokens)")}

    assert {"retrieval", "policy_summary", "execution_job_id"} <= columns, columns
    assert version == "0012_artifact_receipts", version
    assert legacy == ("legacy-run", "legacy answer"), legacy
    assert "ix_agent_tool_runs_execution_job_id" in indexes, indexes
    assert {"platform_artifact_collaborators", "platform_artifact_collaboration_events"} <= tables, tables
    assert "platform_artifact_command_receipts" in tables, tables
    assert {"platform_organizations", "platform_projects", "platform_project_memberships", "ontology_packages", "ontology_package_versions", "ontology_package_installations", "ontology_package_resources"} <= tables, tables
    assert {"ingestion_runs", "ingestion_budgets", "ingestion_dead_letters"} <= tables, tables
    assert {"runtime_job_observations", "runtime_budget_policies", "runtime_slo_policies", "runtime_slo_evaluations"} <= tables, tables
    assert {"runtime_workers", "runtime_queue_policies"} <= tables, tables
    assert {"connector_credentials", "connector_fetch_attempts"} <= tables, tables
    assert {"token_hash", "token_prefix", "last_used_at"} <= token_columns, token_columns

print("\nAgent execution migration verified: legacy evidence preserved and schema upgraded.")
