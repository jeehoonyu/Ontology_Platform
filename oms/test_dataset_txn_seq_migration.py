"""Dataset transaction sequence numbers: renumbered where they collided, then held unique.

Migration 0046. Before it, two commits could share a number on a branch. The upgrade renumbers
only the branches holding a collision, in the order readers fold the log -- seq, then
created_at, then insertion -- so each branch's current view is unchanged, and then builds the
unique index. A branch with no collision keeps its numbers. The index then refuses a new
collision, and the downgrade drops only the index.
"""

import os
import subprocess
import sys
import tempfile

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from tier_b_evidence import current_head

PRIOR = "0045_entity_exact_pass"
INDEX = "uq_dataset_transactions_dataset_branch_seq"

with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
    database_url = f"sqlite:///{os.path.join(temporary, 'dataset-txn-seq-migration.db')}"
    env = {**os.environ, "DATABASE_URL": database_url, "APP_ENV": "test", "AUTH_MODE": "local"}

    def alembic(*args):
        completed = subprocess.run(
            [sys.executable, "-m", "alembic", "-c", "alembic.ini", *args],
            cwd=os.path.dirname(__file__), env=env, capture_output=True, text=True,
        )
        assert completed.returncode == 0, f"{completed.stdout}\n{completed.stderr}"

    def indexes(connection):
        return {row["name"] for row in inspect(connection).get_indexes("dataset_transactions")}

    def numbers(connection, dataset, branch):
        return [tuple(row) for row in connection.execute(text(
            "SELECT id, seq FROM dataset_transactions WHERE dataset_id = :d AND branch = :b ORDER BY seq"
        ), {"d": dataset, "b": branch})]

    alembic("upgrade", PRIOR)
    engine = create_engine(database_url)
    with engine.begin() as connection:
        # 0001 builds today's models, so a fresh chain already has the index. Drop it to stand
        # for a database that reached 0045 before it existed, then write the collisions it allowed.
        if INDEX in indexes(connection):
            connection.execute(text(f"DROP INDEX {INDEX}"))
        rows = [
            # master: a SNAPSHOT, then two APPENDs that raced for seq 1, then one more.
            ("m0", "ds", "master", 0, 100), ("m1a", "ds", "master", 1, 110), ("m1b", "ds", "master", 1, 110),
            ("m2", "ds", "master", 2, 120),
            # dev was created twice: seed SNAPSHOT, an APPEND, then a second seed at seq 0.
            ("d0a", "ds", "dev", 0, 150), ("d1", "ds", "dev", 1, 160), ("d0b", "ds", "dev", 0, 400),
            # A clean branch of another dataset keeps its numbers, gap and all.
            ("c0", "clean", "master", 0, 100), ("c5", "clean", "master", 5, 200),
        ]
        for txn_id, dataset, branch, seq, created in rows:
            connection.execute(text(
                "INSERT INTO dataset_transactions (id, dataset_id, branch, txn_type, primary_key, records, row_count, status, seq, created_at) "
                "VALUES (:id, :d, :b, 'APPEND', 'id', '[]', 0, 'COMMITTED', :s, :c)"
            ), {"id": txn_id, "d": dataset, "b": branch, "s": seq, "c": created})
        assert INDEX not in indexes(connection), "the prior head still has the unique index"

    alembic("upgrade", "head")
    with engine.connect() as connection:
        assert INDEX in indexes(connection), "the upgrade did not build the unique index"
        master = numbers(connection, "ds", "master")
        assert master == [("m0", 0), ("m1a", 1), ("m1b", 2), ("m2", 3)], master
        dev = numbers(connection, "ds", "dev")
        # Fold order was (seq, created_at): d0a, d0b, d1. Renumbered in that order, the view is unchanged.
        assert dev == [("d0a", 0), ("d0b", 1), ("d1", 2)], dev
        clean = numbers(connection, "clean", "master")
        assert clean == [("c0", 0), ("c5", 5)], f"a branch with no collision was renumbered: {clean}"
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == current_head()

    # The index refuses a new collision.
    try:
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO dataset_transactions (id, dataset_id, branch, txn_type, primary_key, records, row_count, status, seq, created_at) "
                "VALUES ('again', 'ds', 'master', 'APPEND', 'id', '[]', 0, 'COMMITTED', 3, 500)"))
        raise AssertionError("a second transaction took seq 3 on master")
    except IntegrityError:
        pass

    # Applied twice, as CI does.
    alembic("upgrade", "head")

    alembic("downgrade", PRIOR)
    with engine.connect() as connection:
        assert INDEX not in indexes(connection), "the downgrade left the index"
        assert numbers(connection, "ds", "dev") == [("d0a", 0), ("d0b", 1), ("d1", 2)], "the downgrade moved numbers"

    alembic("upgrade", "head")
    with engine.connect() as connection:
        assert INDEX in indexes(connection)
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == current_head()
    engine.dispose()

print("Dataset transaction sequence migration verified.")
