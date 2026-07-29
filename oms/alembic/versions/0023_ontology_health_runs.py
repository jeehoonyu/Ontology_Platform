"""Persist ontology health evaluations.

Revision ID: 0023_ontology_health_runs
Revises: 0022_ontology_release_lifecycle
"""
import sqlalchemy as sa
from alembic import op

revision = "0023_ontology_health_runs"
down_revision = "0022_ontology_release_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "ontology_health_runs" in set(sa.inspect(bind).get_table_names()):
        return
    op.create_table(
        "ontology_health_runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("object_type_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("findings", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
    )
    for column in ("project_id", "object_type_id", "status", "created_at"):
        op.create_index(f"ix_ontology_health_runs_{column}", "ontology_health_runs", [column])


def downgrade() -> None:
    bind = op.get_bind()
    if "ontology_health_runs" in set(sa.inspect(bind).get_table_names()):
        op.drop_table("ontology_health_runs")
