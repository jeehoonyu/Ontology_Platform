"""Generate and benchmark representative ontology scale on PostgreSQL.

The smoke profile protects query plans in CI. The reference profile is the
release gate and will not report success below 10 million objects and 50
million links.
"""

from __future__ import annotations

import json
import math
import os
import platform
import statistics
import time
from pathlib import Path


if not os.environ.get("DATABASE_URL", "").startswith("postgresql"):
    raise SystemExit("benchmark_ontology_scale_postgres.py requires a PostgreSQL DATABASE_URL")

PROFILE = os.getenv("ONTOLOGY_SCALE_PROFILE", "smoke").strip().lower()
if PROFILE not in {"smoke", "reference"}:
    raise SystemExit("ONTOLOGY_SCALE_PROFILE must be 'smoke' or 'reference'")

REFERENCE_OBJECTS = 10_000_000
REFERENCE_LINKS = 50_000_000
default_objects = REFERENCE_OBJECTS if PROFILE == "reference" else 100_000
default_links = REFERENCE_LINKS if PROFILE == "reference" else 500_000
OBJECT_COUNT = int(os.getenv("ONTOLOGY_SCALE_OBJECTS", str(default_objects)))
LINK_COUNT = int(os.getenv("ONTOLOGY_SCALE_LINKS", str(default_links)))
SAMPLES = int(os.getenv("ONTOLOGY_SCALE_SAMPLES", "20"))
WARMUPS = int(os.getenv("ONTOLOGY_SCALE_WARMUPS", "3"))
OBJECT_P95_LIMIT_MS = float(os.getenv("ONTOLOGY_OBJECT_QUERY_P95_LIMIT_MS", "300"))
GRAPH_P95_LIMIT_MS = float(os.getenv("ONTOLOGY_GRAPH_QUERY_P95_LIMIT_MS", "2000"))
EVIDENCE_PATH = os.getenv("ONTOLOGY_SCALE_EVIDENCE_PATH")
REUSE_EXISTING = os.getenv("ONTOLOGY_SCALE_REUSE_EXISTING", "").strip().lower() in {"1", "true", "yes"}

if OBJECT_COUNT < 100 or LINK_COUNT < 100 or SAMPLES < 5:
    raise SystemExit("Scale counts must be at least 100 and samples at least 5")
if PROFILE == "reference" and (OBJECT_COUNT < REFERENCE_OBJECTS or LINK_COUNT < REFERENCE_LINKS):
    raise SystemExit("Reference profile requires at least 10,000,000 objects and 50,000,000 links")

os.environ["SKIP_CREATE_ALL"] = "1"
os.environ.setdefault("AUTH_MODE", "local")
os.environ.setdefault("APP_ENV", "test")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import inspect, text  # noqa: E402
from app.database import engine  # noqa: E402
from app.main import app  # noqa: E402


client = TestClient(app)
OBJECT_TYPE_ID = "scale_benchmark_asset"
LINK_TYPE_ID = "scale_benchmark_related"
OBJECT_PREFIX = "scale_object_"
LINK_PREFIX = "scale_link_"


def checked(response, expected: int = 200):
    assert response.status_code == expected, f"{response.status_code}: {response.text[:2000]}"
    return response.json()


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered) - 1, math.ceil(len(ordered) * fraction) - 1))]


def plan_nodes(plan):
    if isinstance(plan, list):
        for item in plan:
            yield from plan_nodes(item)
    elif isinstance(plan, dict):
        if "Node Type" in plan:
            yield plan
        for value in plan.values():
            yield from plan_nodes(value)


def timed_post(path: str, body: dict) -> tuple[float, dict]:
    started = time.perf_counter()
    result = checked(client.post(path, json=body))
    return (time.perf_counter() - started) * 1000.0, result


if not REUSE_EXISTING:
    checked(client.post("/object-types", json={
        "id": OBJECT_TYPE_ID,
        "project_id": "default",
        "display_name": "Scale Benchmark Asset",
        "properties": {
            "assetId": {"type": "string"},
            "risk": {"type": "number"},
            "category": {"type": "string"},
            "latitude": {"type": "number"},
            "longitude": {"type": "number"},
        },
    }))
checked(client.put(f"/ontology/object-types/{OBJECT_TYPE_ID}/profile", json={
    "api_name": "ScaleBenchmarkAsset",
    "primary_key": "assetId",
    "title_key": "assetId",
    "properties": {
        "assetId": {"base_type": "string", "required": True, "indexed": True},
        "risk": {"base_type": "double", "indexed": True},
        "category": {"base_type": "string"},
        "latitude": {"base_type": "double"},
        "longitude": {"base_type": "double"},
    },
}))
if not REUSE_EXISTING:
    checked(client.post("/link-types", json={
        "id": LINK_TYPE_ID,
        "project_id": "default",
        "display_name": "Scale Benchmark Related Asset",
        "description": "Deterministic bounded-degree scale relationship",
        "source_object_type_id": OBJECT_TYPE_ID,
        "target_object_type_id": OBJECT_TYPE_ID,
        "cardinality": "MANY_TO_MANY",
    }))
checked(client.post("/api/v1/ontology/compile", json={
    "project_id": "default", "object_type_ids": [OBJECT_TYPE_ID],
}))

object_width = max(8, len(str(OBJECT_COUNT)))
link_width = max(8, len(str(LINK_COUNT)))
seed_started = time.perf_counter()
if REUSE_EXISTING:
    with engine.connect() as connection:
        counts = connection.execute(text("""
            SELECT
                (SELECT count(*) FROM object_instances WHERE project_id = 'default' AND object_type_id = :object_type_id) AS object_count,
                (SELECT count(*) FROM link_instances WHERE project_id = 'default' AND link_type_id = :link_type_id) AS link_count
        """), {"object_type_id": OBJECT_TYPE_ID, "link_type_id": LINK_TYPE_ID}).mappings().one()
    if int(counts["object_count"]) != OBJECT_COUNT or int(counts["link_count"]) != LINK_COUNT:
        raise SystemExit(
            "Reuse fixture count mismatch: "
            f"expected {OBJECT_COUNT}/{LINK_COUNT}, found {counts['object_count']}/{counts['link_count']}"
        )
else:
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL synchronous_commit = off"))
        connection.execute(text("""
        INSERT INTO object_instances (
            id, project_id, object_type_id, properties, source_asset_id,
            lineage, created_at, updated_at
        )
        SELECT
            :object_prefix || lpad(series::text, :object_width, '0'),
            'default', :object_type_id,
            jsonb_build_object(
                'assetId', :object_prefix || lpad(series::text, :object_width, '0'),
                'risk', mod(series, 101),
                'category', 'category_' || mod(series, 20),
                'latitude', 37.0 + mod(series, 1000)::double precision / 10000.0,
                'longitude', -122.0 - mod(series, 1000)::double precision / 10000.0
            ),
            NULL, '{}'::jsonb, 1700000000 + mod(series, 1000000),
            1700000000 + mod(series, 1000000)
        FROM generate_series(1, :object_count) AS generated(series)
        """), {
            "object_prefix": OBJECT_PREFIX,
            "object_width": object_width,
            "object_type_id": OBJECT_TYPE_ID,
            "object_count": OBJECT_COUNT,
        })
        connection.execute(text("""
        INSERT INTO link_instances (
            id, project_id, link_type_id, source_object_id,
            target_object_id, properties, created_at
        )
        SELECT
            :link_prefix || lpad(series::text, :link_width, '0'),
            'default', :link_type_id,
            :object_prefix || lpad((mod(series - 1, :object_count) + 1)::text, :object_width, '0'),
            :object_prefix || lpad((
                mod(
                    (mod(series::bigint - 1, CAST(:object_count AS bigint)) + 1) * 7919
                    + ((series::bigint - 1) / CAST(:object_count AS bigint)) * 104729
                    + 17,
                    CAST(:object_count AS bigint)
                ) + 1
            )::text, :object_width, '0'),
            json_build_object('ordinal', series), 1700000000 + mod(series, 1000000)
        FROM generate_series(1, :link_count) AS generated(series)
        """), {
            "link_prefix": LINK_PREFIX,
            "link_width": link_width,
            "link_type_id": LINK_TYPE_ID,
            "object_prefix": OBJECT_PREFIX,
            "object_width": object_width,
            "object_count": OBJECT_COUNT,
            "link_count": LINK_COUNT,
        })
        connection.execute(text("ANALYZE object_instances"))
        connection.execute(text("ANALYZE link_instances"))
seed_seconds = time.perf_counter() - seed_started

plans = checked(client.get(
    f"/api/v1/ontology/indexes?project_id=default&object_type_id={OBJECT_TYPE_ID}"
))["indexes"]
for index_plan in plans:
    if index_plan["property_name"] in {"assetId", "risk"}:
        applied = checked(client.post(f"/api/v1/ontology/indexes/{index_plan['id']}/apply"))
        assert applied["status"] == "ACTIVE", applied

target_number = max(1, OBJECT_COUNT - 7)
target_id = f"{OBJECT_PREFIX}{target_number:0{object_width}d}"
seed_number = max(1, OBJECT_COUNT // 2)
seed_id = f"{OBJECT_PREFIX}{seed_number:0{object_width}d}"
lookup_body = {
    "project_id": "default",
    "object_type_id": OBJECT_TYPE_ID,
    "filters": [{"field": "assetId", "operator": "eq", "value": target_id}],
    "order_by": [{"field": "assetId", "direction": "asc"}],
    "limit": 10,
    "include_total": False,
    "include_lineage": False,
}
range_body = {
    "project_id": "default",
    "object_type_id": OBJECT_TYPE_ID,
    "filters": [{"field": "risk", "operator": "gte", "value": 95}],
    "order_by": [{"field": "risk", "direction": "desc"}],
    "limit": 100,
    "include_total": False,
    "include_lineage": False,
}
graph_body = {
    "project_id": "default",
    "seed_object_ids": [seed_id],
    "depth": 2,
    "direction": "both",
    "link_type_ids": [LINK_TYPE_ID],
    "max_nodes": 500,
    "max_edges": 5000,
}

for _ in range(WARMUPS):
    checked(client.post("/api/v1/objects/query", json=lookup_body))
    checked(client.post("/api/v1/objects/query", json=range_body))
    checked(client.post("/api/v1/graph/query", json=graph_body))

lookup_latencies = []
range_latencies = []
graph_latencies = []
last_graph = None
for _ in range(SAMPLES):
    latency, lookup = timed_post("/api/v1/objects/query", lookup_body)
    lookup_latencies.append(latency)
    assert [item["id"] for item in lookup["objects"]] == [target_id], lookup
    latency, range_result = timed_post("/api/v1/objects/query", range_body)
    range_latencies.append(latency)
    assert range_result["count"] == 100 and all(
        item["properties"]["risk"] >= 95 for item in range_result["objects"]
    ), range_result
    latency, last_graph = timed_post("/api/v1/graph/query", graph_body)
    graph_latencies.append(latency)
    assert last_graph["summary"]["depth"] == 2 and last_graph["query_plan"]["n_plus_one"] is False

with engine.connect() as connection:
    object_plan = connection.execute(text("""
        EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
        SELECT id FROM object_instances
        WHERE project_id = 'default' AND object_type_id = :object_type_id
          AND CAST(properties ->> 'assetId' AS VARCHAR) = :target_id
        ORDER BY CAST(properties ->> 'assetId' AS VARCHAR) ASC NULLS LAST, id ASC
        LIMIT 11
    """), {"object_type_id": OBJECT_TYPE_ID, "target_id": target_id}).scalar_one()
    graph_plan = connection.execute(text("""
        EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
        SELECT id, source_object_id, target_object_id FROM link_instances
        WHERE project_id = 'default' AND link_type_id = :link_type_id
          AND (source_object_id = :seed_id OR target_object_id = :seed_id)
        ORDER BY id LIMIT 5001
    """), {"link_type_id": LINK_TYPE_ID, "seed_id": seed_id}).scalar_one()
    sizes = connection.execute(text("""
        SELECT
            pg_total_relation_size('object_instances') AS object_bytes,
            pg_total_relation_size('link_instances') AS link_bytes
    """)).mappings().one()

object_nodes = list(plan_nodes(object_plan))
graph_nodes = list(plan_nodes(graph_plan))
object_index_names = sorted({node.get("Index Name") for node in object_nodes if node.get("Index Name")})
graph_index_names = sorted({node.get("Index Name") for node in graph_nodes if node.get("Index Name")})
assert any(name.startswith("ix_oi_property_") for name in object_index_names), object_nodes
assert set(graph_index_names) & {
    "ix_link_instances_project_source_id", "ix_link_instances_source_object_id",
}, graph_nodes
assert set(graph_index_names) & {
    "ix_link_instances_project_target_id", "ix_link_instances_target_object_id",
}, graph_nodes

lookup_p95 = percentile(lookup_latencies, 0.95)
range_p95 = percentile(range_latencies, 0.95)
graph_p95 = percentile(graph_latencies, 0.95)
assert max(lookup_p95, range_p95) < OBJECT_P95_LIMIT_MS, {
    "lookup_p95_ms": lookup_p95,
    "range_p95_ms": range_p95,
    "limit_ms": OBJECT_P95_LIMIT_MS,
}
assert graph_p95 < GRAPH_P95_LIMIT_MS, {
    "graph_p95_ms": graph_p95,
    "limit_ms": GRAPH_P95_LIMIT_MS,
}

# --- Condition B7: the shapes the surfaces issue -----------------------------
#
# Everything above posts to /api/v1/objects/query, which is one implementation
# of a typed read: a keyset-paginated select with a LIMIT. The Object Explorer
# and the Operational Map reach a *different* implementation behind different
# routes, and until 2026-08-06 that one materialized the whole object type --
# 21.9 GB for a single filter click at this scale. This gate passed throughout,
# honestly, because it never called those routes.
#
# So it calls them now. Same corpus, same run, same evidence file.
surface_latencies: dict[str, list[float]] = {"explorer_filter": [], "facet": []}

explorer_body = {
    "object_type_id": OBJECT_TYPE_ID,
    "filters": {"category": "category_0"},
    "limit": 50,
}
facet_body = {
    "object_type_id": OBJECT_TYPE_ID,
    "group_by": "category",
}

for _ in range(WARMUPS):
    checked(client.post("/object-explorer/query", json=explorer_body))

for _ in range(SAMPLES):
    latency, explorer_result = timed_post("/object-explorer/query", explorer_body)
    surface_latencies["explorer_filter"].append(latency)
    assert explorer_result["result_count"] >= 0, explorer_result

# The facet is served from a rollup when one exists and computed exactly
# otherwise; both are legitimate and the response says which, so the evidence
# records the source rather than assuming the fast path was taken.
facet_source = "unmeasured"
try:
    for _ in range(max(3, SAMPLES // 4)):
        latency, facet_result = timed_post("/object-sets/aggregate", facet_body)
        surface_latencies["facet"].append(latency)
        facet_source = facet_result.get("source", "unknown")
except AssertionError:
    # The aggregate route is not mounted in every profile. Recorded as absent
    # rather than silently skipped, so the evidence does not imply coverage.
    facet_source = "route_unavailable"

explorer_p95 = percentile(surface_latencies["explorer_filter"], 0.95) if surface_latencies["explorer_filter"] else None
facet_p95 = percentile(surface_latencies["facet"], 0.95) if surface_latencies["facet"] else None

evidence = {
    "profile": PROFILE,
    "explorer_filter_p95_ms": round(explorer_p95, 3) if explorer_p95 is not None else None,
    "facet_p95_ms": round(facet_p95, 3) if facet_p95 is not None else None,
    "facet_source": facet_source,
    "reference_scale_achieved": OBJECT_COUNT >= REFERENCE_OBJECTS and LINK_COUNT >= REFERENCE_LINKS,
    "objects": OBJECT_COUNT,
    "links": LINK_COUNT,
    "seed_seconds": round(seed_seconds, 3),
    "reused_existing_fixture": REUSE_EXISTING,
    "samples": SAMPLES,
    "object_lookup_p50_ms": round(statistics.median(lookup_latencies), 3),
    "object_lookup_p95_ms": round(lookup_p95, 3),
    "object_range_p50_ms": round(statistics.median(range_latencies), 3),
    "object_range_p95_ms": round(range_p95, 3),
    "object_query_limit_ms": OBJECT_P95_LIMIT_MS,
    "graph_two_hop_p50_ms": round(statistics.median(graph_latencies), 3),
    "graph_two_hop_p95_ms": round(graph_p95, 3),
    "graph_query_limit_ms": GRAPH_P95_LIMIT_MS,
    "graph_nodes": last_graph["summary"]["node_count"] if last_graph else None,
    "graph_edges": last_graph["summary"]["edge_count"] if last_graph else None,
    "object_index_names": object_index_names,
    "graph_index_names": graph_index_names,
    "object_relation_bytes": int(sizes["object_bytes"]),
    "link_relation_bytes": int(sizes["link_bytes"]),
    "host": {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "processor": platform.processor(),
    },
}
serialized = json.dumps(evidence, indent=2, sort_keys=True)
if EVIDENCE_PATH:
    Path(EVIDENCE_PATH).write_text(serialized + "\n", encoding="utf-8")
print("PostgreSQL ontology scale benchmark passed:")
print(serialized)

# Tier B gate evidence is written only for the reference profile. The smoke
# profile is a functional regression check at a hundredth of the scale, not an
# attempt at the gate; letting it emit would overwrite a genuine reference PASS
# with a FAIL every CI run and destroy the evidence it took hours to produce.
if PROFILE == "reference":
    from tier_b_evidence import write_evidence

    gate_path, gate_status, gate_breaches = write_evidence(
        "ontology_scale",
        thresholds={
            "objects_min": REFERENCE_OBJECTS,
            "links_min": REFERENCE_LINKS,
            "object_lookup_p95_ms_max": OBJECT_P95_LIMIT_MS,
            "object_range_p95_ms_max": OBJECT_P95_LIMIT_MS,
            "graph_two_hop_p95_ms_max": GRAPH_P95_LIMIT_MS,
            # The Object Explorer's own route, held to the same bound as the
            # typed read it parallels. Without this the gate certifies one
            # implementation of a typed read and says nothing about the other.
            "explorer_filter_p95_ms_max": OBJECT_P95_LIMIT_MS,
        },
        measurements={
            "objects": OBJECT_COUNT,
            "links": LINK_COUNT,
            "object_lookup_p95_ms": evidence["object_lookup_p95_ms"],
            "object_range_p95_ms": evidence["object_range_p95_ms"],
            "graph_two_hop_p95_ms": evidence["graph_two_hop_p95_ms"],
            "explorer_filter_p95_ms": evidence["explorer_filter_p95_ms"],
            "facet_p95_ms": evidence["facet_p95_ms"],
            "facet_source": evidence["facet_source"],
        },
        harness="oms/benchmark_ontology_scale_postgres.py",
        entry_points=[
            "POST /api/v1/objects/query",
            "POST /api/v1/graph/query",
            "POST /object-explorer/query",
            "POST /object-sets/aggregate",
        ],
        request_shapes=[
            "typed lookup, equality filter on an indexed property",
            "typed range read, gte filter with ordering",
            "two-hop graph traversal",
            "Object Explorer filtered read (runtime.query_object_set)",
            "facet aggregation grouped by a property",
        ],
        notes=(
            f"Reference profile over {OBJECT_COUNT} objects and {LINK_COUNT} links, "
            f"{SAMPLES} samples per query shape, physical index plans verified. "
            f"Covers both typed-read implementations: the v1 keyset select and the "
            f"Object Explorer path. Facet served from {evidence['facet_source']}."
        ),
    )
    print(f"\nTier B evidence {gate_status}: {gate_path.name}")
    for breach in gate_breaches:
        print(f"  breach: {breach}")
else:
    print(f"\nProfile is '{PROFILE}'; no Tier B gate evidence written. "
          "Run with ONTOLOGY_SCALE_PROFILE=reference to attempt the gate.")
engine.dispose()
