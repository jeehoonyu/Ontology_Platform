"""
Track A — real file upload + object storage.
Dataset CSV/JSON/JSONL upload -> records + inferred schema + raw-file download round-trip;
binary + text media upload -> content download; Parquet upload -> 422 when pyarrow absent.
Run: ./venv312/Scripts/python.exe test_uploads.py
"""
import os
import tempfile

_tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_tmp.name, 'up.db')}"
os.environ["STORAGE_DIR"] = os.path.join(_tmp.name, "storage")

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402
from app.database import engine  # noqa: E402

client = TestClient(app)
passed = 0


def ok(resp, label, expect=200):
    global passed
    success = resp.status_code == expect or (expect == 200 and 200 <= resp.status_code < 300)
    assert success, f"{label}: expected {expect}, got {resp.status_code} -> {resp.text[:300]}"
    passed += 1
    return resp.json() if resp.content else {}


def check(cond, label):
    global passed
    assert cond, f"CHECK FAILED: {label}"
    passed += 1


def new_asset(aid):
    ok(client.post("/data-assets", json={"id": aid, "display_name": aid, "description": "",
        "kind": "dataset", "asset_schema": {}, "records": []}), f"create {aid}")


# ================= CSV upload =================
new_asset("ds_csv")
csv_bytes = b"id,name,score,active\n1,Ann,10.5,true\n2,Bob,20,false\n"
up = ok(client.post("/data-assets/ds_csv/upload",
                    files={"file": ("data.csv", csv_bytes, "text/csv")}), "csv upload")
check(up["source_format"] == "csv" and up["record_count"] == 2, "csv: 2 records")
check(set(up["columns"]) == {"id", "name", "score", "active"}, "csv: columns inferred")
recs = ok(client.get("/data-assets/ds_csv"), "get ds_csv")["records"]
# type coercion: int, float, bool, str
check(recs[0] == {"id": 1, "name": "Ann", "score": 10.5, "active": True}, "csv: cells coerced by type")
check(recs[1]["active"] is False and recs[1]["score"] == 20, "csv row2 coerced")
# raw-file download round-trips the exact bytes
dl = client.get("/data-assets/ds_csv/download")
check(dl.status_code == 200 and dl.content == csv_bytes, "csv download returns the raw bytes")

# ================= JSON upload (list) + append mode =================
new_asset("ds_json")
ok(client.post("/data-assets/ds_json/upload",
               files={"file": ("a.json", b'[{"k":"x","n":1},{"k":"y","n":2}]', "application/json")}), "json upload")
check(ok(client.get("/data-assets/ds_json"), "get ds_json")["records"] == [{"k": "x", "n": 1}, {"k": "y", "n": 2}], "json records")
# append mode adds to existing records
ap = ok(client.post("/data-assets/ds_json/upload",
                    files={"file": ("b.jsonl", b'{"k":"z","n":3}\n', "application/x-ndjson")},
                    data={"mode": "append"}), "jsonl append")
check(ap["added"] == 1 and ap["record_count"] == 3, "append: 1 added -> 3 total")
check(ok(client.get("/data-assets/ds_json"), "re-get")["records"][-1] == {"k": "z", "n": 3}, "appended jsonl row present")

# explicit format override wins over extension
new_asset("ds_ovr")
ov = ok(client.post("/data-assets/ds_ovr/upload",
                   files={"file": ("mystery.dat", b"a,b\n1,2\n", "application/octet-stream")},
                   data={"format": "csv"}), "format override")
check(ov["source_format"] == "csv" and ov["record_count"] == 1, "override parses as csv")

# ================= Parquet without pyarrow -> 422 =================
try:
    import pyarrow  # noqa: F401
    _has_pyarrow = True
except ImportError:
    _has_pyarrow = False
if not _has_pyarrow:
    new_asset("ds_pq")
    r = client.post("/data-assets/ds_pq/upload",
                    files={"file": ("x.parquet", b"PAR1garbage", "application/octet-stream")})
    check(r.status_code == 422 and "pyarrow" in r.text.lower(), "parquet without pyarrow -> 422")

# download with no stored file -> 404
new_asset("ds_empty")
check(client.get("/data-assets/ds_empty/download").status_code == 404, "download 404 when no file stored")
check(client.post("/data-assets/ghost/upload", files={"file": ("x.csv", b"a\n1\n", "text/csv")}).status_code == 404,
      "upload to missing dataset -> 404")

# ================= Media: binary + text upload/download =================
ok(client.post("/media-sets", json={"id": "ms1", "display_name": "Docs", "media_type": "document"}), "media set")
blob = bytes(range(256))  # non-utf8 binary
mup = ok(client.post("/media-sets/ms1/items/upload",
                    files={"file": ("frame.bin", blob, "application/octet-stream")}), "binary media upload")
check(mup["size_bytes"] == 256 and mup["has_text"] is False and mup["storage_uri"], "binary media stored, no text")
content = client.get(f"/media-items/{mup['id']}/content")
check(content.status_code == 200 and content.content == blob, "binary media content round-trips")

tup = ok(client.post("/media-sets/ms1/items/upload",
                    files={"file": ("note.txt", b"hello world", "text/plain")}), "text media upload")
check(tup["has_text"] is True, "text media populates text_content")
tcontent = client.get(f"/media-items/{tup['id']}/content")
check(tcontent.status_code == 200 and tcontent.content == b"hello world", "text media content round-trips")
# text upload also feeds the existing extraction strategy
chunked = ok(client.post(f"/media-items/{tup['id']}/chunk", json={"chunk_size": 5, "overlap": 0}), "chunk uploaded text")
check(chunked["chunk_count"] >= 1, "uploaded text is chunkable by the extraction strategy")

ok(client.post("/media-sets/ghost/items/upload", files={"file": ("x.bin", b"x", "application/octet-stream")}),
   "upload to missing media set -> 404", expect=404)

print(f"\nFile upload + storage verified: {passed} assertions passed.")
engine.dispose()
_tmp.cleanup()
