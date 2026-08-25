"""Alembic preserves retained metadata receipts in the durable receipt table."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from tier_b_evidence import current_head


with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
    database_path = Path(tmpdir) / "legacy_receipts.db"
    metadata = {
        "command_receipts": [{
            "idempotency_key": "legacy-builder-command",
            "revision": 2,
            "command_ids": ["builder-command"],
            "created_at": 10,
        }],
        "collaboration_receipts": [{
            "idempotency_key": "legacy-collaboration-command",
            "revision": 3,
            "lock_version": 3,
            "participant_id": "legacy-participant",
            "command_ids": ["collaboration-command"],
            "rebased_from_lock_version": 1,
            "created_at": 11,
        }],
    }
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY);
            INSERT INTO alembic_version (version_num) VALUES ('0011_hashed_service_tokens');
            CREATE TABLE platform_artifacts (
                id VARCHAR NOT NULL PRIMARY KEY,
                project_id VARCHAR NOT NULL,
                current_revision INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                metadata JSON
            );
            """
        )
        connection.execute(
            "INSERT INTO platform_artifacts (id, project_id, current_revision, updated_at, metadata) VALUES (?, ?, ?, ?, ?)",
            ("legacy-artifact", "legacy-project", 3, 11, json.dumps(metadata)),
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
            "SELECT * FROM platform_artifact_command_receipts ORDER BY command_scope"
        ).fetchall()

    assert version == current_head(), version
    assert len(receipts) == 2, [dict(row) for row in receipts]
    builder, collaboration = receipts
    assert builder["command_scope"] == "builder" and builder["project_id"] == "legacy-project"
    assert builder["idempotency_key"] == "legacy-builder-command" and builder["request_hash"] is None
    assert collaboration["command_scope"] == "collaboration" and collaboration["lock_version"] == 3
    assert collaboration["participant_id"] == "legacy-participant" and collaboration["rebased_from_lock_version"] == 1

print("\nArtifact command receipt migration verified: retained legacy receipts were preserved.")
