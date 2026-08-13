"""Runtime schema reconciliation is one-time and safe under concurrent readiness traffic."""
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'schema_reconciliation.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app import system_hardening  # noqa: E402

client = TestClient(app)


def readiness(_index):
    response = client.get("/project/readiness")
    return response.status_code, response.json()


with ThreadPoolExecutor(max_workers=24) as pool:
    results = list(pool.map(readiness, range(48)))

assert all(status == 200 for status, _body in results), results
assert all(body["status"] in {"READY", "NEEDS_ATTENTION"} for _status, body in results)
assert engine in system_hardening._RUNTIME_SCHEMA_READY_ENGINES

with SessionLocal() as db:
    records = db.query(system_hardening.MigrationRecord).all()
    assert len(records) == len(system_hardening.MIGRATIONS), len(records)
    assert len({row.version for row in records}) == len(records)

assert engine.pool.checkedout() == 0, engine.pool.status()
print("Runtime schema reconciliation verified: 48 concurrent readiness requests passed.")

client.close()
engine.dispose()
tmpdir.cleanup()
