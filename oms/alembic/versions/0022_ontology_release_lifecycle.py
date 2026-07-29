"""Add immutable ontology revisions, change sets, and release environments.

Revision ID: 0022_ontology_release_lifecycle
Revises: 0021_project_operational_plane
"""
import sqlalchemy as sa
from alembic import op

revision = "0022_ontology_release_lifecycle"
down_revision = "0021_project_operational_plane"
branch_labels = None
depends_on = None


def _table_names(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _columns(bind, table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(table_name)}


def _indexes(bind, table_name: str) -> set[str]:
    return {index["name"] for index in sa.inspect(bind).get_indexes(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    existing = _table_names(bind)

    for table_name in ("ontology_branches", "ontology_proposals"):
        if table_name not in existing:
            continue
        if "project_id" not in _columns(bind, table_name):
            with op.batch_alter_table(table_name) as batch:
                batch.add_column(sa.Column("project_id", sa.String(), nullable=False, server_default="default"))
        index_name = f"ix_{table_name}_project_id"
        if index_name not in _indexes(bind, table_name):
            op.create_index(index_name, table_name, ["project_id"])

    if "ontology_revisions" not in existing:
        op.create_table(
            "ontology_revisions",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("project_id", sa.String(), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="DRAFT"),
            sa.Column("parent_revision_id", sa.String(), nullable=True),
            sa.Column("branch_id", sa.String(), nullable=True),
            sa.Column("manifest", sa.JSON(), nullable=False),
            sa.Column("checksum", sa.String(), nullable=False),
            sa.Column("validation", sa.JSON(), nullable=False),
            sa.Column("created_by", sa.String(), nullable=False),
            sa.Column("created_at", sa.Integer(), nullable=False),
            sa.Column("published_at", sa.Integer(), nullable=True),
            sa.UniqueConstraint("project_id", "revision", name="uq_ontology_revision_project_number"),
        )
        op.create_index("ix_ontology_revisions_project_id", "ontology_revisions", ["project_id"])
        op.create_index("ix_ontology_revisions_status", "ontology_revisions", ["status"])
        op.create_index("ix_ontology_revisions_parent_revision_id", "ontology_revisions", ["parent_revision_id"])
        op.create_index("ix_ontology_revisions_branch_id", "ontology_revisions", ["branch_id"])

    if "ontology_change_sets" not in existing:
        op.create_table(
            "ontology_change_sets",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("project_id", sa.String(), nullable=False),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("description", sa.String(), nullable=True),
            sa.Column("base_revision_id", sa.String(), nullable=True),
            sa.Column("draft_revision_id", sa.String(), nullable=False),
            sa.Column("proposal_id", sa.String(), nullable=True),
            sa.Column("status", sa.String(), nullable=False, server_default="DRAFT"),
            sa.Column("changes", sa.JSON(), nullable=False),
            sa.Column("diff", sa.JSON(), nullable=False),
            sa.Column("impact", sa.JSON(), nullable=False),
            sa.Column("validation", sa.JSON(), nullable=False),
            sa.Column("migration_plan", sa.JSON(), nullable=False),
            sa.Column("created_by", sa.String(), nullable=False),
            sa.Column("reviewer", sa.String(), nullable=True),
            sa.Column("created_at", sa.Integer(), nullable=False),
            sa.Column("updated_at", sa.Integer(), nullable=False),
        )
        for column in ("project_id", "base_revision_id", "draft_revision_id", "proposal_id", "status"):
            op.create_index(f"ix_ontology_change_sets_{column}", "ontology_change_sets", [column])

    if "ontology_environments" not in existing:
        op.create_table(
            "ontology_environments",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("project_id", sa.String(), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("current_revision_id", sa.String(), nullable=True),
            sa.Column("previous_revision_id", sa.String(), nullable=True),
            sa.Column("updated_by", sa.String(), nullable=False),
            sa.Column("updated_at", sa.Integer(), nullable=False),
            sa.UniqueConstraint("project_id", "name", name="uq_ontology_environment_project_name"),
        )
        op.create_index("ix_ontology_environments_project_id", "ontology_environments", ["project_id"])
        op.create_index("ix_ontology_environments_current_revision_id", "ontology_environments", ["current_revision_id"])


def downgrade() -> None:
    bind = op.get_bind()
    existing = _table_names(bind)
    for table_name in ("ontology_environments", "ontology_change_sets", "ontology_revisions"):
        if table_name in existing:
            op.drop_table(table_name)
    for table_name in ("ontology_proposals", "ontology_branches"):
        if table_name not in existing or "project_id" not in _columns(bind, table_name):
            continue
        index_name = f"ix_{table_name}_project_id"
        if index_name in _indexes(bind, table_name):
            op.drop_index(index_name, table_name=table_name)
        with op.batch_alter_table(table_name) as batch:
            batch.drop_column("project_id")
