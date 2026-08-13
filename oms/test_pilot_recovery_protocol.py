"""Authenticated source markers and isolated RPO/RTO protocol behavior."""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

root = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
database_path = Path(root.name) / "pilot-recovery.db"
os.environ["DATABASE_URL"] = f"sqlite:///{database_path.as_posix()}"
os.environ["APP_ENV"] = "test"
os.environ["AUTH_MODE"] = "local"
os.environ["PILOT_RECOVERY_TOKEN"] = "pilot-recovery-test-token-abcdefghijklmnopqrstuvwxyz"
sys.path.insert(0, str(Path(__file__).resolve().parent))

import uvicorn  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.database import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.pilot_evidence import current_migration_head, load_journal  # noqa: E402
from recovery_probe_client import require_isolated_target  # noqa: E402
from rpo_sampler import observe, write_mark  # noqa: E402
from rto_rehearsal import load_rehearsals, record  # noqa: E402

HEAD = current_migration_head()
TOKEN = os.environ["PILOT_RECOVERY_TOKEN"]
AUTH = {"Authorization": f"Bearer {TOKEN}"}
passed = 0


def check(condition, label, payload=None):
    global passed
    assert condition, f"{label}: {payload}"
    passed += 1


with engine.begin() as connection:
    connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(128) PRIMARY KEY)"))
    connection.execute(text("INSERT INTO alembic_version(version_num) VALUES (:head)"), {"head": HEAD})

client = TestClient(app)
body = {
    "run_id": "api-contract",
    "sequence": 1,
    "written_at": 1_700_000_000,
    "project_id": "operations",
    "migration_head": HEAD,
}
check(client.post("/health/pilot-recovery/marks", json=body).status_code == 401,
      "marker rejects missing bearer")
saved_token = os.environ.pop("PILOT_RECOVERY_TOKEN")
check(client.post("/health/pilot-recovery/marks", json=body, headers=AUTH).status_code == 404,
      "recovery protocol is disabled without an explicit secret")
os.environ["PILOT_RECOVERY_TOKEN"] = "short"
os.environ["APP_ENV"] = "production"
check(client.post(
    "/health/pilot-recovery/marks", json=body,
    headers={"Authorization": "Bearer short"},
).status_code == 503, "production rejects a weak recovery secret")
os.environ["APP_ENV"] = "test"
os.environ["PILOT_RECOVERY_TOKEN"] = saved_token
created = client.post("/health/pilot-recovery/marks", json=body, headers=AUTH)
check(created.status_code == 200 and created.json()["sequence"] == 1,
      "marker writes through authenticated internal endpoint", created.text)
check(created.json()["database_migration_head"] == HEAD, "database head is explicit", created.json())
replayed = client.post("/health/pilot-recovery/marks", json=body, headers=AUTH)
check(replayed.status_code == 200, "identical marker replay is idempotent", replayed.text)
changed = dict(body, written_at=body["written_at"] + 1)
check(client.post("/health/pilot-recovery/marks", json=changed, headers=AUTH).status_code == 409,
      "marker identity cannot be reused with changed data")
highest = client.get(
    "/health/pilot-recovery/marks/api-contract/highest?project_id=operations", headers=AUTH,
)
check(highest.status_code == 200 and highest.json()["sequence"] == 1,
      "highest surviving marker is queryable", highest.text)


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


source_port = free_port()
server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=source_port, log_level="error"))
source_thread = threading.Thread(target=server.run, daemon=True)
source_thread.start()
deadline = time.time() + 10
while not server.started and time.time() < deadline:
    time.sleep(0.02)
check(server.started, "source API starts for the real HTTP protocol")
source_target = f"http://127.0.0.1:{source_port}"


class RecoveryHandler(BaseHTTPRequestHandler):
    survivor = {"sequence": 1, "written_at": 100}
    database_head = HEAD

    def _send(self, status, payload):
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _authorized(self):
        return self.headers.get("Authorization") == f"Bearer {TOKEN}"

    def do_GET(self):
        if self.path == "/health/ready":
            self._send(200, {"status": "READY"})
            return
        if "/health/pilot-recovery/marks/" in self.path and self.path.split("?", 1)[0].endswith("/highest"):
            if not self._authorized():
                self._send(401, {"detail": "unauthorized"})
                return
            self._send(200, {
                "run_id": "unused",
                "project_id": "operations",
                "kind": "mark",
                "sequence": self.survivor["sequence"],
                "written_at": self.survivor["written_at"],
                "migration_head": HEAD,
                "database_migration_head": self.database_head,
                "runtime_migration_head": HEAD,
            })
            return
        self._send(404, {})

    def do_POST(self):
        if self.path != "/health/pilot-recovery/write-probes":
            self._send(404, {})
            return
        if not self._authorized():
            self._send(401, {"detail": "unauthorized"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length) or b"{}")
        self._send(200, {
            "run_id": request["run_id"],
            "project_id": request["project_id"],
            "kind": "write_probe",
            "sequence": 1,
            "written_at": int(time.time()),
            "migration_head": HEAD,
            "database_migration_head": self.database_head,
            "runtime_migration_head": HEAD,
        })

    def log_message(self, *_args):
        return


recovery = ThreadingHTTPServer(("127.0.0.1", 0), RecoveryHandler)
recovery_thread = threading.Thread(target=recovery.serve_forever, daemon=True)
recovery_thread.start()
recovery_target = f"http://127.0.0.1:{recovery.server_port}"

try:
    try:
        require_isolated_target(source_target, source_target + "/")
        raise AssertionError("same target was accepted")
    except ValueError:
        passed += 1

    marks = Path(root.name) / "rpo-marks.jsonl"
    state = Path(root.name) / "rpo-state.json"
    samples = Path(root.name) / "rpo-samples.jsonl"
    first = write_mark(
        source_target, marks, state, project_id="operations", token=TOKEN, now=100,
    )
    second = write_mark(
        source_target, marks, state, project_id="operations", token=TOKEN, now=200,
    )
    check((first["sequence"], second["sequence"]) == (1, 2),
          "source marks advance monotonically", (first, second))
    check(len(load_journal(marks)) == 2, "source marks have a hash-chained local receipt")
    code = observe(
        source_target, recovery_target, marks, samples, "pre_backup",
        project_id="operations", token=TOKEN, now=300,
    )
    observation = load_journal(samples)[0]["payload"]
    check(code == 0 and observation["rpo_seconds"] == 100,
          "isolated restore reports the exact surviving recovery point", observation)

    RecoveryHandler.database_head = "stale_head"
    try:
        observe(
            source_target, recovery_target, marks, Path(root.name) / "stale.jsonl", "mid_cycle",
            project_id="operations", token=TOKEN, now=400,
        )
        raise AssertionError("stale restored database was accepted")
    except RuntimeError as error:
        check("migration mismatch" in str(error), "stale recovery head is rejected", str(error))
    RecoveryHandler.database_head = HEAD

    rehearsals = Path(root.name) / "rto-rehearsals.jsonl"
    args = argparse.Namespace(
        source_target=source_target,
        target=recovery_target,
        restore_command=f'"{sys.executable}" -c "pass"',
        trigger="unattended",
        project_id="operations",
        token_env="PILOT_RECOVERY_TOKEN",
        note="protocol test",
        rehearsals_file=str(rehearsals),
    )
    check(record(args) == 0, "RTO stops only after authenticated recovered-target write")
    recorded = load_rehearsals(rehearsals)
    check(len(recorded) == 1 and recorded[0]["recovered"] is True,
          "successful RTO evidence is durable", recorded)

    unsafe = argparse.Namespace(**{**vars(args), "target": source_target})
    try:
        record(unsafe)
        raise AssertionError("RTO accepted the source as recovery target")
    except ValueError:
        passed += 1
finally:
    recovery.shutdown()
    recovery.server_close()
    recovery_thread.join(timeout=2)
    server.should_exit = True
    source_thread.join(timeout=5)
    root.cleanup()

print(f"Pilot recovery protocol verified: {passed} assertions passed.")
