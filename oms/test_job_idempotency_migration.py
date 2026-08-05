"""Alembic preserves legacy job idempotency evidence without duplicate scopes."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile


with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
    database_path = Path(tmpdir) / "legacy_jobs.db"
    payload = json.dumps({"kind": "report", "__execution": {"idempotency_key": "legacy-report-v1"}})
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY);
            INSERT INTO alembic_version (version_num) VALUES ('0012_artifact_receipts');
            CREATE TABLE platform_jobs (
                id VARCHAR NOT NULL PRIMARY KEY,
                project_id VARCHAR NOT NULL,
                job_type VARCHAR NOT NULL,
                actor VARCHAR NOT NULL,
                subject_type VARCHAR,
                subject_id VARCHAR,
                payload JSON NOT NULL,
                created_at INTEGER NOT NULL
            );
            """
        )
        connection.execute(
            "INSERT INTO platform_jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("legacy-job-first", "legacy-project", "report.generate", "legacy-user", "incident", "inc-1", payload, 10),
        )
        connection.execute(
            "INSERT INTO platform_jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("legacy-job-duplicate", "legacy-project", "report.generate", "legacy-user", "incident", "inc-1", payload, 11),
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
        connection.row_factory = sqlite3.Row
        version = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        receipts = connection.execute(
            "SELECT * FROM platform_job_idempotency_receipts ORDER BY created_at"
        ).fetchall()

    assert version == "0038_explicit_schema_baseline", version
    assert len(receipts) == 1, [dict(row) for row in receipts]
    receipt = receipts[0]
    assert receipt["job_id"] == "legacy-job-first" and receipt["project_id"] == "legacy-project"
    assert receipt["actor"] == "legacy-user" and receipt["idempotency_key"] == "legacy-report-v1"
    assert receipt["request_hash"] is None and len(receipt["scope_hash"]) == 64

print("\nJob idempotency migration verified: legacy duplicate scopes reconcile to one durable receipt.")
