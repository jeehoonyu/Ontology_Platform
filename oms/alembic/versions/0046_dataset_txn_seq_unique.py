"""Give every dataset transaction its own sequence number on its branch.

Section 4 of the 2026-09-23 survey, decision F. `seq` was read as the branch's highest plus
one and written with nothing to stop two commits reading the same highest, so one branch of
one dataset could hold two transactions with one number, and on master the mirror kept only
the second. A unique index on (dataset_id, branch, seq) stops new ones, and the writer
retries a commit that loses.

What already collided is renumbered first, and only on the branches that hold a collision.
The order is the one readers already fold the log in -- seq, then created_at -- with the
insertion order breaking what those two cannot, so every current view is unchanged. Every
number after the first collision on such a branch moves up; nothing else moves.

Revision ID: 0046_dataset_txn_seq_unique
Revises: 0045_entity_exact_pass
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0046_dataset_txn_seq_unique"
down_revision = "0045_entity_exact_pass"
branch_labels = None
depends_on = None

TABLE = "dataset_transactions"
INDEX = "uq_dataset_transactions_dataset_branch_seq"
REQUIRED = {"id", "dataset_id", "branch", "seq", "created_at"}

# The branches holding a collision, and each of their rows' place in fold order. SQLite
# records insertion order as rowid; Postgres records none, and ctid is its nearest reading.
RENUMBER = """
UPDATE dataset_transactions SET seq = renumbered.new_seq
FROM (
    SELECT x.id AS id,
           ROW_NUMBER() OVER (PARTITION BY x.dataset_id, x.branch
                              ORDER BY x.seq, x.created_at, {insertion}) - 1 AS new_seq
    FROM dataset_transactions x
    WHERE EXISTS (
        SELECT 1 FROM dataset_transactions d
        WHERE d.dataset_id = x.dataset_id AND d.branch = x.branch
        GROUP BY d.seq HAVING COUNT(*) > 1
    )
) AS renumbered
WHERE dataset_transactions.id = renumbered.id AND dataset_transactions.seq <> renumbered.new_seq
"""


def _indexes(bind) -> set:
    return {index["name"] for index in sa.inspect(bind).get_indexes(TABLE)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    # Guarded, like 0044 and 0045: CI applies the chain twice, and some tests build partial schemas.
    if not inspector.has_table(TABLE):
        return
    if not REQUIRED <= {column["name"] for column in inspector.get_columns(TABLE)}:
        return
    if bind.dialect.name == "postgresql":
        # A replica still on the old code must not add a collision between the renumber and the index.
        bind.execute(sa.text(f"LOCK TABLE {TABLE} IN SHARE ROW EXCLUSIVE MODE"))
    insertion = "x.rowid" if bind.dialect.name == "sqlite" else "x.ctid"
    bind.execute(sa.text(RENUMBER.format(insertion=insertion)))
    # 0001 builds today's models, so a fresh chain already has the index.
    if INDEX not in _indexes(bind):
        op.create_index(INDEX, TABLE, ["dataset_id", "branch", "seq"], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table(TABLE) and INDEX in _indexes(bind):
        op.drop_index(INDEX, table_name=TABLE)
    # The renumbering is not undone: the numbers it gave are as good as the ones it replaced.
