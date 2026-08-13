"""Live REST/SQL adapters, encrypted credentials, cursors, SSRF, and plugins."""
import json
import os
import sqlite3
import tempfile
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
database_path = os.path.join(tmpdir.name, "platform.db")
external_path = os.path.join(tmpdir.name, "external.db")
os.environ["DATABASE_URL"] = f"sqlite:///{database_path}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"
os.environ["CONNECTOR_SECRET_KEY"] = "live-connector-test-key"
os.environ["CONNECTOR_ALLOW_PRIVATE_NETWORKS"] = "true"

with sqlite3.connect(external_path) as connection:
    connection.execute("CREATE TABLE external_assets (asset_id TEXT, updated_at INTEGER, status TEXT)")
    connection.executemany("INSERT INTO external_assets VALUES (?, ?, ?)", [("SQL-1", 1, "RUNNING"), ("SQL-2", 2, "DEGRADED")])


class Handler(BaseHTTPRequestHandler):
    token = "initial-secret"

    def log_message(self, *_args):
        return

    def do_GET(self):
        if self.path.startswith("/fail"):
            self.send_response(500)
            self.end_headers()
            return
        if self.headers.get("Authorization") != f"Bearer {self.token}":
            self.send_response(401)
            self.end_headers()
            return
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        after = int(query.get("after", ["0"])[0])
        records = [
            {"asset_id": "REST-1", "updated_at": 1, "status": "RUNNING"},
            {"asset_id": "REST-2", "updated_at": 2, "status": "DEGRADED"},
            {"asset_id": "REST-3", "updated_at": 3, "status": "CRITICAL"},
        ]
        selected = [row for row in records if row["updated_at"] > after]
        if after == 0:
            selected = selected[:2]
        body = json.dumps({"data": {"records": selected}, "next_cursor": max([row["updated_at"] for row in selected], default=after)}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()

from fastapi.testclient import TestClient  # noqa: E402
from app import connector_runtime, models  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
passed = 0


def ok(response, label, expect=200):
    global passed
    assert response.status_code == expect, f"{label}: {response.status_code} {response.text[:1400]}"
    passed += 1
    return response.json() if response.content else {}


with SessionLocal() as db:
    db.add_all([
        models.DataAsset(id="rest_target", display_name="REST Target", description=None, kind="dataset", asset_schema={}, records=[], file_ref=None, source_format=None, created_at=1, updated_at=1),
        models.DataAsset(id="failure_target", display_name="Failure Target", description=None, kind="dataset", asset_schema={}, records=[], file_ref=None, source_format=None, created_at=1, updated_at=1),
    ])
    db.commit()

base_url = f"http://127.0.0.1:{server.server_port}"
source = ok(client.post("/connections/sources", json={
    "id": "live_rest", "display_name": "Live REST", "source_type": "rest",
    "config": {
        "base_url": base_url, "endpoint": "/assets", "execution_mode": "live",
        "records_path": "data.records", "next_cursor_path": "next_cursor", "cursor_param": "after",
        "cursor_field": "updated_at", "batch_size": 50,
        "headers": {"Authorization": "must-not-be-used", "X-Client": "ontology-platform"},
    },
}), "create live REST source")
assert source["config"]["headers"]["Authorization"] == "***", source

credential = ok(client.post("/connections/sources/live_rest/runtime-credentials", json={
    "credential_type": "bearer", "secret": Handler.token, "metadata": {"purpose": "test"},
}), "store encrypted credential", 201)
assert "secret" not in credential and "encrypted_secret" not in credential, credential
with SessionLocal() as db:
    stored = db.get(connector_runtime.ConnectorCredential, credential["id"])
    assert Handler.token not in stored.encrypted_secret and connector_runtime._decrypt_secret(stored.encrypted_secret) == Handler.token
passed += 1

preview = ok(client.post("/connections/sources/live_rest/live-preview", json={"limit": 10}), "fetch authenticated live preview")
assert [row["asset_id"] for row in preview["preview_rows"]] == ["REST-1", "REST-2"] and preview["next_cursor"] == 2, preview

sync = ok(client.post("/connections/sources/live_rest/syncs", json={
    "id": "live_rest_sync", "target_asset_id": "rest_target", "mode": "incremental", "cursor_field": "updated_at",
}), "create live incremental sync")
first_job = ok(client.post("/ingestion/syncs/live_rest_sync/enqueue", json={"idempotency_key": "rest-live-1"}), "enqueue first live sync", 202)
first_run = ok(client.post("/ingestion/workers/run-next", json={"job_id": first_job["job"]["id"], "worker_id": "live-rest-worker"}), "run first live sync")
assert first_run["job"]["status"] == "SUCCEEDED" and first_run["run"]["records_out"] == 2, first_run
assert first_run["run"]["metrics"]["adapter_id"] == "rest" and first_run["run"]["metrics"]["next_cursor"] == 2, first_run

second_job = ok(client.post("/ingestion/syncs/live_rest_sync/enqueue", json={"idempotency_key": "rest-live-2"}), "enqueue second live sync", 202)
second_run = ok(client.post("/ingestion/workers/run-next", json={"job_id": second_job["job"]["id"], "worker_id": "live-rest-worker"}), "run second live sync")
assert second_run["run"]["records_out"] == 1 and second_run["run"]["metrics"]["previous_cursor"] == 2 and second_run["run"]["metrics"]["next_cursor"] == 3, second_run
cursor = ok(client.get("/connections/syncs/live_rest_sync/cursor"), "inspect durable live cursor")
assert cursor["last_value"] == 3 and cursor["runs"] == 2, cursor
with SessionLocal() as db:
    target = db.get(models.DataAsset, "rest_target")
    assert [row["asset_id"] for row in target.records] == ["REST-1", "REST-2", "REST-3"]
passed += 1

attempts = ok(client.get("/connections/sources/live_rest/fetch-attempts"), "inspect live fetch evidence")
assert len(attempts) == 3 and all(row["status"] == "SUCCEEDED" for row in attempts), attempts

ok(client.post("/connections/sources", json={
    "id": "failing_rest", "display_name": "Failing REST", "source_type": "rest",
    "config": {"base_url": base_url, "endpoint": "/fail", "execution_mode": "live", "records_path": "records"},
}), "create failing REST source")
ok(client.post("/connections/sources/failing_rest/syncs", json={"id": "failing_sync", "target_asset_id": "failure_target"}), "create failing sync")
failed_job = ok(client.post("/ingestion/syncs/failing_sync/enqueue", json={"idempotency_key": "rest-fail-1", "max_attempts": 2}), "enqueue failing sync", 202)
failed_run = ok(client.post("/ingestion/workers/run-next", json={"job_id": failed_job["job"]["id"], "worker_id": "live-rest-worker"}), "capture retryable fetch failure")
assert failed_run["job"]["status"] == "QUEUED" and failed_run["run"]["status"] == "RETRYING", failed_run
failure_attempts = ok(client.get("/connections/sources/failing_rest/fetch-attempts"), "inspect failed fetch evidence")
assert len(failure_attempts) == 1 and failure_attempts[0]["status"] == "FAILED" and "500" in failure_attempts[0]["error"], failure_attempts

os.environ["CONNECTOR_ALLOW_PRIVATE_NETWORKS"] = "false"
ok(client.post("/connections/sources/live_rest/live-preview", json={"limit": 1}), "deny private REST target", 403)
os.environ["CONNECTOR_ALLOW_PRIVATE_NETWORKS"] = "true"

sql_source = ok(client.post("/connections/sources", json={
    "id": "live_sql", "display_name": "Live SQL", "source_type": "jdbc",
    "config": {"sqlalchemy_url": f"sqlite:///{external_path}", "driver_class": "sqlite", "table": "external_assets", "execution_mode": "live", "cursor_field": "updated_at"},
}), "create SQL adapter source")
sql_preview = ok(client.post("/connections/sources/live_sql/live-preview", json={"limit": 10}), "query live SQL source")
assert [row["asset_id"] for row in sql_preview["preview_rows"]] == ["SQL-1", "SQL-2"] and sql_preview["metadata"]["backend"] == "sqlite", sql_preview

ok(client.post("/connections/sources", json={
    "id": "unsafe_sql", "display_name": "Unsafe SQL", "source_type": "jdbc",
    "config": {"sqlalchemy_url": f"sqlite:///{external_path}", "driver_class": "sqlite", "query": "DELETE FROM external_assets", "execution_mode": "live"},
}), "create unsafe SQL source")
ok(client.post("/connections/sources/unsafe_sql/live-preview", json={"limit": 10}), "reject mutating SQL connector query", 422)


class FixtureAdapter:
    id = "fixture_plugin"
    source_types = ["rest"]
    modes = ["snapshot"]

    def config_schema(self):
        return {"properties": {"fixture": {"type": "string"}}}

    def fetch(self, context):
        return connector_runtime.AdapterResult(records=[{"plugin": context.config.get("fixture")}], next_cursor="done", bytes_read=12, metadata={"plugin": True})


connector_runtime.register_adapter(FixtureAdapter())
catalog = ok(client.get("/connectors/adapters"), "inspect pluggable adapter catalog")
assert next(row for row in catalog["adapters"] if row["id"] == "fixture_plugin")["available"] is True, catalog
plugin_source = ok(client.post("/connections/sources", json={
    "id": "plugin_source", "display_name": "Plugin Source", "source_type": "rest",
    "config": {"adapter_id": "fixture_plugin", "fixture": "loaded", "execution_mode": "live", "base_url": "https://example.test"},
}), "create plugin source")
plugin_preview = ok(client.post("/connections/sources/plugin_source/live-preview", json={"limit": 5}), "execute plugin adapter")
assert plugin_preview["preview_rows"] == [{"plugin": "loaded"}] and plugin_preview["next_cursor"] == "done", plugin_preview

snapshot = ok(client.get("/project/export"), "export connector evidence")
assert snapshot["connector_fetch_attempts"] and "connector_credentials" not in snapshot, snapshot.keys()

print(f"\nLive connector runtime verified: {passed} assertions passed.")
server.shutdown()
server.server_close()
engine.dispose()
tmpdir.cleanup()
