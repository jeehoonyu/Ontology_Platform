"""Rehearse resumable collaboration WebSockets across API replica loss."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from contextlib import ExitStack
from pathlib import Path

from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect


if not os.environ.get("DATABASE_URL", "").startswith("postgresql"):
    raise SystemExit("verify_collaboration_websocket_chaos_postgres.py requires a PostgreSQL DATABASE_URL")

ROOT = Path(__file__).resolve().parent
ARTIFACT_ID = f"collaboration_ws_chaos_{uuid.uuid4().hex[:10]}"
RECONNECT_LIMIT_SECONDS = float(os.getenv("COLLABORATION_WS_RECONNECT_LIMIT_SECONDS", "5"))


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def request(base_url: str, method: str, path: str, body=None, timeout=20):
    payload = None if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
    outgoing = urllib.request.Request(
        f"{base_url}{path}", data=payload, method=method,
        headers={"content-type": "application/json"} if payload is not None else {},
    )
    try:
        with urllib.request.urlopen(outgoing, timeout=timeout) as response:  # nosec - local rehearsal
            raw = response.read()
            return response.status, json.loads(raw.decode("utf-8")) if raw else {}
    except urllib.error.HTTPError as error:
        raw = error.read()
        return error.code, json.loads(raw.decode("utf-8")) if raw else {}


def start_replica(stack: ExitStack, port: int) -> tuple[subprocess.Popen, str]:
    environment = os.environ.copy()
    environment.update({"AUTH_MODE": "local", "APP_ENV": "test", "SKIP_CREATE_ALL": "1"})
    process = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn", "app.main:app", "--app-dir", str(ROOT),
            "--host", "127.0.0.1", "--port", str(port), "--no-access-log",
        ],
        cwd=ROOT.parent,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=None,
        text=True,
    )

    def stop() -> None:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    stack.callback(stop)
    base_url = f"http://127.0.0.1:{port}"
    for _ in range(120):
        if process.poll() is not None:
            raise AssertionError("API replica exited during startup")
        try:
            status, _ = request(base_url, "GET", "/health/live", timeout=1)
            if status == 200:
                return process, base_url
        except (OSError, TimeoutError):
            pass
        time.sleep(0.1)
    raise AssertionError(f"API replica on {port} did not become ready")


def websocket_url(base_url: str, cursor: int) -> str:
    return base_url.replace("http://", "ws://", 1) + f"/artifacts/{ARTIFACT_ID}/collaboration/ws?after={cursor}"


def receive_ready(connection, expected_cursor: int) -> dict:
    payload = json.loads(connection.recv(timeout=5))
    assert payload["type"] == "connection.ready" and payload["cursor"] == expected_cursor, payload
    return payload


def receive_command(connection) -> dict:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        payload = json.loads(connection.recv(timeout=max(0.1, deadline - time.monotonic())))
        if payload.get("type") == "event" and (payload.get("event") or {}).get("event_type") == "artifact.commands":
            return payload
    raise AssertionError("Timed out waiting for an artifact.commands event")


def apply_edit(base_url: str, token: str, lock_version: int, sequence: int):
    return request(base_url, "POST", f"/artifacts/{ARTIFACT_ID}/collaboration/commands", {
        "participant_token": token,
        "expected_lock_version": lock_version,
        "idempotency_key": f"ws-chaos-edit-{sequence}",
        "commands": [{
            "command_id": f"ws-chaos-command-{sequence}",
            "command": "add_node",
            "payload": {"node": {
                "id": f"node-{sequence}",
                "position": {"x": 100 + sequence * 180, "y": 120},
                "data": {"label": f"Node {sequence}", "nodeType": "filter"},
            }},
        }],
        "message": f"WebSocket chaos edit {sequence}",
    })


with ExitStack() as stack:
    primary_port, peer_port = free_port(), free_port()
    primary_process, primary = start_replica(stack, primary_port)
    _, peer = start_replica(stack, peer_port)

    status, artifact = request(primary, "POST", "/artifacts", {
        "id": ARTIFACT_ID,
        "artifact_type": "pipeline",
        "display_name": "WebSocket replica chaos",
        "state": {"nodes": [], "edges": []},
    })
    assert status == 201, (status, artifact)
    status, joined = request(primary, "POST", f"/artifacts/{ARTIFACT_ID}/collaboration/join", {
        "client_id": "websocket-chaos-client", "ttl_seconds": 300,
    })
    assert status == 200, (status, joined)
    token = joined["participant_token"]
    cursor = int(joined["event_cursor"])
    received_ids: list[int] = []
    reconnect_seconds: list[float] = []

    with connect(websocket_url(primary, cursor), open_timeout=5) as stream:
        receive_ready(stream, cursor)
        status, edit = apply_edit(peer, token, artifact["lock_version"], 1)
        assert status == 200, (status, edit)
        envelope = receive_command(stream)
        cursor = int(envelope["cursor"])
        received_ids.append(cursor)

        primary_process.terminate()
        primary_process.wait(timeout=10)
        try:
            stream.recv(timeout=3)
            raise AssertionError("Primary WebSocket remained open after replica termination")
        except ConnectionClosed:
            pass

    reconnect_started = time.perf_counter()
    with connect(websocket_url(peer, cursor), open_timeout=5) as stream:
        receive_ready(stream, cursor)
        reconnect_seconds.append(time.perf_counter() - reconnect_started)
        status, edit = apply_edit(peer, token, edit["lock_version"], 2)
        assert status == 200, (status, edit)
        envelope = receive_command(stream)
        cursor = int(envelope["cursor"])
        received_ids.append(cursor)

    restarted_process, restarted_primary = start_replica(stack, primary_port)
    assert restarted_process.poll() is None
    reconnect_started = time.perf_counter()
    with connect(websocket_url(restarted_primary, cursor), open_timeout=5) as stream:
        receive_ready(stream, cursor)
        reconnect_seconds.append(time.perf_counter() - reconnect_started)
        status, edit = apply_edit(peer, token, edit["lock_version"], 3)
        assert status == 200, (status, edit)
        envelope = receive_command(stream)
        cursor = int(envelope["cursor"])
        received_ids.append(cursor)

    # Reconnect time is a threshold and is judged with the evidence below, so a
    # breaching run is recorded rather than lost. Event loss, duplication, and
    # ordering are correctness and still abort here.
    assert len(received_ids) == len(set(received_ids)) == 3, received_ids
    assert received_ids == sorted(received_ids), received_ids
    status, committed = request(restarted_primary, "GET", f"/artifacts/{ARTIFACT_ID}")
    assert status == 200 and committed["current_revision"] == 4, committed
    assert len((committed.get("state") or {}).get("nodes") or []) == 3, committed

    evidence = {
        "transport": "authenticated_resumable_websocket",
        "replicas": 2,
        "replica_terminations": 1,
        "replica_restarts": 1,
        "command_events_received": 3,
        "duplicate_events": 0,
        "missed_events": 0,
        "final_revision": committed["current_revision"],
        "reconnect_max_ms": round(max(reconnect_seconds) * 1000, 3),
        "reconnect_limit_ms": round(RECONNECT_LIMIT_SECONDS * 1000, 3),
        "event_ids": received_ids,
    }
    evidence_path = os.getenv("COLLABORATION_WS_EVIDENCE_PATH", "").strip()
    if evidence_path:
        path = Path(evidence_path)
        if not path.is_absolute():
            path = (ROOT.parent / path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("PostgreSQL collaboration WebSocket chaos rehearsal measurements:")
    print(json.dumps(evidence, indent=2, sort_keys=True))

    from chaos_rehearsals import record

    # This harness covers the collaboration half of the chaos gate. It records a
    # rehearsal rather than writing the gate verdict, because the gate also names
    # cross-stream processing and no single harness can see both. The verdict
    # comes from `python oms/chaos_rehearsals.py aggregate`, which fails while
    # either subject has no rehearsal.
    record("collaboration", {
        "reconnect_max_ms": evidence["reconnect_max_ms"],
        "duplicate_events": evidence["duplicate_events"],
        "missed_events": evidence["missed_events"],
        "replica_terminations": evidence["replica_terminations"],
        "replica_restarts": evidence["replica_restarts"],
        "command_events_received": evidence["command_events_received"],
    }, harness="oms/verify_collaboration_websocket_chaos_postgres.py")
    print("Recorded a collaboration chaos rehearsal.")
    print("PostgreSQL collaboration WebSocket chaos rehearsal passed.")
