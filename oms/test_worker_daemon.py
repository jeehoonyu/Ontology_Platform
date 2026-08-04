"""Hashed service tokens and independently deployable worker daemon."""
import hashlib
import json
import os
import socket
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'worker_daemon.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402
from app import admin_auth  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.worker_daemon import WorkerApi, WorkerConfig, WorkerDaemon  # noqa: E402
import uvicorn  # noqa: E402

client = TestClient(app)
passed = 0


def ok(response, label, expect=200):
    global passed
    assert response.status_code == expect, f"{label}: {response.status_code} {response.text[:1000]}"
    passed += 1
    return response.json() if response.content else {}


ok(client.post("/tenancy/bootstrap", json={"project_id": "worker-prod", "project_name": "Worker Production"}), "bootstrap worker project")
ok(client.post("/admin/service-accounts", json={"id": "worker-service", "display_name": "Production Worker", "organization_id": "local"}), "create worker service account", 201)
issued = ok(client.post("/admin/tokens", json={
    "principal_type": "service_account", "principal_id": "worker-service",
    "scopes": ["project:worker-prod:execute", "project:default:execute"], "ttl_seconds": 3600,
}), "issue one-time worker token", 201)
secret = issued["token"]
assert secret.startswith("tok_") and len(secret) >= 40, issued
passed += 1

with SessionLocal() as db:
    stored = db.get(admin_auth.ApiToken, issued["id"])
    assert stored.token == f"hashed:{stored.id}", stored.token
    assert stored.token_hash == hashlib.sha256(secret.encode()).hexdigest(), stored.token_hash
    assert secret not in stored.token and stored.token_prefix == secret[:12]
    passed += 1

listed = ok(client.get("/admin/tokens?principal_id=worker-service"), "list safe token metadata")
assert listed[0]["token_prefix"] == secret[:12] and "token" not in listed[0] and "token_hash" not in listed[0], listed
passed += 1

queued = ok(client.post("/jobs", json={
    "project_id": "worker-prod", "job_type": "pipeline.preview", "payload": {"probe": True},
}), "queue worker-token claim probe", 201)

os.environ["AUTH_MODE"] = "oidc"
headers = {"Authorization": f"Bearer {secret}"}
registered = ok(client.put("/runtime/workers/prod-worker", headers=headers, json={
    "project_id": "worker-prod", "supported_job_types": ["pipeline.preview", "aip.agent.invoke"],
    "max_concurrency": 2, "labels": {"runtime": "acceptance"},
}), "register through service-token middleware")
assert registered["principal_id"] == "worker-service" and registered["project_id"] == "worker-prod", registered
passed += 1
ok(client.post("/runtime/workers/prod-worker/heartbeat", headers=headers, json={}), "heartbeat through execute-only token")
claimed = ok(client.post("/jobs/claim", headers=headers, json={
    "worker_id": "prod-worker", "supported_job_types": ["pipeline.preview"], "project_id": "worker-prod",
}), "claim through execute-only token")["job"]
assert claimed["id"] == queued["id"], claimed
passed += 1
ok(client.post(f"/jobs/{claimed['id']}/complete", headers=headers, json={
    "lease_token": claimed["lease_token"], "result": {"probe": "complete"},
}), "complete through execute-only token")
plugin_callback = client.post("/api/v1/plugins/workers/work", headers=headers, json={
    "job_id": "missing-plugin-job", "lease_token": "missing-lease",
})
assert plugin_callback.status_code == 404, plugin_callback.text
passed += 1
ok(client.get("/runtime/workers", headers=headers), "execute-only worker token cannot list fleet", 403)
os.environ["AUTH_MODE"] = "local"


class ProbeHandler(BaseHTTPRequestHandler):
    authorization = None

    def do_POST(self):
        ProbeHandler.authorization = self.headers.get("authorization")
        raw = json.dumps({"ok": True}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *_args):
        return


probe = ThreadingHTTPServer(("127.0.0.1", 0), ProbeHandler)
threading.Thread(target=probe.serve_forever, daemon=True).start()
probe_config = WorkerConfig(
    api_url=f"http://127.0.0.1:{probe.server_port}", token=secret, worker_name="probe",
    project_id="worker-prod", supported_job_types=["pipeline.preview"], health_port=8098,
)
assert WorkerApi(probe_config).request("POST", "/probe", {}) == {"ok": True}
assert ProbeHandler.authorization == f"Bearer {secret}"
passed += 2
probe.shutdown()
probe.server_close()


class FakeApi:
    def __init__(self):
        self.calls = []
        self.seen = set()
        self.lock = threading.Lock()

    def request(self, method, path, body=None):
        with self.lock:
            self.calls.append((method, path, body or {}))
            if path.endswith("/run-next") and path not in self.seen:
                self.seen.add(path)
                return {"job": {"id": f"job-{len(self.seen)}", "status": "SUCCEEDED"}}
            if path.endswith("/run-next"):
                return {"job": None}
            return {"status": "ACTIVE"}


with socket.socket() as health_socket:
    health_socket.bind(("127.0.0.1", 0))
    health_port = health_socket.getsockname()[1]
daemon_config = WorkerConfig(
    api_url="http://api.invalid", token=secret, worker_name="daemon-worker", project_id="worker-prod",
    supported_job_types=["pipeline.preview", "pipeline.deliver", "aip.agent.invoke", "ingestion.connector_sync", "ingestion.stream_replay"],
    max_concurrency=2, poll_interval_seconds=0.01, heartbeat_interval_seconds=0.02, health_host="127.0.0.1", health_port=health_port,
)
fake = FakeApi()
daemon = WorkerDaemon(daemon_config, api=fake)
snapshot = daemon.run(max_cycles=8)
paths = [path for _method, path, _body in fake.calls]
assert "/pipeline-builder/workers/run-next" in paths
assert "/aip/agents/workers/run-next" in paths
assert "/ingestion/workers/run-next" in paths
assert paths[0] == "/runtime/workers/daemon-worker" and paths[-1] == "/runtime/workers/daemon-worker/drain", paths
assert snapshot["jobs_seen"] == 3 and snapshot["jobs_succeeded"] == 3 and snapshot["api_errors"] == 0, snapshot
passed += 5

with socket.socket() as health_socket:
    health_socket.bind(("127.0.0.1", 0))
    live_health_port = health_socket.getsockname()[1]
live_config = WorkerConfig(
    api_url="http://api.invalid", token=secret, worker_name="health-worker", project_id="worker-prod",
    supported_job_types=["pipeline.preview"], max_concurrency=1, poll_interval_seconds=0.02,
    heartbeat_interval_seconds=0.02, health_host="127.0.0.1", health_port=live_health_port,
)
live_daemon = WorkerDaemon(live_config, api=FakeApi())
live_thread = threading.Thread(target=live_daemon.run)
live_thread.start()
deadline = time.time() + 3
while not live_daemon.registered and time.time() < deadline:
    time.sleep(0.01)
with urllib.request.urlopen(f"http://127.0.0.1:{live_health_port}/health/ready", timeout=2) as response:
    health = json.loads(response.read())
assert response.status == 200 and health["status"] == "READY", health
live_daemon.request_stop()
live_thread.join(timeout=3)
assert not live_thread.is_alive()
passed += 2


class RevokedApi(FakeApi):
    def request(self, method, path, body=None):
        if path.endswith("/run-next"):
            from app.worker_daemon import WorkerApiError
            raise WorkerApiError(401, "revoked")
        return super().request(method, path, body)


with socket.socket() as health_socket:
    health_socket.bind(("127.0.0.1", 0))
    revoked_port = health_socket.getsockname()[1]
revoked_daemon = WorkerDaemon(WorkerConfig(
    api_url="http://api.invalid", token=secret, worker_name="revoked-worker", project_id="worker-prod",
    supported_job_types=["pipeline.preview"], max_concurrency=1, health_host="127.0.0.1", health_port=revoked_port,
), api=RevokedApi())
revoked_snapshot = revoked_daemon.run()
assert revoked_snapshot["api_errors"] == 1 and "401" in revoked_snapshot["last_error"], revoked_snapshot
passed += 1

asset_id = "worker-daemon-input"
graph_id = "worker-daemon-pipeline"
ok(client.post("/data-assets", json={
    "id": asset_id, "display_name": "Worker daemon input", "kind": "dataset", "asset_schema": {},
    "records": [{"id": "a1", "risk": 91}, {"id": "a2", "risk": 20}],
}), "create daemon input")
ok(client.post("/pipeline-builder/graphs", json={
    "id": graph_id, "display_name": "Worker daemon pipeline",
    "nodes": [
        {"id": "input", "type": "input_dataset", "config": {"asset_id": asset_id}},
        {"id": "filter", "type": "filter", "config": {"field": "risk", "operator": "gte", "value": 80}},
    ],
    "edges": [{"source": "input", "target": "filter"}],
}), "create daemon pipeline", 201)
queued = ok(client.post(f"/pipeline-builder/graphs/{graph_id}/preview/async", json={
    "limit": 10, "idempotency_key": "worker-daemon-e2e",
}), "queue daemon pipeline preview", 202)

with socket.socket() as api_socket, socket.socket() as health_socket:
    api_socket.bind(("127.0.0.1", 0))
    api_port = api_socket.getsockname()[1]
    health_socket.bind(("127.0.0.1", 0))
    e2e_health_port = health_socket.getsockname()[1]
server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=api_port, log_level="error"))
server_thread = threading.Thread(target=server.run)
server_thread.start()
deadline = time.time() + 5
while not server.started and time.time() < deadline:
    time.sleep(0.01)
assert server.started
try:
    os.environ["AUTH_MODE"] = "oidc"
    e2e_daemon = WorkerDaemon(WorkerConfig(
        api_url=f"http://127.0.0.1:{api_port}", token=secret, worker_name="pipeline-e2e-worker",
        project_id="default", supported_job_types=["pipeline.preview"], max_concurrency=1,
        poll_interval_seconds=0.02, heartbeat_interval_seconds=20, request_timeout_seconds=30,
        health_host="127.0.0.1", health_port=e2e_health_port,
    ))
    e2e_snapshot = e2e_daemon.run(max_cycles=2)
    os.environ["AUTH_MODE"] = "local"
    completed = ok(client.get(f"/jobs/{queued['id']}"), "inspect daemon-completed pipeline job")
    assert completed["status"] == "SUCCEEDED" and e2e_snapshot["jobs_succeeded"] == 1, (completed, e2e_snapshot)
    assert completed["result"]["row_count"] == 1, completed["result"]
    passed += 2
finally:
    os.environ["AUTH_MODE"] = "local"
    server.should_exit = True
    server_thread.join(timeout=5)
    assert not server_thread.is_alive()

print(f"\nWorker daemon and hashed service tokens verified: {passed} assertions passed.")
engine.dispose()
tmpdir.cleanup()
