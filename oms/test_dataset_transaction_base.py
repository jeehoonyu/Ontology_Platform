"""
A dataset transaction starts from the dataset's real rows.

`POST /datasets/{id}/transactions` rebuilt the live rows as the fold of the transaction
log, and the fold starts from nothing. A dataset made by `POST /data-assets`, or given
rows later by an upload, a sync or a pipeline run, has rows the log never saw. So APPEND
left only the appended rows, UPDATE only the patch, and DELETE emptied the dataset, while
the reply reported the payload's size. GOAL_HONEST_UI_2026-09-11 filed it under N7c.

Each block runs on its own and every failure is printed, so one run on the old code
shows each block failing for its own reason.

Run:
  python oms/test_dataset_transaction_base.py
"""
import os
import sys
import tempfile

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'txn_base.db')}"
os.environ["STORAGE_DIR"] = os.path.join(tmpdir.name, "storage")

from fastapi.testclient import TestClient  # noqa: E402
from app import models_action  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
passed = 0
TWO = [{"id": 1, "v": 10}, {"id": 2, "v": 20}]


def ok(resp, label, expect=200):
    global passed
    success = resp.status_code == expect or (expect == 200 and 200 <= resp.status_code < 300)
    assert success, f"{label}: expected {expect}, got {resp.status_code} -> {resp.text[:400]}"
    passed += 1
    return resp.json() if resp.content else {}


def check(condition, message):
    global passed
    assert condition, message
    passed += 1


def mk_asset(aid, records):
    ok(client.post("/data-assets", json={"id": aid, "display_name": aid, "kind": "dataset", "asset_schema": {}, "records": records}), f"asset {aid}")


def commit(aid, txn_type, records, branch="master"):
    return ok(client.post(f"/datasets/{aid}/transactions", json={"branch": branch, "txn_type": txn_type, "primary_key": "id", "records": records}), f"{txn_type} {aid}", 201)


def rows(aid):
    return ok(client.get(f"/data-assets/{aid}"), f"get {aid}")["records"]


def ids(aid):
    return sorted(row["id"] for row in rows(aid))


def log(aid, branch="master"):
    return [(t["txn_type"], t["seq"], t["row_count"]) for t in ok(client.get(f"/datasets/{aid}/transactions", params={"branch": branch}), f"log {aid}")]


def view(aid, **params):
    return ok(client.get(f"/datasets/{aid}/view", params=params), f"view {aid} {params}")


def audit(aid, event_type):
    with SessionLocal() as db:
        return [row.payload for row in db.query(models_action.AuditLog).filter(
            models_action.AuditLog.subject_id == aid, models_action.AuditLog.event_type == event_type).all()]


def append_keeps_rows():
    mk_asset("seeded_append", TWO)
    appended = commit("seeded_append", "APPEND", [{"id": 3, "v": 30}])
    check(ids("seeded_append") == [1, 2, 3], f"APPEND on a dataset with no log left ids {ids('seeded_append')}, not [1, 2, 3]")
    check(view("seeded_append")["row_count"] == 3, "the master view does not agree with the dataset's rows")
    check(appended["seq"] == 1, f"the APPEND took seq {appended['seq']}; the rows it was appended to should hold seq 0")
    check(log("seeded_append") == [("SNAPSHOT", 0, 2), ("APPEND", 1, 1)], f"the log is {log('seeded_append')}")
    check(view("seeded_append", as_of_seq=0)["rows"] == TWO, "the rows before the APPEND cannot be reached with as_of_seq=0")
    commit("seeded_append", "APPEND", [{"id": 4}])
    check(len(log("seeded_append")) == 3 and ids("seeded_append") == [1, 2, 3, 4],
          f"a second APPEND on a reconciled dataset gave log {log('seeded_append')} and ids {ids('seeded_append')}")


def delete_does_not_empty():
    mk_asset("seeded_delete", TWO)
    commit("seeded_delete", "DELETE", [{"id": 2}])
    check(rows("seeded_delete") == [{"id": 1, "v": 10}], f"DELETE of one row left {rows('seeded_delete')}")
    check(view("seeded_delete")["row_count"] == 1, "the master view does not agree with the dataset's rows")


def update_merges_into_the_row():
    mk_asset("seeded_update", [{"id": 1, "v": 10, "name": "a"}, {"id": 2, "v": 20, "name": "b"}])
    commit("seeded_update", "UPDATE", [{"id": 1, "v": 99}])
    current = {row["id"]: row for row in rows("seeded_update")}
    check(current == {1: {"id": 1, "v": 99, "name": "a"}, 2: {"id": 2, "v": 20, "name": "b"}},
          f"UPDATE of one field left {rows('seeded_update')}")


def snapshot_keeps_history():
    mk_asset("seeded_snap", TWO)
    commit("seeded_snap", "SNAPSHOT", [{"id": 9}])
    check(rows("seeded_snap") == [{"id": 9}], "a SNAPSHOT no longer replaces the rows")
    past = view("seeded_snap", as_of_seq=0)
    check(past["rows"] == TWO, f"the rows a SNAPSHOT replaced are gone from history: as_of_seq=0 gives {past['rows']}")
    check([entry[0] for entry in log("seeded_snap")] == ["SNAPSHOT", "SNAPSHOT"], f"the log is {log('seeded_snap')}")


def rows_written_outside_the_log_survive():
    mk_asset("drift", [])
    commit("drift", "SNAPSHOT", [{"id": 1}])
    ok(client.post("/data-assets/drift/upload", files={"file": ("more.json", b'[{"id": 2}]', "application/json")}, data={"mode": "append"}), "upload append")
    commit("drift", "APPEND", [{"id": 3}])
    check(ids("drift") == [1, 2, 3], f"a row uploaded after the SNAPSHOT was dropped by the next APPEND: ids {ids('drift')}")
    check(log("drift") == [("SNAPSHOT", 0, 1), ("SNAPSHOT", 1, 2), ("APPEND", 2, 1)], f"the log is {log('drift')}")


def branch_seeds_real_rows():
    mk_asset("seeded_branch", TWO)
    branch = ok(client.post("/datasets/seeded_branch/branches", json={"name": "dev"}), "branch", 201)
    check(branch["seeded_rows"] == 2, f"a branch of a dataset with no log seeded {branch['seeded_rows']} rows")
    check(view("seeded_branch", branch="dev")["row_count"] == 2, "the branch view does not hold the dataset's rows")
    check(log("seeded_branch") == [("SNAPSHOT", 0, 2)], f"master's log does not hold the rows the branch came from: {log('seeded_branch')}")


def in_sync_dataset_is_unchanged():
    # Passes on the old code by design: a dataset whose every write went through the log
    # gets no baseline, and no transaction is applied twice.
    mk_asset("in_sync", [])
    commit("in_sync", "SNAPSHOT", [{"id": 1}])
    commit("in_sync", "APPEND", [{"id": 2}])
    commit("in_sync", "UPDATE", [{"id": 1, "v": 5}])
    check(log("in_sync") == [("SNAPSHOT", 0, 1), ("APPEND", 1, 1), ("UPDATE", 2, 1)], f"an in-sync dataset's log is {log('in_sync')}")
    check(rows("in_sync") == [{"id": 1, "v": 5}, {"id": 2}], f"an in-sync dataset's rows are {rows('in_sync')}")


def baseline_is_audited():
    baselines = audit("seeded_append", "dataset.transaction.baseline_recorded")
    check(len(baselines) == 1, f"{len(baselines)} baseline audit entries for seeded_append, not 1")
    check(baselines[0] == {"branch": "master", "rows": 2, "seq": 0, "reason": "no_history"}, f"the baseline entry is {baselines[0]}")
    committed = audit("seeded_append", "dataset.transaction.committed")
    check(committed and committed[0].get("dataset_rows") == 3, f"the committed entry does not say how many rows the dataset holds: {committed[:1]}")
    drift = audit("drift", "dataset.transaction.baseline_recorded")
    check([entry.get("reason") for entry in drift] == ["records_changed_outside_log"], f"the drift baseline entries are {drift}")


def other_branch_leaves_master():
    # A write to another branch never touches master. The branch is created first, which
    # records master's baseline; the side write must add nothing to master after that.
    mk_asset("side_only", TWO)
    ok(client.post("/datasets/side_only/branches", json={"name": "side", "base_branch": "master"}), "create side", 201)
    master_before = log("side_only")
    commit("side_only", "APPEND", [{"id": 3}], branch="side")
    check(rows("side_only") == TWO, f"a write to another branch changed master's rows: {rows('side_only')}")
    check(log("side_only") == master_before, f"a write to another branch wrote to master's log: {log('side_only')}")


def unknown_branch_is_refused():
    # A transaction to a branch nobody created was accepted as seq 0 of a branch that then
    # existed only in the log.
    mk_asset("ghostly", TWO)
    r = client.post("/datasets/ghostly/transactions",
                    json={"branch": "ghost", "txn_type": "APPEND", "primary_key": "id", "records": [{"id": 9}]})
    check(r.status_code == 404, f"a transaction to a branch nobody created returned {r.status_code}")
    check(log("ghostly", branch="ghost") == [], f"it wrote to the log: {log('ghostly', branch='ghost')}")


def recreating_a_branch_is_refused():
    # Creating a branch that exists wrote a second branch row and a second seq-0 SNAPSHOT on
    # it; naming master wrote one on master.
    mk_asset("twice", TWO)
    ok(client.post("/datasets/twice/branches", json={"name": "dev", "base_branch": "master"}), "create dev", 201)
    master_log = log("twice")
    r = client.post("/datasets/twice/branches", json={"name": "dev", "base_branch": "master"})
    check(r.status_code == 409, f"re-creating a branch returned {r.status_code}")
    r = client.post("/datasets/twice/branches", json={"name": "master", "base_branch": "master"})
    check(r.status_code == 409, f"creating a branch named master returned {r.status_code}")
    r = client.post("/datasets/twice/branches", json={"name": "feature", "base_branch": "nope"})
    check(r.status_code == 404, f"a branch from a base nobody created returned {r.status_code}")
    branches = [b["name"] for b in ok(client.get("/datasets/twice/branches"), "branches")]
    check(branches == ["dev"], f"the branch list is {branches}")
    check([seq for _, seq, _ in log("twice", branch="dev")] == [0], f"dev's log is {log('twice', branch='dev')}")
    check(log("twice") == master_log, f"master's log changed: {master_log} -> {log('twice')}")


def racing_commits_take_distinct_numbers():
    # Two commits that both read the log before either writes. `seq` was the branch's highest
    # plus one, so both took the same number -- and on master the mirror kept only the second.
    # Each thread is held at a barrier after its read; the handlers are called directly, each
    # on its own session, the way two requests would run.
    import threading
    from app import datasets_ext as DX, production_auth

    caller = production_auth._local_principal()
    for aid, branch, reader in (("race_master", "master", "_reconcile_master"), ("race_dev", "dev", "_next_seq")):
        mk_asset(aid, TWO)
        if branch != "master":
            ok(client.post(f"/datasets/{aid}/branches", json={"name": branch, "base_branch": "master"}), f"create {branch}", 201)
        barrier = threading.Barrier(2, timeout=20)
        held = threading.local()
        original = getattr(DX, reader)

        def read_then_wait(*args, _original=original, **kwargs):
            result = _original(*args, **kwargs)
            if not getattr(held, "waited", False):
                held.waited = True
                barrier.wait()
            return result

        setattr(DX, reader, read_then_wait)
        outcomes = []

        def write(row_id):
            with SessionLocal() as db:
                try:
                    txn = DX.create_transaction(aid, DX.TransactionCreate(
                        branch=branch, txn_type="APPEND", primary_key="id", records=[{"id": row_id}]), principal=caller, db=db)
                    outcomes.append(("ok", txn.seq))
                except Exception as error:  # the assertion below names it
                    outcomes.append(("error", repr(error)))

        try:
            threads = [threading.Thread(target=write, args=(row_id,)) for row_id in (100, 200)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(60)
        finally:
            setattr(DX, reader, original)
        check([kind for kind, _ in outcomes] == ["ok", "ok"], f"{branch}: the racing commits did not both land: {outcomes}")
        seqs = [seq for _, seq, _ in log(aid, branch=branch)]
        check(len(seqs) == len(set(seqs)), f"{branch}: two transactions share a sequence number: {seqs}")
        check(seqs == list(range(len(seqs))), f"{branch}: the sequence has a gap or is out of order: {seqs}")
        folded = sorted(row["id"] for row in view(aid, branch=branch)["rows"])
        check({100, 200} <= set(folded), f"{branch}: the view lost a racing commit: {folded}")
        if branch == "master":
            check(ids(aid) == folded, f"master's mirror {ids(aid)} is not its log {folded}")


def a_delivery_that_loses_the_race_writes_nothing():
    # A pipeline delivery writes its output's master snapshot at the branch's next number.
    # Losing that number to a concurrent write used to surface as an unhandled 500; now the
    # index refuses it, the delivery answers 503, and nothing it built is kept.
    from app import pipeline_builder_ops as PB

    mk_asset("deliver_in", TWO)
    mk_asset("deliver_out", [])
    commit("deliver_out", "SNAPSHOT", [{"id": 1}])
    graph = ok(client.post("/pipeline-builder/graphs", json={
        "id": "deliver_race", "display_name": "Deliver race",
        "nodes": [{"id": "input", "type": "input_dataset", "config": {"asset_id": "deliver_in"}},
                  {"id": "output", "type": "dataset_output", "config": {"asset_id": "deliver_out"}}],
        "edges": [{"source": "input", "target": "output"}],
    }), "create graph")
    before = log("deliver_out")
    original = PB._next_seq
    PB._next_seq = lambda db, dataset_id, branch: 0  # the number a concurrent write already took
    try:
        r = client.post(f"/pipeline-builder/graphs/{graph['id']}/deliver", json={"actor": "test"})
    finally:
        PB._next_seq = original
    check(r.status_code == 503, f"a delivery that lost the sequence race returned {r.status_code}: {r.text[:200]}")
    check(log("deliver_out") == before, f"the refused delivery wrote to the log: {before} -> {log('deliver_out')}")
    check(ids("deliver_out") == [1], f"the refused delivery changed the output's rows: {ids('deliver_out')}")
    ok(client.post(f"/pipeline-builder/graphs/{graph['id']}/deliver", json={"actor": "test"}), "deliver again")
    check(ids("deliver_out") == [1, 2], f"the delivery that followed did not land: {ids('deliver_out')}")


def next_number_counts_unwritten_rows():
    # With autoflush off, a row added but not yet written is invisible to the query, so two
    # writes to one dataset in one session -- a delivery whose quarantine and output are the
    # same asset -- took the same number, which the unique index now refuses.
    import uuid
    from app import datasets_ext as DX

    mk_asset("pending_rows", TWO)
    commit("pending_rows", "SNAPSHOT", [{"id": 1}])
    with SessionLocal() as db:
        first = DX._next_seq(db, "pending_rows", "master")
        db.add(DX.DatasetTransaction(id=uuid.uuid4().hex, dataset_id="pending_rows", branch="master", txn_type="APPEND",
                                     primary_key="id", records=[], row_count=0, status="COMMITTED", seq=first, created_at=1))
        second = DX._next_seq(db, "pending_rows", "master")
        check(second == first + 1, f"a second write in one session took number {second}, the same as the first's {first}")
        db.rollback()


failures = []
for block in (append_keeps_rows, delete_does_not_empty, update_merges_into_the_row, snapshot_keeps_history,
              rows_written_outside_the_log_survive, branch_seeds_real_rows, in_sync_dataset_is_unchanged,
              baseline_is_audited, other_branch_leaves_master, unknown_branch_is_refused,
              recreating_a_branch_is_refused, racing_commits_take_distinct_numbers,
              a_delivery_that_loses_the_race_writes_nothing, next_number_counts_unwritten_rows):
    try:
        block()
    except (AssertionError, KeyError, IndexError, TypeError) as error:
        failures.append(f"{block.__name__}: {type(error).__name__}: {error}")

for failure in failures:
    print(f"FAIL {failure}")
from app.database import engine as _engine  # noqa: E402
_engine.dispose()
if failures:
    sys.exit(1)
print(f"Dataset transactions start from the dataset's rows: {passed} assertions passed.")
tmpdir.cleanup()
