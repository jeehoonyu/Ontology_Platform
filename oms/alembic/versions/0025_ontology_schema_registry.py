"""Persist immutable ontology schema registry publications.

Revision ID: 0025_ontology_schema_registry
Revises: 0024_pipeline_ontology_contracts
"""
import sqlalchemy as sa
from alembic import op

revision = "0025_ontology_schema_registry"
down_revision = "0024_pipeline_ontology_contracts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "ontology_registry_entries" in set(sa.inspect(bind).get_table_names()):
        return
    op.create_table(
        "ontology_registry_entries",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("channel", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("revision_id", sa.String(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("manifest", sa.JSON(), nullable=False),
        sa.Column("contract_schema", sa.JSON(), nullable=False),
        sa.Column("compatibility", sa.JSON(), nullable=False),
        sa.Column("checksum", sa.String(), nullable=False),
        sa.Column("published_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.UniqueConstraint("project_id", "channel", "version", name="uq_ontology_registry_project_channel_version"),
    )
    for column in ("project_id", "channel", "version", "revision_id", "status", "checksum", "created_at"):
        op.create_index(f"ix_ontology_registry_entries_{column}", "ontology_registry_entries", [column])


def downgrade() -> None:
    bind = op.get_bind()
    if "ontology_registry_entries" in set(sa.inspect(bind).get_table_names()):
        op.drop_table("ontology_registry_entries")
