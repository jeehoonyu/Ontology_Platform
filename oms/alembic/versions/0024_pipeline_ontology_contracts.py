"""Persist pipeline-to-ontology contract reconciliation evidence.

Revision ID: 0024_pipeline_ontology_contracts
Revises: 0023_ontology_health_runs
"""
import sqlalchemy as sa
from alembic import op

revision = "0024_pipeline_ontology_contracts"
down_revision = "0023_ontology_health_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "pipeline_ontology_contract_runs" in set(sa.inspect(bind).get_table_names()):
        return
    op.create_table(
        "pipeline_ontology_contract_runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("graph_id", sa.String(), nullable=False),
        sa.Column("build_id", sa.String(), nullable=False),
        sa.Column("node_id", sa.String(), nullable=False),
        sa.Column("object_type_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("input_rows", sa.Integer(), nullable=False),
        sa.Column("accepted_rows", sa.Integer(), nullable=False),
        sa.Column("rejected_rows", sa.Integer(), nullable=False),
        sa.Column("created_objects", sa.Integer(), nullable=False),
        sa.Column("updated_objects", sa.Integer(), nullable=False),
        sa.Column("unchanged_objects", sa.Integer(), nullable=False),
        sa.Column("quarantine_asset_id", sa.String(), nullable=True),
        sa.Column("field_lineage", sa.JSON(), nullable=False),
        sa.Column("violations", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
    )
    for column in (
        "project_id", "graph_id", "build_id", "node_id", "object_type_id",
        "status", "quarantine_asset_id", "created_at",
    ):
        op.create_index(
            f"ix_pipeline_ontology_contract_runs_{column}",
            "pipeline_ontology_contract_runs",
            [column],
        )


def downgrade() -> None:
    bind = op.get_bind()
    if "pipeline_ontology_contract_runs" in set(sa.inspect(bind).get_table_names()):
        op.drop_table("pipeline_ontology_contract_runs")
