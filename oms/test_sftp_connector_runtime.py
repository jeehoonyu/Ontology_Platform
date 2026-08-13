"""Pinned-host SFTP ingestion over a real Paramiko SSH/SFTP protocol server."""
import io
import json
import logging
import os
import posixpath
import socket
import tempfile
import threading
import time

import paramiko

logging.getLogger("paramiko.transport").setLevel(logging.CRITICAL)

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
root = os.path.join(tmpdir.name, "sftp-root")
upload = os.path.join(root, "upload")
os.makedirs(upload)
with open(os.path.join(upload, "001.jsonl"), "w", encoding="utf-8") as handle:
    handle.write('{"asset_id":"SFTP-1","status":"RUNNING"}\n{"asset_id":"SFTP-2","status":"DEGRADED"}\n')
with open(os.path.join(upload, "002.csv"), "w", encoding="utf-8", newline="") as handle:
    handle.write("asset_id,status\r\nSFTP-3,RUNNING\r\n")
with open(os.path.join(upload, "003.json"), "w", encoding="utf-8") as handle:
    json.dump({"asset_id": "SFTP-4", "status": "CRITICAL"}, handle)

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'sftp.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"
os.environ["CONNECTOR_SECRET_KEY"] = "sftp-connector-test-key"
os.environ["CONNECTOR_ALLOW_PRIVATE_NETWORKS"] = "true"

SERVER_KEY = paramiko.RSAKey.generate(2048)
USER_KEY = paramiko.RSAKey.generate(2048)


class AuthServer(paramiko.ServerInterface):
    def check_auth_password(self, username, password):
        return paramiko.AUTH_SUCCESSFUL if username == "operator" and password == "fixture-password" else paramiko.AUTH_FAILED

    def check_auth_publickey(self, username, key):
        return paramiko.AUTH_SUCCESSFUL if username == "operator" and key.asbytes() == USER_KEY.asbytes() else paramiko.AUTH_FAILED

    def get_allowed_auths(self, _username):
        return "password,publickey"

    def check_channel_request(self, kind, _channel_id):
        return paramiko.OPEN_SUCCEEDED if kind == "session" else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED


class FixtureSFTP(paramiko.SFTPServerInterface):
    def _local(self, path):
        relative = posixpath.normpath(path).lstrip("/")
        candidate = os.path.realpath(os.path.join(root, *relative.split("/")))
        if os.path.commonpath([os.path.realpath(root), candidate]) != os.path.realpath(root):
            raise OSError(13, "path outside fixture root")
        return candidate

    def stat(self, path):
        try:
            return paramiko.SFTPAttributes.from_stat(os.stat(self._local(path)))
        except OSError as exc:
            return paramiko.SFTPServer.convert_errno(exc.errno)

    lstat = stat

    def list_folder(self, path):
        try:
            rows = []
            local = self._local(path)
            for filename in os.listdir(local):
                attributes = paramiko.SFTPAttributes.from_stat(os.stat(os.path.join(local, filename)))
                attributes.filename = filename
                rows.append(attributes)
            return rows
        except OSError as exc:
            return paramiko.SFTPServer.convert_errno(exc.errno)

    def open(self, path, flags, attr):
        try:
            file_object = open(self._local(path), "rb")
            handle = paramiko.SFTPHandle(flags)
            handle.readfile = file_object
            return handle
        except OSError as exc:
            return paramiko.SFTPServer.convert_errno(exc.errno)


listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
listener.bind(("127.0.0.1", 0))
listener.listen(10)
listener.settimeout(0.2)
stop_server = threading.Event()


def serve():
    while not stop_server.is_set():
        try:
            client_socket, _ = listener.accept()
        except socket.timeout:
            continue
        except OSError:
            if stop_server.is_set():
                break
            raise
        transport = paramiko.Transport(client_socket)
        transport.add_server_key(SERVER_KEY)
        transport.set_subsystem_handler("sftp", paramiko.SFTPServer, FixtureSFTP)
        try:
            try:
                transport.start_server(server=AuthServer())
                while transport.is_active() and not stop_server.wait(0.05):
                    pass
            except (EOFError, OSError, paramiko.SSHException):
                pass
        finally:
            transport.close()


server_thread = threading.Thread(target=serve, daemon=True)
server_thread.start()

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
        id="sftp_target", display_name="SFTP Target", description=None, kind="dataset",
        asset_schema={}, records=[], file_ref=None, source_format=None, created_at=1, updated_at=1,
    ))
    db.commit()

catalog = ok(client.get("/connectors/adapters"), "connector catalog")
adapters = {row["id"]: row for row in catalog["adapters"]}
assert adapters["sftp"]["available"] is True and adapters["kafka"]["available"] is True
assert adapters["sftp"]["config_schema"]["incremental_cursor_field"] == "_source_file_path"

fingerprint = connector_runtime._host_key_fingerprint(SERVER_KEY)
port = listener.getsockname()[1]
source_config = {
    "host": "127.0.0.1", "port": port, "username": "operator", "remote_path": "/upload",
    "host_key_sha256": fingerprint, "format": "auto", "max_files": 2, "max_records": 10,
    "execution_mode": "live", "batch_size": 2,
}
ok(client.post("/connections/sources", json={
    "id": "live_sftp", "display_name": "Live SFTP", "source_type": "sftp", "config": source_config,
}), "create SFTP source")
ok(client.post("/connections/sources/live_sftp/live-preview", json={"limit": 2}), "reject preview without credential", 422)
credential = ok(client.post("/connections/sources/live_sftp/runtime-credentials", json={
    "credential_type": "sftp_password", "secret": "fixture-password", "metadata": {},
}), "store SFTP password", 201)
assert "secret" not in credential and "encrypted_secret" not in credential
with SessionLocal() as db:
    stored = db.get(connector_runtime.ConnectorCredential, credential["id"])
    assert "fixture-password" not in stored.encrypted_secret
passed += 1

preview = ok(client.post("/connections/sources/live_sftp/live-preview", json={"limit": 2}), "preview pinned SFTP source")
assert [row["asset_id"] for row in preview["preview_rows"]] == ["SFTP-1", "SFTP-2", "SFTP-3"], preview
assert preview["next_cursor"] == "/upload/002.csv" and preview["metadata"]["host_key_sha256"] == fingerprint

ok(client.post("/connections/sources/live_sftp/syncs", json={
    "id": "live_sftp_sync", "target_asset_id": "sftp_target", "mode": "incremental", "cursor_field": "_source_file_path",
}), "create incremental SFTP sync")
first = ok(client.post("/ingestion/syncs/live_sftp_sync/enqueue", json={"idempotency_key": "sftp-1"}), "enqueue first SFTP sync", 202)
first_run = ok(client.post("/ingestion/workers/run-next", json={"job_id": first["job"]["id"], "worker_id": "sftp-worker"}), "execute first SFTP sync")
assert first_run["run"]["records_out"] == 3 and first_run["run"]["metrics"]["next_cursor"] == "/upload/002.csv"
second = ok(client.post("/ingestion/syncs/live_sftp_sync/enqueue", json={"idempotency_key": "sftp-2"}), "enqueue second SFTP sync", 202)
second_run = ok(client.post("/ingestion/workers/run-next", json={"job_id": second["job"]["id"], "worker_id": "sftp-worker"}), "execute second SFTP sync")
assert second_run["run"]["records_out"] == 1 and second_run["run"]["metrics"]["next_cursor"] == "/upload/003.json"
with SessionLocal() as db:
    target = db.get(models.DataAsset, "sftp_target")
    assert [row["asset_id"] for row in target.records] == ["SFTP-1", "SFTP-2", "SFTP-3", "SFTP-4"]
passed += 1

private_key_buffer = io.StringIO()
USER_KEY.write_private_key(private_key_buffer)
ok(client.post("/connections/sources", json={
    "id": "key_sftp", "display_name": "Key SFTP", "source_type": "sftp", "config": {**source_config, "max_files": 1},
}), "create private-key SFTP source")
ok(client.post("/connections/sources/key_sftp/runtime-credentials", json={
    "credential_type": "sftp_private_key", "secret": private_key_buffer.getvalue(), "metadata": {},
}), "store SFTP private key", 201)
key_preview = ok(client.post("/connections/sources/key_sftp/live-preview", json={"limit": 1}), "authenticate with SFTP private key")
assert [row["asset_id"] for row in key_preview["preview_rows"]] == ["SFTP-1", "SFTP-2"]

ok(client.post("/connections/sources", json={
    "id": "wrong_host_sftp", "display_name": "Wrong Host SFTP", "source_type": "sftp",
    "config": {**source_config, "host_key_sha256": "SHA256:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"},
}), "create mismatched host source")
ok(client.post("/connections/sources/wrong_host_sftp/runtime-credentials", json={
    "credential_type": "sftp_password", "secret": "fixture-password", "metadata": {},
}), "store mismatched host credential", 201)
ok(client.post("/connections/sources/wrong_host_sftp/live-preview", json={"limit": 1}), "reject mismatched SFTP host key", 403)

os.environ["CONNECTOR_ALLOW_PRIVATE_NETWORKS"] = "false"
ok(client.post("/connections/sources/live_sftp/live-preview", json={"limit": 1}), "deny private SFTP endpoint", 403)
os.environ["CONNECTOR_ALLOW_PRIVATE_NETWORKS"] = "true"

attempts = ok(client.get("/connections/sources/live_sftp/fetch-attempts"), "inspect SFTP fetch evidence")
assert len(attempts) == 5 and [row["status"] for row in attempts].count("FAILED") == 2
assert all("fixture-password" not in json.dumps(row) for row in attempts)

snapshot = ok(client.get("/project/export"), "export SFTP project snapshot")
assert "connector_credentials" not in snapshot and "fixture-password" not in json.dumps(snapshot)

print(f"SFTP connector runtime verified: {passed} assertions passed.")
stop_server.set()
listener.close()
server_thread.join(timeout=2)
engine.dispose()
tmpdir.cleanup()
