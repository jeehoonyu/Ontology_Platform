"""Add governed ontology query indexes and PostgreSQL JSONB state.

Revision ID: 0027_ontology_query_indexes
Revises: 0026_ontologyos_runtime_core
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0027_ontology_query_indexes"
down_revision = "0026_ontologyos_runtime_core"
branch_labels = None
depends_on = None


def _tables(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _indexes(bind, table_name: str) -> set[str]:
    return {row["name"] for row in sa.inspect(bind).get_indexes(table_name)}


def _columns(bind, table_name: str) -> set[str]:
    return {row["name"] for row in sa.inspect(bind).get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    existing = _tables(bind)

    if "ontology_index_definitions" not in existing:
        op.create_table(
            "ontology_index_definitions",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("project_id", sa.String(), nullable=False),
            sa.Column("object_type_id", sa.String(), nullable=False),
            sa.Column("property_name", sa.String(), nullable=False),
            sa.Column("base_type", sa.String(), nullable=False),
            sa.Column("index_name", sa.String(), nullable=False, unique=True),
            sa.Column("strategy", sa.String(), nullable=False, server_default="BTREE_EXPRESSION"),
            sa.Column("status", sa.String(), nullable=False, server_default="PLANNED"),
            sa.Column("ddl", sa.String(), nullable=True),
            sa.Column("last_error", sa.String(), nullable=True),
            sa.Column("created_by", sa.String(), nullable=False),
            sa.Column("created_at", sa.Integer(), nullable=False),
            sa.Column("updated_at", sa.Integer(), nullable=False),
            sa.Column("applied_at", sa.Integer(), nullable=True),
            sa.UniqueConstraint(
                "project_id", "object_type_id", "property_name", "strategy",
                name="uq_ontology_index_project_type_property_strategy",
            ),
        )
        for column in ("project_id", "object_type_id", "property_name", "status"):
            op.create_index(f"ix_ontology_index_definitions_{column}", "ontology_index_definitions", [column])

    if "object_instances" in existing:
        object_columns = _columns(bind, "object_instances")
        current_indexes = _indexes(bind, "object_instances")
        if {"project_id", "object_type_id", "updated_at", "id"} <= object_columns and "ix_object_instances_project_type_updated_id" not in current_indexes:
            op.create_index(
                "ix_object_instances_project_type_updated_id", "object_instances",
                ["project_id", "object_type_id", "updated_at", "id"],
            )
        if bind.dialect.name == "postgresql" and {"properties", "lineage"} <= object_columns:
            op.alter_column(
                "object_instances", "properties", type_=postgresql.JSONB(),
                postgresql_using="properties::jsonb", existing_nullable=False,
            )
            op.alter_column(
                "object_instances", "lineage", type_=postgresql.JSONB(),
                postgresql_using="lineage::jsonb", existing_nullable=False,
            )
            current_indexes = _indexes(bind, "object_instances")
            if "ix_object_instances_properties_gin" not in current_indexes:
                op.execute(
                    "CREATE INDEX ix_object_instances_properties_gin "
                    "ON object_instances USING gin (properties jsonb_path_ops)"
                )

    if "object_change_events" in existing:
        event_indexes = _indexes(bind, "object_change_events")
        if "ix_object_change_events_temporal_lookup" not in event_indexes:
            op.create_index(
                "ix_object_change_events_temporal_lookup", "object_change_events",
                ["project_id", "object_type_id", "object_id", "transaction_time", "object_version"],
            )
        if bind.dialect.name == "postgresql":
            op.alter_column(
                "object_change_events", "before_state", type_=postgresql.JSONB(),
                postgresql_using="before_state::jsonb", existing_nullable=False,
            )
            op.alter_column(
                "object_change_events", "after_state", type_=postgresql.JSONB(),
                postgresql_using="after_state::jsonb", existing_nullable=False,
            )

    if "link_instances" in existing:
        link_columns = _columns(bind, "link_instances")
        link_indexes = _indexes(bind, "link_instances")
        for name, columns in (
            ("ix_link_instances_project_source_id", ["project_id", "source_object_id", "id"]),
            ("ix_link_instances_project_target_id", ["project_id", "target_object_id", "id"]),
            ("ix_link_instances_project_type_id", ["project_id", "link_type_id", "id"]),
        ):
            if set(columns) <= link_columns and name not in link_indexes:
                op.create_index(name, "link_instances", columns)


def downgrade() -> None:
    bind = op.get_bind()
    existing = _tables(bind)
    if "link_instances" in existing:
        indexes = _indexes(bind, "link_instances")
        for name in (
            "ix_link_instances_project_source_id",
            "ix_link_instances_project_target_id",
            "ix_link_instances_project_type_id",
        ):
            if name in indexes:
                op.drop_index(name, table_name="link_instances")
    if "object_change_events" in existing:
        indexes = _indexes(bind, "object_change_events")
        if "ix_object_change_events_temporal_lookup" in indexes:
            op.drop_index("ix_object_change_events_temporal_lookup", table_name="object_change_events")
        if bind.dialect.name == "postgresql":
            op.alter_column(
                "object_change_events", "before_state", type_=sa.JSON(),
                postgresql_using="before_state::json", existing_nullable=False,
            )
            op.alter_column(
                "object_change_events", "after_state", type_=sa.JSON(),
                postgresql_using="after_state::json", existing_nullable=False,
            )
    if "object_instances" in existing:
        object_columns = _columns(bind, "object_instances")
        indexes = _indexes(bind, "object_instances")
        if "ix_object_instances_properties_gin" in indexes:
            op.drop_index("ix_object_instances_properties_gin", table_name="object_instances")
        if "ix_object_instances_project_type_updated_id" in indexes:
            op.drop_index("ix_object_instances_project_type_updated_id", table_name="object_instances")
        if bind.dialect.name == "postgresql" and {"properties", "lineage"} <= object_columns:
            op.alter_column(
                "object_instances", "properties", type_=sa.JSON(),
                postgresql_using="properties::json", existing_nullable=False,
            )
            op.alter_column(
                "object_instances", "lineage", type_=sa.JSON(),
                postgresql_using="lineage::json", existing_nullable=False,
            )
    if "ontology_index_definitions" in existing:
        op.drop_table("ontology_index_definitions")
