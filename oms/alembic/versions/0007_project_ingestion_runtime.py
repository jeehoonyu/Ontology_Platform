"""Add project-scoped jobs, connectors, streams, and durable ingestion evidence.

Revision ID: 0007_project_ingestion_runtime
Revises: 0006_tenancy_ontology_packages
"""
import sqlalchemy as sa
from alembic import op

revision = "0007_project_ingestion_runtime"
down_revision = "0006_tenancy_ontology_packages"
branch_labels = None
depends_on = None


def _add_project_column(table: str) -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}
    if "project_id" not in columns:
        op.add_column(table, sa.Column("project_id", sa.String(), nullable=False, server_default="default"))
        op.create_index(f"ix_{table}_project_id", table, ["project_id"])


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for table in ("platform_jobs", "connection_sources", "connection_syncs", "connection_exports", "streams"):
        if table in tables:
            _add_project_column(table)
    if "ingestion_runs" not in tables:
        op.create_table(
            "ingestion_runs",
            sa.Column("id", sa.String(), nullable=False), sa.Column("project_id", sa.String(), nullable=False),
            sa.Column("job_id", sa.String(), nullable=True), sa.Column("idempotency_key", sa.String(), nullable=False),
            sa.Column("run_type", sa.String(), nullable=False), sa.Column("resource_type", sa.String(), nullable=False),
            sa.Column("resource_id", sa.String(), nullable=False), sa.Column("status", sa.String(), nullable=False),
            sa.Column("records_in", sa.Integer(), nullable=False), sa.Column("records_out", sa.Integer(), nullable=False),
            sa.Column("bytes_processed", sa.Integer(), nullable=False), sa.Column("estimated_cost_usd", sa.Float(), nullable=False),
            sa.Column("metrics", sa.JSON(), nullable=False), sa.Column("error", sa.String(), nullable=True),
            sa.Column("created_at", sa.Integer(), nullable=False), sa.Column("started_at", sa.Integer(), nullable=True),
            sa.Column("completed_at", sa.Integer(), nullable=True), sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("job_id"), sa.UniqueConstraint("project_id", "idempotency_key", name="uq_ingestion_project_idempotency"),
        )
        for name, columns in (
            ("ix_ingestion_runs_id", ["id"]), ("ix_ingestion_runs_project_id", ["project_id"]),
            ("ix_ingestion_runs_job_id", ["job_id"]), ("ix_ingestion_runs_run_type", ["run_type"]),
            ("ix_ingestion_runs_resource_id", ["resource_id"]), ("ix_ingestion_runs_status", ["status"]),
        ):
            op.create_index(name, "ingestion_runs", columns)
    if "ingestion_budgets" not in tables:
        op.create_table(
            "ingestion_budgets",
            sa.Column("id", sa.String(), nullable=False), sa.Column("project_id", sa.String(), nullable=False),
            sa.Column("metric", sa.String(), nullable=False), sa.Column("limit_value", sa.Float(), nullable=False),
            sa.Column("window_seconds", sa.Integer(), nullable=False), sa.Column("enforcement", sa.String(), nullable=False),
            sa.Column("created_at", sa.Integer(), nullable=False), sa.Column("updated_at", sa.Integer(), nullable=False),
            sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("project_id", "metric", name="uq_ingestion_project_budget_metric"),
        )
        for name, columns in (("ix_ingestion_budgets_id", ["id"]), ("ix_ingestion_budgets_project_id", ["project_id"]), ("ix_ingestion_budgets_metric", ["metric"])):
            op.create_index(name, "ingestion_budgets", columns)
    if "ingestion_dead_letters" not in tables:
        op.create_table(
            "ingestion_dead_letters",
            sa.Column("id", sa.String(), nullable=False), sa.Column("project_id", sa.String(), nullable=False),
            sa.Column("run_id", sa.String(), nullable=False), sa.Column("resource_type", sa.String(), nullable=False),
            sa.Column("resource_id", sa.String(), nullable=False), sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("error", sa.String(), nullable=False), sa.Column("status", sa.String(), nullable=False),
            sa.Column("replay_job_id", sa.String(), nullable=True), sa.Column("attempts", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.Integer(), nullable=False), sa.Column("updated_at", sa.Integer(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        for name, columns in (
            ("ix_ingestion_dead_letters_id", ["id"]), ("ix_ingestion_dead_letters_project_id", ["project_id"]),
            ("ix_ingestion_dead_letters_run_id", ["run_id"]), ("ix_ingestion_dead_letters_resource_id", ["resource_id"]),
            ("ix_ingestion_dead_letters_status", ["status"]),
        ):
            op.create_index(name, "ingestion_dead_letters", columns)


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for table in ("ingestion_dead_letters", "ingestion_budgets", "ingestion_runs"):
        if table in tables:
            op.drop_table(table)
    for table in ("streams", "connection_exports", "connection_syncs", "connection_sources", "platform_jobs"):
        if table in tables and "project_id" in {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}:
            # Drop the index first. SQLite leaves an index referencing the
            # dropped column behind and then rejects the table, while
            # PostgreSQL removes it by cascade.
            indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table)}
            index_name = f"ix_{table}_project_id"
            if index_name in indexes:
                op.drop_index(index_name, table_name=table)
            op.drop_column(table, "project_id")
