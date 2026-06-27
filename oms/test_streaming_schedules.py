"""
Deep-fidelity pass 9 conformance test:
  Streaming — tumbling/session windows, watermark late-drop, stateful running aggregates.
  Schedules — cron-due matching, compound AND/OR trigger evaluation, schedule evaluate.
Run: ./venv312/Scripts/python.exe test_streaming_schedules.py
"""
import os
import tempfile

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'stream_sched.db')}"

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
passed = 0


def ok(resp, label, expect=200):
    global passed
    success = resp.status_code == expect or (expect == 200 and 200 <= resp.status_code < 300)
    assert success, f"{label}: expected {expect}, got {resp.status_code} -> {resp.text[:400]}"
    passed += 1
    return resp.json() if resp.content else {}


# ================= Streaming windowing =================
ok(client.post("/streams", json={"id": "events", "display_name": "Events"}), "stream")
ok(client.post("/streams/events/publish", json={"records": [
    {"ts": 0, "k": "a", "v": 10}, {"ts": 1, "k": "a", "v": 20},
    {"ts": 5, "k": "a", "v": 30}, {"ts": 6, "k": "a", "v": 40},
]}), "publish")

tum = ok(client.post("/streams/events/window", json={
    "window_type": "tumbling", "size": 5, "timestamp_field": "ts", "key_field": "k", "value_field": "v", "agg": "sum"}), "tumbling")
assert tum["window_count"] == 2, tum
assert [w["value"] for w in tum["windows"]] == [30, 70], tum["windows"]  # [0,5)=10+20, [5,10)=30+40

ses = ok(client.post("/streams/events/window", json={
    "window_type": "session", "gap": 2, "timestamp_field": "ts", "key_field": "k", "value_field": "v", "agg": "count"}), "session")
assert ses["window_count"] == 2 and [w["count"] for w in ses["windows"]] == [2, 2], ses["windows"]

wm = ok(client.post("/streams/events/window", json={
    "window_type": "tumbling", "size": 5, "timestamp_field": "ts", "agg": "count", "watermark": 5, "allowed_lateness": 0}), "watermark")
assert wm["late_dropped"] == 2, wm  # ts 0 and 1 dropped

stf = ok(client.post("/streams/events/stateful", json={"key_field": "k", "value_field": "v", "op": "sum"}), "stateful")
assert stf["final_state"]["a"] == 100, stf
assert stf["timeline"][-1]["running_sum"] == 100, stf["timeline"]

# ================= Schedules: cron-due =================
T_0900 = 1609491600   # 2021-01-01 09:00:00 UTC (Friday)
assert ok(client.post("/schedules/cron-due", json={"cron": "0 9 * * *", "timestamp": T_0900}), "cron 0900")["due"] is True
assert ok(client.post("/schedules/cron-due", json={"cron": "0 9 * * *", "timestamp": T_0900 + 60}), "cron 0901")["due"] is False
assert ok(client.post("/schedules/cron-due", json={"cron": "*/15 * * * *", "timestamp": T_0900}), "cron */15 @00")["due"] is True
assert ok(client.post("/schedules/cron-due", json={"cron": "*/15 * * * *", "timestamp": T_0900 + 7 * 60}), "cron */15 @07")["due"] is False
assert ok(client.post("/schedules/cron-due", json={"cron": "0 9 * * 1-5", "timestamp": T_0900}), "cron weekday")["due"] is True  # Friday

# ================= Schedules: compound triggers =================
and_trigger = {"type": "and", "triggers": [
    {"type": "time", "cron": "0 9 * * *"},
    {"type": "event", "event": "rawLoaded"}]}
r_and_yes = ok(client.post("/schedules/evaluate-trigger", json={
    "trigger": and_trigger, "context": {"timestamp": T_0900, "events": ["rawLoaded"]}}), "and yes")
assert r_and_yes["result"]["satisfied"] is True, r_and_yes
r_and_no = ok(client.post("/schedules/evaluate-trigger", json={
    "trigger": and_trigger, "context": {"timestamp": T_0900, "events": []}}), "and no")
assert r_and_no["result"]["satisfied"] is False, r_and_no
or_trigger = {"type": "or", "triggers": [
    {"type": "event", "event": "x"}, {"type": "schedule_succeeded", "schedule": "upstream"}]}
r_or = ok(client.post("/schedules/evaluate-trigger", json={
    "trigger": or_trigger, "context": {"events": [], "succeeded_schedules": ["upstream"]}}), "or")
assert r_or["result"]["satisfied"] is True, r_or

# ================= Schedules: stored schedule evaluate =================
ok(client.post("/schedules", json={"id": "nightly", "display_name": "Nightly", "target_type": "pipeline",
    "target_id": "p1", "trigger_type": "cron", "cron": "0 9 * * *", "enabled": True}), "create schedule")
ev_yes = ok(client.post("/schedules/nightly/evaluate", json={"context": {"timestamp": T_0900}}), "sched eval yes")
assert ev_yes["would_fire"] is True, ev_yes
ev_no = ok(client.post("/schedules/nightly/evaluate", json={"context": {"timestamp": T_0900 + 60}}), "sched eval no")
assert ev_no["would_fire"] is False, ev_no

print(f"\nStreaming + Schedules deep mechanics verified: {passed} assertions passed.")
from app.database import engine as _engine  # noqa: E402
_engine.dispose()
tmpdir.cleanup()
