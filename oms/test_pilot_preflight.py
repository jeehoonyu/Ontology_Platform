"""Preflight must fail before the window opens, not after it closes.

Every check here stands for a misconfiguration that is otherwise invisible until
aggregation seven days later, when the only remedy is another seven days. The
cases are the ones that look healthy from the outside: a token that is long
enough but not accepted, a recovery URL that resolves back to the live system, an
observer that was never started.
"""
import argparse
import json
import os
import re
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pilot_window  # noqa: E402
from app.pilot_recovery import RUN_ID_PATTERN as RUN_ID  # noqa: E402

assert isinstance(RUN_ID, re.Pattern)

TOKEN = "pilot-preflight-token-abcdefghijklmnopqrstuvwxyz"
passed = 0


def check(condition, label, payload=None):
    global passed
    assert condition, f"{label}: {payload}"
    passed += 1


class Api(BaseHTTPRequestHandler):
    """The parts of the real API preflight touches.

    The recovery route reproduces app/pilot_recovery.py exactly: an unset token
    disables the whole protocol with 404, a wrong credential is 401, and a
    malformed run_id is 422 -- but only after the credential was accepted.
    """

    healthy = True
    recovery_enabled = True

    def do_GET(self):
        if self.path.startswith("/health/pilot-recovery/"):
            if not Api.recovery_enabled:
                self._reply(404)          # "Recovery probe is disabled"
            elif self.headers.get("Authorization") != f"Bearer {TOKEN}":
                self._reply(401)
            elif not RUN_ID.fullmatch(self.path.split("/marks/")[1].split("/")[0]):
                self._reply(422)          # "run_id contains unsupported characters"
            else:
                self._reply(404)          # "No recovery mark survived"
            return
        self._reply(200 if Api.healthy else 503)

    def _reply(self, code):
        self.send_response(code)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *args):
        pass


server = HTTPServer(("127.0.0.1", 0), Api)
threading.Thread(target=server.serve_forever, daemon=True).start()
TARGET = f"http://127.0.0.1:{server.server_address[1]}"
ELSEWHERE = "http://127.0.0.1:18002"


def preflight(root, *, token=TOKEN, target=TARGET, recovery=ELSEWHERE, observer=True):
    pilot_window.EVIDENCE_ROOT = root
    pilot_window.MANIFEST = root / "pilot-window.json"
    os.environ["PILOT_RECOVERY_TOKEN"] = token
    if observer:
        (root / "availability-probe-state.json").write_text(
            json.dumps({"next_scheduled_at": int(time.time()) + pilot_window.PROBE_INTERVAL_SECONDS}),
            encoding="utf-8")
    return pilot_window.preflight(argparse.Namespace(
        target=target, recovery_target=recovery, recovery_driver="manual",
        availability_writer="observer", token_env="PILOT_RECOVERY_TOKEN",
    ))


def in_root(**kwargs):
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
        return preflight(Path(directory), **kwargs)


try:
    check(in_root() == 0, "a correctly configured pilot passes preflight")

    # Long enough to satisfy the length rule, and still refused by the API. Only
    # asking the API distinguishes them.
    check(in_root(token="wrong-but-long-enough-token-abcdefghijklmnop") != 0,
          "a token the source API rejects fails preflight")
    check(in_root(token="short") != 0, "a token under 32 characters fails preflight")

    # The likely mistake: the token exported for the host process but never put
    # in the API container. The protocol is then off and answers 404 -- the same
    # status a live route gives for "no such run", so only a request the live
    # route answers differently can tell them apart.
    Api.recovery_enabled = False
    check(in_root() != 0, "a disabled recovery protocol fails preflight")
    Api.recovery_enabled = True

    check(in_root(recovery=TARGET) != 0,
          "a recovery URL that resolves to the live source fails preflight")

    check(in_root(observer=False) != 0,
          "an availability observer that was never started fails preflight")

    Api.healthy = False
    check(in_root() != 0, "a source that answers 503 on /health/ready fails preflight")
    Api.healthy = True

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
        root = Path(directory)
        (root / "pilot-window.json").write_text("{}", encoding="utf-8")
        check(preflight(root) != 0, "an evidence root with an open window fails preflight")

    # Unreachable is distinct from unhealthy and must also fail.
    check(in_root(target="http://127.0.0.1:1") != 0,
          "an unreachable source fails preflight")
finally:
    server.shutdown()

print(f"Pilot preflight verified: {passed} assertions passed.")
