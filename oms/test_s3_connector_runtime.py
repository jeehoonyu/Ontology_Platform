"""Live S3-compatible ingestion with SigV4, cursors, limits, and secret isolation."""
import json
import hashlib
import hmac
import os
import tempfile
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 's3.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"
os.environ["CONNECTOR_SECRET_KEY"] = "s3-connector-test-key"
os.environ["CONNECTOR_ALLOW_PRIVATE_NETWORKS"] = "true"


OBJECTS = {
    "data/001.jsonl": b'{"asset_id":"S3-1","status":"RUNNING"}\n{"asset_id":"S3-2","status":"DEGRADED"}\n',
    "data/002.csv": b"asset_id,status\r\nS3-3,RUNNING\r\n",
    "data/003.json": json.dumps({"asset_id": "S3-4", "status": "CRITICAL"}).encode(),
}


def valid_signature(handler) -> bool:
    authorization = handler.headers.get("Authorization", "")
    if not authorization.startswith("AWS4-HMAC-SHA256 "):
        return False
    try:
        fields = dict(part.strip().split("=", 1) for part in authorization.removeprefix("AWS4-HMAC-SHA256 ").split(","))
        access_key, date_stamp, region, service, terminal = fields["Credential"].split("/")
        if access_key != "AKIA_TEST" or service != "s3" or terminal != "aws4_request":
            return False
        parsed = urllib.parse.urlsplit(handler.path)
        canonical_query = "&".join(
            f"{urllib.parse.quote(key, safe='-_.~')}={urllib.parse.quote(value, safe='-_.~')}"
            for key, value in sorted(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
        )
        signed_headers = fields["SignedHeaders"]
        canonical_headers = "".join(f"{name}:{handler.headers.get(name, '').strip()}\n" for name in signed_headers.split(";"))
        payload_hash = handler.headers.get("x-amz-content-sha256", "")
        canonical_request = "\n".join(["GET", parsed.path, canonical_query, canonical_headers, signed_headers, payload_hash])
        amz_date = handler.headers["x-amz-date"]
        scope = f"{date_stamp}/{region}/s3/aws4_request"
        string_to_sign = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical_request.encode()).hexdigest()])
        key_date = hmac.new(b"AWS4fixture-secret-access-key", date_stamp.encode(), hashlib.sha256).digest()
        key_region = hmac.new(key_date, region.encode(), hashlib.sha256).digest()
        key_service = hmac.new(key_region, b"s3", hashlib.sha256).digest()
        signing_key = hmac.new(key_service, b"aws4_request", hashlib.sha256).digest()
        expected = hmac.new(signing_key, string_to_sign.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, fields["Signature"])
    except (KeyError, ValueError):
        return False


class S3FixtureHandler(BaseHTTPRequestHandler):
    signed_requests = []

    def log_message(self, *_args):
        return

    def do_GET(self):
        authorization = self.headers.get("Authorization", "")
        if not valid_signature(self):
            self.send_response(403)
            self.end_headers()
            return
        if self.headers.get("x-amz-security-token") != "fixture-session":
            self.send_response(403)
            self.end_headers()
            return
        self.signed_requests.append({"path": self.path, "authorization": authorization})
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path == "/operations-bucket":
            query = urllib.parse.parse_qs(parsed.query)
            prefix = query.get("prefix", [""])[0]
            start_after = query.get("start-after", [""])[0]
            max_keys = int(query.get("max-keys", ["100"])[0])
            keys = [key for key in sorted(OBJECTS) if key.startswith(prefix) and key > start_after][:max_keys]
            contents = "".join(
                f"<Contents><Key>{key}</Key><ETag>&quot;etag-{index}&quot;</ETag><Size>{len(OBJECTS[key])}</Size></Contents>"
                for index, key in enumerate(keys, 1)
            )
            body = f'<?xml version="1.0" encoding="UTF-8"?><ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">{contents}</ListBucketResult>'.encode()
            self.send_response(200)
            self.send_header("content-type", "application/xml")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        key = urllib.parse.unquote(parsed.path.removeprefix("/operations-bucket/"))
        body = OBJECTS.get(key)
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


server = ThreadingHTTPServer(("127.0.0.1", 0), S3FixtureHandler)
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
    assert response.status_code == expect, f"{label}: {response.status_code} {response.text[:1600]}"
    passed += 1
    return response.json() if response.content else {}


with SessionLocal() as db:
    db.add(models.DataAsset(
        id="s3_target", display_name="S3 Target", description=None, kind="dataset",
        asset_schema={}, records=[], file_ref=None, source_format=None, created_at=1, updated_at=1,
    ))
    db.commit()

catalog = ok(client.get("/connectors/adapters"), "connector catalog")
adapters = {row["id"]: row for row in catalog["adapters"]}
assert adapters["s3"]["available"] is True and adapters["sftp"]["available"] is True and adapters["kafka"]["available"] is True
assert adapters["s3"]["config_schema"]["incremental_cursor_field"] == "_source_object_key"

endpoint = f"http://127.0.0.1:{server.server_port}"
source = ok(client.post("/connections/sources", json={
    "id": "live_s3", "display_name": "Live S3", "source_type": "s3",
    "config": {
        "bucket": "operations-bucket", "region": "us-west-2", "endpoint_url": endpoint,
        "prefix": "data/", "format": "auto", "max_objects": 2, "max_records": 10,
        "execution_mode": "live", "batch_size": 2,
    },
}), "create S3 source")
assert "credential" not in source["config"]

ok(client.post("/connections/sources/live_s3/live-preview", json={"limit": 2}), "reject preview without credential", 422)
credential = ok(client.post("/connections/sources/live_s3/runtime-credentials", json={
    "credential_type": "aws", "secret": "fixture-secret-access-key",
    "metadata": {"access_key_id": "AKIA_TEST", "session_token": "fixture-session"},
}), "store AWS credential", 201)
assert "secret" not in credential and "encrypted_secret" not in credential
assert credential["metadata"] == {"access_key_id": "AKIA_TEST"}
with SessionLocal() as db:
    stored = db.get(connector_runtime.ConnectorCredential, credential["id"])
    assert "fixture-secret" not in stored.encrypted_secret
    assert "fixture-session" not in json.dumps(stored.metadata_)
passed += 1

preview = ok(client.post("/connections/sources/live_s3/live-preview", json={"limit": 2}), "preview signed S3 source")
assert [row["asset_id"] for row in preview["preview_rows"]] == ["S3-1", "S3-2", "S3-3"], preview
assert preview["next_cursor"] == "data/002.csv" and preview["metadata"]["objects_read"] == 2

ok(client.post("/connections/sources/live_s3/syncs", json={
    "id": "live_s3_sync", "target_asset_id": "s3_target", "mode": "incremental", "cursor_field": "_source_object_key",
}), "create incremental S3 sync")
first = ok(client.post("/ingestion/syncs/live_s3_sync/enqueue", json={"idempotency_key": "s3-1"}), "enqueue first S3 sync", 202)
first_run = ok(client.post("/ingestion/workers/run-next", json={"job_id": first["job"]["id"], "worker_id": "s3-worker"}), "execute first S3 sync")
assert first_run["run"]["records_out"] == 3 and first_run["run"]["metrics"]["next_cursor"] == "data/002.csv", first_run

second = ok(client.post("/ingestion/syncs/live_s3_sync/enqueue", json={"idempotency_key": "s3-2"}), "enqueue second S3 sync", 202)
second_run = ok(client.post("/ingestion/workers/run-next", json={"job_id": second["job"]["id"], "worker_id": "s3-worker"}), "execute second S3 sync")
assert second_run["run"]["records_out"] == 1 and second_run["run"]["metrics"]["previous_cursor"] == "data/002.csv"
assert second_run["run"]["metrics"]["next_cursor"] == "data/003.json"

with SessionLocal() as db:
    target = db.get(models.DataAsset, "s3_target")
    assert [row["asset_id"] for row in target.records] == ["S3-1", "S3-2", "S3-3", "S3-4"]
    assert all(row["_source_object_key"].startswith("data/") for row in target.records)
passed += 1

attempts = ok(client.get("/connections/sources/live_s3/fetch-attempts"), "inspect S3 fetch evidence")
assert len(attempts) == 4 and all(row["adapter_id"] == "s3" for row in attempts)
assert [row["status"] for row in attempts].count("FAILED") == 1
assert all("secret" not in json.dumps(row).lower() for row in attempts)
assert len(S3FixtureHandler.signed_requests) == 8
assert all("fixture-secret-access-key" not in row["authorization"] for row in S3FixtureHandler.signed_requests)

ok(client.post("/connections/sources/live_s3/runtime-credentials", json={
    "credential_type": "aws", "secret": "replacement", "metadata": {},
}), "reject AWS credential without access key", 422)
credential_rows = ok(client.get("/connections/sources/live_s3/runtime-credentials"), "keep active credential after rejected rotation")
assert len([row for row in credential_rows if row["status"] == "ACTIVE"]) == 1

os.environ["CONNECTOR_ALLOW_PRIVATE_NETWORKS"] = "false"
ok(client.post("/connections/sources/live_s3/live-preview", json={"limit": 1}), "deny private S3 endpoint", 403)
os.environ["CONNECTOR_ALLOW_PRIVATE_NETWORKS"] = "true"

ok(client.post("/connections/sources", json={
    "id": "bounded_s3", "display_name": "Bounded S3", "source_type": "s3",
    "config": {
        "bucket": "operations-bucket", "region": "us-west-2", "endpoint_url": endpoint,
        "prefix": "data/", "format": "auto", "max_objects": 1, "max_records": 1, "execution_mode": "live",
    },
}), "create bounded S3 source")
ok(client.post("/connections/sources/bounded_s3/runtime-credentials", json={
    "credential_type": "aws", "secret": "fixture-secret-access-key",
    "metadata": {"access_key_id": "AKIA_TEST", "session_token": "fixture-session"},
}), "store bounded source credential", 201)
ok(client.post("/connections/sources/bounded_s3/live-preview", json={"limit": 1}), "reject oversized S3 record batch", 413)
bounded_attempts = ok(client.get("/connections/sources/bounded_s3/fetch-attempts"), "persist bounded fetch failure")
assert len(bounded_attempts) == 1 and bounded_attempts[0]["status"] == "FAILED"

snapshot = ok(client.get("/project/export"), "export S3 project snapshot")
assert "connector_credentials" not in snapshot
assert "fixture-secret-access-key" not in json.dumps(snapshot)

print(f"S3 connector runtime verified: {passed} assertions passed.")
server.shutdown()
server.server_close()
engine.dispose()
tmpdir.cleanup()
