"""Add columns introduced before persisted Alembic history.

Revision ID: 0002_legacy_column_compat
Revises: 0001_runtime_baseline
"""
import os

import sqlalchemy as sa
from alembic import op

revision = "0002_legacy_column_compat"
down_revision = "0001_runtime_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    os.environ["SKIP_CREATE_ALL"] = "1"
    from app.database import Base
    from app import main  # noqa: F401 - registers all model metadata

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    for table_name, table in Base.metadata.tables.items():
        if table_name not in existing_tables:
            table.create(bind=bind, checkfirst=True)
            continue
        existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
        for column in table.columns:
            if column.name in existing_columns:
                continue
            # Legacy rows cannot satisfy newly introduced required fields. The
            # application applies current defaults to every new write, while the
            # compatibility column remains nullable for old records.
            op.add_column(
                table_name,
                sa.Column(column.name, column.type, nullable=True),
            )


def downgrade() -> None:
    # Additive compatibility upgrades are intentionally restored from backup.
    pass
