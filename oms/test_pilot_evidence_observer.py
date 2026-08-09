"""Production-pilot observer persistence, restart accounting, and UI state."""
import json
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from availability_probe import PROBE_INTERVAL_SECONDS, run_probe, summarize  # noqa: E402
from app.pilot_evidence import (  # noqa: E402
    JournalIntegrityError, append_observation, current_migration_head, load_journal,
)
from app.pilot_observability import availability_status, rpo_status, rto_status  # noqa: E402

passed = 0


def check(condition, label, payload=None):
    global passed
    assert condition, f"{label}: {payload}"
    passed += 1


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in {"/health/live", "/health/ready"}:
            self.send_response(404)
            self.end_headers()
            return
        body = b'{"status":"READY"}'
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        return


server = ThreadingHTTPServer(("127.0.0.1", 0), HealthHandler)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()

try:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
        root = Path(directory)
        journal = root / "availability-samples.jsonl"
        state = root / "availability-probe-state.json"
        target = f"http://127.0.0.1:{server.server_port}"

        check(run_probe(target, journal, state, max_samples=1) == 0,
              "one live observation completes")
        records = load_journal(journal)
        check(len(records) == 1, "one observation is durable", records)
        check(records[0]["payload"]["available"] is True, "both health checks passed", records[0])
        saved_state = json.loads(state.read_text(encoding="utf-8"))
        check(saved_state["last_record_hash"] == records[-1]["record_hash"],
              "state anchors the journal tail", saved_state)

        # Move the schedule far enough into the past to model an observer that
        # was absent for three intervals. The restarted process must append
        # DOWN records before it performs another live probe.
        old_start = int(time.time()) - 5 * PROBE_INTERVAL_SECONDS
        journal.unlink()
        state.unlink()
        seed = append_observation(
            journal, run_id="pilot_restart", kind="availability", target=target,
            migration_head=current_migration_head(), scheduled_at=old_start,
            observed_at=old_start, payload={"available": True},
        )
        state.write_text(json.dumps({
            "schema_version": 1, "run_id": "pilot_restart", "target": target,
            "migration_head": current_migration_head(), "started_at": old_start,
            "next_scheduled_at": old_start + PROBE_INTERVAL_SECONDS,
            "last_record_hash": seed["record_hash"],
        }) + "\n", encoding="utf-8")
        check(run_probe(target, journal, state, max_samples=1) == 0,
              "restart accounts for missed intervals")
        restarted = load_journal(journal)
        gaps = [record for record in restarted if record["payload"].get("observer_gap")]
        check(len(gaps) >= 3, "every missed slot is an explicit DOWN record", gaps)
        check(all(not record["payload"]["available"] for record in gaps),
              "observer gaps cannot look available", gaps)
        summary = summarize(restarted, now=restarted[-1]["scheduled_at"])
        available = sum(1 for record in restarted if record["payload"].get("available"))
        expected_pct = round(100 * available / len(restarted), 4)
        check(summary["availability_pct"] == expected_pct,
              "restart accounting uses every scheduled slot", summary)

        status = availability_status(root)
        check(status["integrity"] == "PASS" and status["status"] == "COLLECTING",
              "backend exposes a valid in-progress run", status)
        check(status["measurements"]["unavailable_seconds"] >= 90,
              "backend includes observer downtime", status)

        rpo_journal = root / "rpo-samples.jsonl"
        for index in range(10):
            append_observation(
                rpo_journal, run_id="rpo_status", kind="rpo_observation",
                target="http://recovery.test", migration_head=current_migration_head(),
                scheduled_at=old_start + index, observed_at=old_start + index,
                payload={
                    "at": old_start + index,
                    "phase": "pre_backup" if index >= 8 else "mid_cycle",
                    "rpo_seconds": 120,
                    "total_loss": False,
                },
            )
        recovery_point = rpo_status(root)
        check(recovery_point["status"] == "COMPLETE" and recovery_point["remaining_samples"] == 0,
              "backend exposes complete current-head RPO coverage", recovery_point)

        rto_journal = root / "rto-rehearsals.jsonl"
        for index in range(4):
            append_observation(
                rto_journal, run_id=f"rto_status_{index}", kind="rto_rehearsal",
                target="http://recovery.test", migration_head=current_migration_head(),
                scheduled_at=old_start + index, observed_at=old_start + index,
                payload={
                    "at": old_start + index,
                    "trigger": "unattended" if index == 3 else "attended",
                    "elapsed_seconds": 300,
                    "recovered": True,
                },
            )
        recovery_time = rto_status(root)
        check(recovery_time["status"] == "COMPLETE" and recovery_time["remaining_rehearsals"] == 0,
              "backend exposes complete isolated RTO coverage", recovery_time)

        original_journal = journal.read_text(encoding="utf-8")
        journal.write_text(original_journal.splitlines()[0] + "\n", encoding="utf-8")
        rolled_back = availability_status(root)
        check(
            rolled_back["integrity"] == "FAIL"
            and "truncated behind" in str(rolled_back["warning"]),
            "backend detects journal rollback behind the durable tail anchor",
            rolled_back,
        )
        journal.write_text(original_journal, encoding="utf-8")

        tampered = journal.read_text(encoding="utf-8").replace(
            '"observer_gap":true', '"observer_gap":false', 1,
        )
        journal.write_text(tampered, encoding="utf-8")
        try:
            load_journal(journal)
            raise AssertionError("tampered journal was accepted")
        except JournalIntegrityError:
            passed += 1
        invalid = availability_status(root)
        check(invalid["integrity"] == "FAIL" and invalid["status"] == "INVALID",
              "backend surfaces journal tampering", invalid)
finally:
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)

print(f"Pilot evidence observer verified: {passed} assertions passed.")
