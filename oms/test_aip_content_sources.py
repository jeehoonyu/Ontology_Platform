import os, tempfile
_tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_tmp.name, 't.db')}"
from fastapi import FastAPI                       # noqa: E402
from fastapi.testclient import TestClient         # noqa: E402
from app.database import Base, engine             # noqa: E402
from app import models, models_action            # noqa: E402  (registers core + audit tables)
from app import aip_content_sources as M           # noqa: E402  (registers this module's tables)
Base.metadata.create_all(bind=engine)
api = FastAPI(); api.include_router(M.router)
client = TestClient(api)
passed = 0


def ok(resp, label, expect=200):
    global passed
    success = resp.status_code == expect or (expect == 200 and 200 <= resp.status_code < 300)
    assert success, f"{label}: expected {expect}, got {resp.status_code} -> {resp.text[:400]}"
    passed += 1
    return resp.json() if resp.content else {}


def check(cond, label):
    global passed
    assert cond, f"CHECK FAILED: {label}"
    passed += 1


# ---------------------------------------------------------------------------
# Scenario 1: register a 2-heading doc -> 2 chunks + INGESTED + log
# ---------------------------------------------------------------------------
DOC_2H = """# Onboarding Guide

Welcome to the platform. Follow these onboarding steps to get started.

# Security Policy

All users must enable multi factor authentication for security compliance.
"""

src1 = ok(client.post("/aip/assist/sources", json={
    "id": "src-onboarding",
    "display_name": "Onboarding & Security",
    "source_type": "markdown_docs",
    "owner": "alice",
    "content": DOC_2H,
}), "create 2-heading source")
check(src1["ingestion_status"] == "INGESTED", "source1 ingested")
check(src1["id"] == "src-onboarding", "source1 id preserved")

content1 = ok(client.get("/aip/assist/sources/src-onboarding/content"), "get content1")
check(content1["chunk_count"] == 2, f"2 chunks expected, got {content1['chunk_count']}")
headings = [c["heading_path"] for c in content1["chunks"]]
check("Onboarding Guide" in headings, "heading path Onboarding Guide present")
check("Security Policy" in headings, "heading path Security Policy present")

logs1 = ok(client.get("/aip/assist/sources/ingest-logs?source_id=src-onboarding"), "ingest logs src1")
check(logs1["count"] == 1, "one ingest log after register")
check(logs1["logs"][0]["event_type"] == "registered", "log event_type=registered")
check(logs1["logs"][0]["status"] == "INGESTED", "log status=INGESTED")
check(logs1["logs"][0]["chunk_count"] == 2, "log chunk_count=2")

# ---------------------------------------------------------------------------
# Scenario 2: heading-hierarchy path with nested headings (H1 > H2)
# ---------------------------------------------------------------------------
DOC_NESTED = """# Database

Intro to databases.

## Indexing

Use indexes to speed up queries on large tables.

## Backups

Schedule nightly backups for disaster recovery.
"""
src2 = ok(client.post("/aip/assist/sources", json={
    "id": "src-db",
    "display_name": "Database Handbook",
    "content": DOC_NESTED,
}), "create nested source")
content2 = ok(client.get("/aip/assist/sources/src-db/content"), "get content2")
paths2 = [c["heading_path"] for c in content2["chunks"]]
check("Database > Indexing" in paths2, f"nested path Database > Indexing present: {paths2}")
check("Database > Backups" in paths2, f"nested path Database > Backups present: {paths2}")
check(content2["chunk_count"] == 3, f"3 chunks expected for nested doc, got {content2['chunk_count']}")

# ---------------------------------------------------------------------------
# Scenario 3: visibility always returns regardless of scope_context
# ---------------------------------------------------------------------------
r_always = ok(client.post("/aip/assist/sources/src-onboarding/retrieve", json={
    "query": "onboarding steps", "k": 3, "scope_context": "anything-here",
}), "retrieve always with scope_context")
check(r_always["in_scope"] is True, "default visibility=always returns in_scope")
check(r_always["count"] >= 1, "always retrieve returns results")

# ---------------------------------------------------------------------------
# Scenario 4: by_resource returns only for matching scope
# ---------------------------------------------------------------------------
ok(client.put("/aip/assist/sources/src-db/visibility", json={
    "scope_type": "by_resource", "resource_ids": ["proj-A", "proj-B"],
}), "set by_resource visibility")
vis = ok(client.get("/aip/assist/sources/src-db/visibility"), "get visibility")
check(vis["scope_type"] == "by_resource", "visibility scope_type by_resource")

r_match = ok(client.post("/aip/assist/sources/src-db/retrieve", json={
    "query": "indexes queries", "k": 3, "scope_context": "proj-A",
}), "retrieve by_resource matching scope")
check(r_match["in_scope"] is True and r_match["count"] >= 1, "by_resource matching scope returns")

r_nomatch = ok(client.post("/aip/assist/sources/src-db/retrieve", json={
    "query": "indexes queries", "k": 3, "scope_context": "proj-Z",
}), "retrieve by_resource non-matching scope")
check(r_nomatch["in_scope"] is False, "by_resource non-matching scope hidden")
check(r_nomatch["count"] == 0, "by_resource non-matching returns no results")

r_noscope = ok(client.post("/aip/assist/sources/src-db/retrieve", json={
    "query": "indexes queries", "k": 3,
}), "retrieve by_resource without scope")
check(r_noscope["in_scope"] is False, "by_resource without scope_context hidden")

# ---------------------------------------------------------------------------
# Scenario 5: retrieve ranks the relevant heading first & is repeatable
# ---------------------------------------------------------------------------
r1 = ok(client.post("/aip/assist/sources/src-onboarding/retrieve", json={
    "query": "multi factor authentication security", "k": 2,
}), "retrieve security query")
top_heading = r1["results"][0]["heading_path"]
check(top_heading == "Security Policy", f"security query ranks Security Policy first, got {top_heading}")

r1b = ok(client.post("/aip/assist/sources/src-onboarding/retrieve", json={
    "query": "multi factor authentication security", "k": 2,
}), "retrieve security query repeat")
check([x["chunk_id"] for x in r1["results"]] == [x["chunk_id"] for x in r1b["results"]],
      "retrieve is repeatable (deterministic order)")
check([round(x["score"], 6) for x in r1["results"]] == [round(x["score"], 6) for x in r1b["results"]],
      "retrieve scores repeatable")

r_onb = ok(client.post("/aip/assist/sources/src-onboarding/retrieve", json={
    "query": "onboarding steps started", "k": 2,
}), "retrieve onboarding query")
check(r_onb["results"][0]["heading_path"] == "Onboarding Guide",
      "onboarding query ranks Onboarding Guide first")

# ---------------------------------------------------------------------------
# Scenario 6: suggest picks the right source per prompt
# ---------------------------------------------------------------------------
sug = ok(client.get("/aip/assist/sources/suggest?prompt=onboarding+steps+welcome"), "suggest onboarding")
# src-db is by_resource with no scope -> filtered out; src-onboarding should top.
check(sug["suggestions"][0]["source_id"] == "src-onboarding",
      f"suggest picks onboarding source, got {sug['suggestions'][0]['source_id']}")

sug_db = ok(client.get("/aip/assist/sources/suggest?prompt=database+indexing+backups&scope_context=proj-A"),
            "suggest db with scope")
db_ids = [s["source_id"] for s in sug_db["suggestions"]]
check("src-db" in db_ids, "suggest includes db source when in scope")
check(sug_db["suggestions"][0]["source_id"] == "src-db",
      f"suggest ranks db top for db prompt, got {sug_db['suggestions'][0]['source_id']}")

# ---------------------------------------------------------------------------
# Scenario 7: query-with-sources returns citations
# ---------------------------------------------------------------------------
qws = ok(client.post("/aip/assist/query-with-sources", json={
    "prompt": "how do I enable multi factor authentication",
    "source_ids": ["src-onboarding"],
    "k": 2,
}), "query-with-sources")
check(len(qws["citations"]) >= 1, "query-with-sources has citations")
check(qws["citations"][0]["source_id"] == "src-onboarding", "citation source_id correct")
check(qws["citations"][0]["heading_path"] == "Security Policy",
      f"top citation heading is Security Policy, got {qws['citations'][0]['heading_path']}")
check("retrieved passage" in qws["answer"], "answer is templated over retrieved chunks")

# query-with-sources respects scope: src-db by_resource w/o scope -> not cited
qws_all = ok(client.post("/aip/assist/query-with-sources", json={
    "prompt": "database indexing backups",
}), "query-with-sources all (no scope)")
cited_sources = {c["source_id"] for c in qws_all["citations"]}
check("src-db" not in cited_sources, "by_resource source excluded when out of scope")

# ---------------------------------------------------------------------------
# Scenario 8: reingest after adding a heading yields 3 chunks + new log
# ---------------------------------------------------------------------------
DOC_3H = DOC_2H + "\n# Support\n\nContact support for help with any platform issues.\n"
re_summary = ok(client.post("/aip/assist/sources/src-onboarding/reingest", json={
    "content": DOC_3H,
}), "reingest with 3 headings")
check(re_summary["chunk_count"] == 3, f"reingest yields 3 chunks, got {re_summary['chunk_count']}")
check(re_summary["status"] == "INGESTED", "reingest status INGESTED")

content3 = ok(client.get("/aip/assist/sources/src-onboarding/content"), "get content after reingest")
check(content3["chunk_count"] == 3, "content reflects 3 chunks after reingest")

logs2 = ok(client.get("/aip/assist/sources/ingest-logs?source_id=src-onboarding"), "ingest logs after reingest")
check(logs2["count"] == 2, f"two ingest logs after reingest, got {logs2['count']}")
check(logs2["logs"][-1]["event_type"] == "reingested", "latest log event_type=reingested")
check(logs2["logs"][-1]["chunk_count"] == 3, "reingest log chunk_count=3")

# ---------------------------------------------------------------------------
# Scenario 9: empty doc -> FAILED
# ---------------------------------------------------------------------------
src_empty = ok(client.post("/aip/assist/sources", json={
    "id": "src-empty",
    "display_name": "Empty Doc",
    "content": "   \n\n   \n",
}), "create empty source")
check(src_empty["ingestion_status"] == "FAILED", "empty doc -> FAILED")

logs_empty = ok(client.get("/aip/assist/sources/ingest-logs?source_id=src-empty"), "ingest logs empty")
check(logs_empty["logs"][0]["status"] == "FAILED", "empty doc log status FAILED")
check(logs_empty["logs"][0]["error_detail"] is not None, "empty doc has error_detail")

# ---------------------------------------------------------------------------
# Scenario 10: validation + error paths
# ---------------------------------------------------------------------------
ok(client.post("/aip/assist/sources", json={
    "display_name": "Bad type", "source_type": "pdf", "content": "# H\n\ntext",
}), "invalid source_type -> 422", expect=422)

ok(client.post("/aip/assist/sources", json={
    "id": "src-onboarding", "display_name": "dup", "content": "# H\n\ntext",
}), "duplicate id -> 400", expect=400)

ok(client.get("/aip/assist/sources/does-not-exist"), "missing source -> 404", expect=404)

ok(client.put("/aip/assist/sources/src-onboarding/visibility", json={
    "scope_type": "weird", "resource_ids": [],
}), "invalid scope_type -> 422", expect=422)

# ---------------------------------------------------------------------------
# Scenario 11: list + delete
# ---------------------------------------------------------------------------
all_srcs = ok(client.get("/aip/assist/sources"), "list sources")
check(len(all_srcs) == 3, f"three sources listed, got {len(all_srcs)}")

ok(client.delete("/aip/assist/sources/src-empty"), "delete empty source")
ok(client.get("/aip/assist/sources/src-empty"), "deleted source -> 404", expect=404)
all_srcs2 = ok(client.get("/aip/assist/sources"), "list after delete")
check(len(all_srcs2) == 2, "two sources after delete")

print(f"\nAIP-ASSIST verified: {passed} assertions passed.")
engine.dispose(); _tmp.cleanup()
