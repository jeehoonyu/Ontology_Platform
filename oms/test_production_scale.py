"""Production-pilot scale contract: 250-node DAG and 50 concurrent readers."""
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'production_scale.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
nodes = [{"id": f"node_{index:03d}", "type": "transform"} for index in range(250)]
edges = [{"source": f"node_{index:03d}", "target": f"node_{index + 1:03d}"} for index in range(249)]

created = client.post("/artifacts", json={
    "id": "scale_pipeline_250",
    "artifact_type": "pipeline",
    "display_name": "Production scale pipeline",
    "state": {"nodes": nodes, "edges": edges},
    "layout": {node["id"]: {"x": (index % 25) * 180, "y": (index // 25) * 90} for index, node in enumerate(nodes)},
})
assert created.status_code == 201, created.text[:1000]
assert created.json()["validation"]["status"] == "PASS", created.json()["validation"]

validated = client.post("/artifacts/scale_pipeline_250/validate")
assert validated.status_code == 200, validated.text[:1000]
assert validated.json()["status"] == "PASS", validated.json()


def read_artifact(_reader: int):
    response = client.get("/artifacts/scale_pipeline_250")
    assert response.status_code == 200, response.text[:500]
    body = response.json()
    return len(body["state"]["nodes"]), len(body["state"]["edges"]), body["current_revision"]


with ThreadPoolExecutor(max_workers=50) as pool:
    results = list(pool.map(read_artifact, range(50)))

assert results == [(250, 249, 1)] * 50, results
print("Production scale verified: 250-node DAG and 50 concurrent authenticated readers.")

from app.database import engine as _engine  # noqa: E402
_engine.dispose()
tmpdir.cleanup()
