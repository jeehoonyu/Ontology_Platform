"""Add the OntologyOS semantic, temporal, data-plane, and model-gateway core.

Revision ID: 0026_ontologyos_runtime_core
Revises: 0025_ontology_schema_registry
"""

import sqlalchemy as sa
from alembic import op


revision = "0026_ontologyos_runtime_core"
down_revision = "0025_ontology_schema_registry"
branch_labels = None
depends_on = None


def _tables(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def upgrade() -> None:
    bind = op.get_bind()
    existing = _tables(bind)

    if "ontology_property_definitions" not in existing:
        op.create_table(
            "ontology_property_definitions",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("project_id", sa.String(), nullable=False),
            sa.Column("object_type_id", sa.String(), nullable=False),
            sa.Column("property_name", sa.String(), nullable=False),
            sa.Column("display_name", sa.String(), nullable=False),
            sa.Column("base_type", sa.String(), nullable=False),
            sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("primary_key", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("title_key", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("indexed", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("status", sa.String(), nullable=False, server_default="ACTIVE"),
            sa.Column("definition", sa.JSON(), nullable=False),
            sa.Column("ontology_revision_id", sa.String(), nullable=True),
            sa.Column("created_at", sa.Integer(), nullable=False),
            sa.Column("updated_at", sa.Integer(), nullable=False),
            sa.UniqueConstraint("project_id", "object_type_id", "property_name", name="uq_ontology_property_project_type_name"),
        )
        for column in ("project_id", "object_type_id", "base_type", "status", "ontology_revision_id"):
            op.create_index(f"ix_ontology_property_definitions_{column}", "ontology_property_definitions", [column])

    if "ontology_resource_definitions" not in existing:
        op.create_table(
            "ontology_resource_definitions",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("project_id", sa.String(), nullable=False),
            sa.Column("resource_kind", sa.String(), nullable=False),
            sa.Column("resource_id", sa.String(), nullable=False),
            sa.Column("object_type_id", sa.String(), nullable=True),
            sa.Column("display_name", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="ACTIVE"),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("definition", sa.JSON(), nullable=False),
            sa.Column("ontology_revision_id", sa.String(), nullable=True),
            sa.Column("created_at", sa.Integer(), nullable=False),
            sa.Column("updated_at", sa.Integer(), nullable=False),
            sa.UniqueConstraint("project_id", "resource_kind", "resource_id", name="uq_ontology_resource_project_kind_id"),
        )
        for column in ("project_id", "resource_kind", "resource_id", "object_type_id", "status", "ontology_revision_id"):
            op.create_index(f"ix_ontology_resource_definitions_{column}", "ontology_resource_definitions", [column])

    if "object_change_events" not in existing:
        op.create_table(
            "object_change_events",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("project_id", sa.String(), nullable=False),
            sa.Column("object_type_id", sa.String(), nullable=False),
            sa.Column("object_id", sa.String(), nullable=False),
            sa.Column("object_version", sa.Integer(), nullable=False),
            sa.Column("event_type", sa.String(), nullable=False),
            sa.Column("actor", sa.String(), nullable=False),
            sa.Column("source_type", sa.String(), nullable=False),
            sa.Column("source_id", sa.String(), nullable=True),
            sa.Column("before_state", sa.JSON(), nullable=False),
            sa.Column("after_state", sa.JSON(), nullable=False),
            sa.Column("changed_fields", sa.JSON(), nullable=False),
            sa.Column("evidence", sa.JSON(), nullable=False),
            sa.Column("ontology_revision_id", sa.String(), nullable=True),
            sa.Column("valid_from", sa.Integer(), nullable=False),
            sa.Column("valid_to", sa.Integer(), nullable=True),
            sa.Column("transaction_time", sa.Integer(), nullable=False),
            sa.UniqueConstraint("project_id", "object_id", "object_version", name="uq_object_change_project_object_version"),
        )
        for column in ("project_id", "object_type_id", "object_id", "event_type", "source_type", "transaction_time"):
            op.create_index(f"ix_object_change_events_{column}", "object_change_events", [column])
        op.create_index("ix_object_change_events_object_time", "object_change_events", ["project_id", "object_id", "transaction_time"])

    if "data_asset_snapshots" not in existing:
        op.create_table(
            "data_asset_snapshots",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("project_id", sa.String(), nullable=False),
            sa.Column("asset_id", sa.String(), nullable=False),
            sa.Column("snapshot_number", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("storage_format", sa.String(), nullable=False),
            sa.Column("storage_uri", sa.String(), nullable=False),
            sa.Column("content_hash", sa.String(), nullable=False),
            sa.Column("row_count", sa.Integer(), nullable=False),
            sa.Column("byte_size", sa.Integer(), nullable=False),
            sa.Column("schema", sa.JSON(), nullable=False),
            sa.Column("partition_spec", sa.JSON(), nullable=False),
            sa.Column("lineage", sa.JSON(), nullable=False),
            sa.Column("created_by", sa.String(), nullable=False),
            sa.Column("created_at", sa.Integer(), nullable=False),
            sa.UniqueConstraint("project_id", "asset_id", "snapshot_number", name="uq_data_snapshot_project_asset_number"),
        )
        for column in ("project_id", "asset_id", "status", "content_hash", "created_at"):
            op.create_index(f"ix_data_asset_snapshots_{column}", "data_asset_snapshots", [column])

    if "pipeline_execution_plans" not in existing:
        op.create_table(
            "pipeline_execution_plans",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("project_id", sa.String(), nullable=False),
            sa.Column("graph_id", sa.String(), nullable=False),
            sa.Column("graph_updated_at", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("executor", sa.String(), nullable=False),
            sa.Column("plan_hash", sa.String(), nullable=False),
            sa.Column("logical_plan", sa.JSON(), nullable=False),
            sa.Column("input_schema", sa.JSON(), nullable=False),
            sa.Column("output_schema", sa.JSON(), nullable=False),
            sa.Column("field_lineage", sa.JSON(), nullable=False),
            sa.Column("validation", sa.JSON(), nullable=False),
            sa.Column("created_by", sa.String(), nullable=False),
            sa.Column("created_at", sa.Integer(), nullable=False),
        )
        for column in ("project_id", "graph_id", "status", "executor", "plan_hash", "created_at"):
            op.create_index(f"ix_pipeline_execution_plans_{column}", "pipeline_execution_plans", [column])

    if "model_gateway_providers" not in existing:
        op.create_table(
            "model_gateway_providers",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("project_id", sa.String(), nullable=False),
            sa.Column("display_name", sa.String(), nullable=False),
            sa.Column("provider_type", sa.String(), nullable=False),
            sa.Column("base_url", sa.String(), nullable=True),
            sa.Column("secret_ref", sa.String(), nullable=True),
            sa.Column("allowed_models", sa.JSON(), nullable=False),
            sa.Column("policy", sa.JSON(), nullable=False),
            sa.Column("configuration", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("created_at", sa.Integer(), nullable=False),
            sa.Column("updated_at", sa.Integer(), nullable=False),
        )
        for column in ("project_id", "provider_type", "status"):
            op.create_index(f"ix_model_gateway_providers_{column}", "model_gateway_providers", [column])

    if "model_gateway_runs" not in existing:
        op.create_table(
            "model_gateway_runs",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("project_id", sa.String(), nullable=False),
            sa.Column("provider_id", sa.String(), nullable=False),
            sa.Column("model_name", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("request_hash", sa.String(), nullable=False),
            sa.Column("idempotency_key", sa.String(), nullable=True),
            sa.Column("input_summary", sa.JSON(), nullable=False),
            sa.Column("output", sa.JSON(), nullable=False),
            sa.Column("usage", sa.JSON(), nullable=False),
            sa.Column("policy_decision", sa.JSON(), nullable=False),
            sa.Column("trace", sa.JSON(), nullable=False),
            sa.Column("evidence", sa.JSON(), nullable=False),
            sa.Column("error", sa.String(), nullable=True),
            sa.Column("created_by", sa.String(), nullable=False),
            sa.Column("created_at", sa.Integer(), nullable=False),
            sa.Column("completed_at", sa.Integer(), nullable=True),
            sa.UniqueConstraint("project_id", "provider_id", "created_by", "idempotency_key", name="uq_model_gateway_run_idempotency"),
        )
        for column in ("project_id", "provider_id", "model_name", "status", "request_hash", "idempotency_key", "created_at"):
            op.create_index(f"ix_model_gateway_runs_{column}", "model_gateway_runs", [column])


def downgrade() -> None:
    bind = op.get_bind()
    existing = _tables(bind)
    for table_name in (
        "model_gateway_runs",
        "model_gateway_providers",
        "pipeline_execution_plans",
        "data_asset_snapshots",
        "object_change_events",
        "ontology_resource_definitions",
        "ontology_property_definitions",
    ):
        if table_name in existing:
            op.drop_table(table_name)
