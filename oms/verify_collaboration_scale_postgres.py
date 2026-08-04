"""Measure two-replica visual-builder collaboration on PostgreSQL.

The rehearsal uses real HTTP sockets and independent API processes. It proves
that 20 stale-base, target-disjoint edits serialize without lost updates and
that 200 simultaneous readers observe the same committed revision.
"""

from __future__ import annotations

import json
import math
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path


EDITOR_COUNT = 20
READER_COUNT = 200
ACK_P95_LIMIT_MS = float(os.getenv("COLLABORATION_ACK_P95_LIMIT_MS", "250"))
READ_BATCH_LIMIT_SECONDS = float(os.getenv("COLLABORATION_READ_BATCH_LIMIT_SECONDS", "15"))

if not os.environ.get("DATABASE_URL", "").startswith("postgresql"):
    raise SystemExit("verify_collaboration_scale_postgres.py requires a PostgreSQL DATABASE_URL")

ROOT = Path(__file__).resolve().parent
ARTIFACT_ID = f"collaboration_scale_{uuid.uuid4().hex[:10]}"


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def request(base_url: str, method: str, path: str, body=None, timeout=30):
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
        try:
            raw = error.read()
        except (OSError, TimeoutError) as read_error:
            return error.code, {"error": f"response body unavailable: {read_error}"}
        try:
            return error.code, json.loads(raw.decode("utf-8")) if raw else {}
        except json.JSONDecodeError:
            return error.code, {"error": raw.decode("utf-8", errors="replace")}


def percentile(values: list[float], percentile_value: float) -> float:
    ordered = sorted(values)
    rank = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * percentile_value) - 1))
    return ordered[rank]


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


with ExitStack() as stack:
    replicas = [start_replica(stack, free_port())[1] for _ in range(2)]
    nodes = [
        {
            "id": f"editor_node_{index:02d}",
            "position": {"x": (index % 5) * 220, "y": (index // 5) * 120},
            "data": {"label": f"Editor node {index:02d}", "nodeType": "transform"},
        }
        for index in range(EDITOR_COUNT)
    ]
    status, artifact = request(replicas[0], "POST", "/artifacts", {
        "id": ARTIFACT_ID,
        "project_id": "default",
        "artifact_type": "pipeline",
        "display_name": "Twenty-editor collaboration rehearsal",
        "state": {"nodes": nodes, "edges": []},
    })
    assert status == 201, (status, artifact)
    base_lock_version = artifact["lock_version"]

    participants = []
    for index in range(EDITOR_COUNT):
        replica = replicas[index % len(replicas)]
        status, joined = request(replica, "POST", f"/artifacts/{ARTIFACT_ID}/collaboration/join", {
            "client_id": f"scale-editor-{index:02d}", "ttl_seconds": 300,
        })
        assert status == 200, (status, joined)
        participants.append((replica, joined["participant_token"]))

    status, room = request(replicas[0], "GET", f"/artifacts/{ARTIFACT_ID}/collaboration")
    assert status == 200 and len(room["participants"]) == EDITOR_COUNT, room

    def edit(index: int):
        replica, token = participants[index]
        started = time.perf_counter()
        edit_status, result = request(
            replica,
            "POST",
            f"/artifacts/{ARTIFACT_ID}/collaboration/commands",
            {
                "participant_token": token,
                "expected_lock_version": base_lock_version,
                "idempotency_key": f"scale-edit-{index:02d}",
                "commands": [{
                    "command_id": f"scale-command-{index:02d}",
                    "command": "move_nodes",
                    "payload": {"positions": {
                        f"editor_node_{index:02d}": {"x": 1000 + index * 20, "y": 600 + index * 10}
                    }},
                }],
                "message": f"Concurrent editor {index:02d}",
            },
        )
        return edit_status, result, (time.perf_counter() - started) * 1000

    with ThreadPoolExecutor(max_workers=EDITOR_COUNT) as pool:
        edits = list(pool.map(edit, range(EDITOR_COUNT)))
    assert all(status == 200 for status, _, _ in edits), [
        (status, body) for status, body, _ in edits if status != 200
    ]
    latencies = [latency for _, _, latency in edits]
    acknowledgement_p95_ms = percentile(latencies, 0.95)
    assert acknowledgement_p95_ms < ACK_P95_LIMIT_MS, {
        "p95_ms": round(acknowledgement_p95_ms, 3),
        "limit_ms": ACK_P95_LIMIT_MS,
        "latencies_ms": [round(value, 3) for value in sorted(latencies)],
    }

    revisions = sorted(result["collaboration_receipt"]["revision"] for _, result, _ in edits)
    assert revisions == list(range(2, EDITOR_COUNT + 2)), revisions
    assert sum(bool(result["collaboration_receipt"]["rebased_from_lock_version"]) for _, result, _ in edits) == EDITOR_COUNT - 1

    status, committed = request(replicas[1], "GET", f"/artifacts/{ARTIFACT_ID}")
    assert status == 200
    assert committed["current_revision"] == EDITOR_COUNT + 1
    positions = {node["id"]: node["position"] for node in committed["state"]["nodes"]}
    assert all(positions[f"editor_node_{index:02d}"]["x"] == 1000 + index * 20 for index in range(EDITOR_COUNT))

    def read(reader: int):
        read_status, result = request(
            replicas[reader % len(replicas)], "GET", f"/artifacts/{ARTIFACT_ID}", timeout=30,
        )
        return read_status, result.get("current_revision"), len((result.get("state") or {}).get("nodes") or [])

    read_started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=READER_COUNT) as pool:
        reads = list(pool.map(read, range(READER_COUNT)))
    read_seconds = time.perf_counter() - read_started
    assert reads == [(200, EDITOR_COUNT + 1, EDITOR_COUNT)] * READER_COUNT, reads
    assert read_seconds < READ_BATCH_LIMIT_SECONDS, {
        "elapsed_seconds": round(read_seconds, 3), "limit_seconds": READ_BATCH_LIMIT_SECONDS,
    }

    status, events = request(
        replicas[0], "GET", f"/artifacts/{ARTIFACT_ID}/collaboration/events?after=0&limit=500",
    )
    assert status == 200
    command_events = [event for event in events["events"] if event["event_type"] == "artifact.commands"]
    assert len(command_events) == EDITOR_COUNT
    assert len({event["lock_version"] for event in command_events}) == EDITOR_COUNT

    evidence = {
        "artifact_id": ARTIFACT_ID,
        "replicas": len(replicas),
        "editors": EDITOR_COUNT,
        "commands_applied": len(edits),
        "acknowledgement_p50_ms": round(percentile(latencies, 0.50), 3),
        "acknowledgement_p95_ms": round(acknowledgement_p95_ms, 3),
        "acknowledgement_limit_ms": ACK_P95_LIMIT_MS,
        "readers": READER_COUNT,
        "reader_batch_seconds": round(read_seconds, 3),
        "final_revision": committed["current_revision"],
        "lost_updates": 0,
    }
    print("PostgreSQL collaboration scale rehearsal passed:")
    print(json.dumps(evidence, indent=2, sort_keys=True))
