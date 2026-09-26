"""The collaboration WebSocket reads its event log off the event loop.

The handler is async, and it read the log with a synchronous SQLAlchemy query every
half second on the event loop's own thread. Each open builder page then held the whole
server for the length of that query, and a query waiting on SQLite's write lock held
it for up to the lock timeout. In full browser runs, `/project/readiness` went
unanswered for 45 s while builder pages were open, and the shell-width test that waits
on it slowed from 17 s to past its timeout (GOAL_FOUNDATIONS, measured during A8).

This slows every query the socket makes, holds a socket open, and checks that a plain
request is still answered promptly. The HTTP requests and the socket share one event
loop only when the TestClient is entered as a context manager.
"""
import os
import tempfile
import time

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'socket.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402

from app import platform_runtime as runtime  # noqa: E402
from app.main import app  # noqa: E402

SLOW = 0.6  # seconds each query the socket makes is held, as a locked database would hold it
checks = 0


def check(condition, message):
    global checks
    assert condition, message
    checks += 1


class SlowSession:
    """A real session whose queries wait first, as they do behind a write lock."""

    def __init__(self, session):
        self._session = session

    def query(self, *args, **kwargs):
        time.sleep(SLOW)
        return self._session.query(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._session, name)


with TestClient(app) as client:
    created = client.post("/artifacts", json={
        "id": "socket_artifact", "artifact_type": "workshop", "display_name": "Socket artifact",
        "state": {"nodes": [], "edges": [], "widgets": []},
    })
    check(created.status_code in (200, 201), f"the artifact is created: {created.status_code} {created.text[:200]}")

    real = runtime.SessionLocal
    runtime.SessionLocal = lambda: SlowSession(real())
    try:
        with client.websocket_connect("/artifacts/socket_artifact/collaboration/ws?after=0") as socket:
            check(socket.receive_json()["type"] == "connection.ready", "the socket is ready")
            time.sleep(3 * SLOW)  # let it poll a few times
            waits = []
            for _ in range(8):
                started = time.perf_counter()
                check(client.get("/health/live").status_code == 200, "the server answers")
                waits.append(time.perf_counter() - started)
                time.sleep(0.15)
            worst = max(waits)
            check(worst < 0.3, f"a plain request waited {worst:.2f}s behind the socket's event-log read "
                               f"(waits: {', '.join(f'{wait:.2f}' for wait in waits)})")
    finally:
        runtime.SessionLocal = real

print(f"Collaboration socket stays off the event loop: {checks} assertions passed.")
