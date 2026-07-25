"""Add project-scoped runtime observations, budgets, and SLO evidence.

Revision ID: 0008_runtime_observability
Revises: 0007_project_ingestion_runtime
"""
import sqlalchemy as sa
from alembic import op

revision = "0008_runtime_observability"
down_revision = "0007_project_ingestion_runtime"
branch_labels = None
depends_on = None


def _indexes(table: str, specs: list[tuple[str, list[str]]]) -> None:
    for name, columns in specs:
        op.create_index(name, table, columns)


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "runtime_job_observations" not in tables:
        op.create_table(
            "runtime_job_observations",
            sa.Column("id", sa.String(), nullable=False), sa.Column("project_id", sa.String(), nullable=False),
            sa.Column("job_id", sa.String(), nullable=False), sa.Column("correlation_id", sa.String(), nullable=False),
            sa.Column("job_type", sa.String(), nullable=False), sa.Column("actor", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False), sa.Column("attempt", sa.Integer(), nullable=False),
            sa.Column("progress", sa.Integer(), nullable=False), sa.Column("queue_latency_ms", sa.Integer(), nullable=False),
            sa.Column("duration_ms", sa.Integer(), nullable=False), sa.Column("compute_seconds", sa.Float(), nullable=False),
            sa.Column("token_units", sa.Float(), nullable=False), sa.Column("record_units", sa.Float(), nullable=False),
            sa.Column("estimated_cost_usd", sa.Float(), nullable=False), sa.Column("metrics", sa.JSON(), nullable=False),
            sa.Column("spans", sa.JSON(), nullable=False), sa.Column("error", sa.String(), nullable=True),
            sa.Column("created_at", sa.Integer(), nullable=False), sa.Column("updated_at", sa.Integer(), nullable=False),
            sa.Column("completed_at", sa.Integer(), nullable=True), sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("job_id"),
        )
        _indexes("runtime_job_observations", [
            ("ix_runtime_job_observations_id", ["id"]), ("ix_runtime_job_observations_project_id", ["project_id"]),
            ("ix_runtime_job_observations_job_id", ["job_id"]), ("ix_runtime_job_observations_correlation_id", ["correlation_id"]),
            ("ix_runtime_job_observations_job_type", ["job_type"]), ("ix_runtime_job_observations_actor", ["actor"]),
            ("ix_runtime_job_observations_status", ["status"]),
        ])
    if "runtime_budget_policies" not in tables:
        op.create_table(
            "runtime_budget_policies",
            sa.Column("id", sa.String(), nullable=False), sa.Column("project_id", sa.String(), nullable=False),
            sa.Column("metric", sa.String(), nullable=False), sa.Column("limit_value", sa.Float(), nullable=False),
            sa.Column("window_seconds", sa.Integer(), nullable=False), sa.Column("enforcement", sa.String(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False), sa.Column("created_at", sa.Integer(), nullable=False),
            sa.Column("updated_at", sa.Integer(), nullable=False), sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("project_id", "metric", name="uq_runtime_project_budget_metric"),
        )
        _indexes("runtime_budget_policies", [("ix_runtime_budget_policies_id", ["id"]), ("ix_runtime_budget_policies_project_id", ["project_id"]), ("ix_runtime_budget_policies_metric", ["metric"])])
    if "runtime_slo_policies" not in tables:
        op.create_table(
            "runtime_slo_policies",
            sa.Column("id", sa.String(), nullable=False), sa.Column("project_id", sa.String(), nullable=False),
            sa.Column("display_name", sa.String(), nullable=False), sa.Column("job_type", sa.String(), nullable=True),
            sa.Column("metric", sa.String(), nullable=False), sa.Column("operator", sa.String(), nullable=False),
            sa.Column("threshold", sa.Float(), nullable=False), sa.Column("window_seconds", sa.Integer(), nullable=False),
            sa.Column("severity", sa.String(), nullable=False), sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.Integer(), nullable=False), sa.Column("updated_at", sa.Integer(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        _indexes("runtime_slo_policies", [("ix_runtime_slo_policies_id", ["id"]), ("ix_runtime_slo_policies_project_id", ["project_id"]), ("ix_runtime_slo_policies_job_type", ["job_type"])])
    if "runtime_slo_evaluations" not in tables:
        op.create_table(
            "runtime_slo_evaluations",
            sa.Column("id", sa.String(), nullable=False), sa.Column("project_id", sa.String(), nullable=False),
            sa.Column("policy_id", sa.String(), nullable=False), sa.Column("status", sa.String(), nullable=False),
            sa.Column("observed_value", sa.Float(), nullable=False), sa.Column("threshold", sa.Float(), nullable=False),
            sa.Column("sample_count", sa.Integer(), nullable=False), sa.Column("details", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.Integer(), nullable=False), sa.PrimaryKeyConstraint("id"),
        )
        _indexes("runtime_slo_evaluations", [("ix_runtime_slo_evaluations_id", ["id"]), ("ix_runtime_slo_evaluations_project_id", ["project_id"]), ("ix_runtime_slo_evaluations_policy_id", ["policy_id"]), ("ix_runtime_slo_evaluations_status", ["status"])])


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for table in ("runtime_slo_evaluations", "runtime_slo_policies", "runtime_budget_policies", "runtime_job_observations"):
        if table in tables:
            op.drop_table(table)
