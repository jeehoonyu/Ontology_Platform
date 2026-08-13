"""Add project tenancy and governed ontology package records.

Revision ID: 0006_tenancy_ontology_packages
Revises: 0005_artifact_collaboration
"""
import sqlalchemy as sa
from alembic import op

revision = "0006_tenancy_ontology_packages"
down_revision = "0005_artifact_collaboration"
branch_labels = None
depends_on = None


def _index(table: str, name: str, columns: list[str]) -> None:
    op.create_index(name, table, columns)


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "platform_organizations" not in tables:
        op.create_table(
            "platform_organizations",
            sa.Column("id", sa.String(), nullable=False), sa.Column("display_name", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False), sa.Column("created_at", sa.Integer(), nullable=False),
            sa.Column("updated_at", sa.Integer(), nullable=False), sa.PrimaryKeyConstraint("id"),
        )
        _index("platform_organizations", "ix_platform_organizations_id", ["id"])
        _index("platform_organizations", "ix_platform_organizations_status", ["status"])
    if "platform_projects" not in tables:
        op.create_table(
            "platform_projects",
            sa.Column("id", sa.String(), nullable=False), sa.Column("organization_id", sa.String(), nullable=False),
            sa.Column("display_name", sa.String(), nullable=False), sa.Column("description", sa.String(), nullable=True),
            sa.Column("status", sa.String(), nullable=False), sa.Column("created_at", sa.Integer(), nullable=False),
            sa.Column("updated_at", sa.Integer(), nullable=False), sa.PrimaryKeyConstraint("id"),
        )
        for name, columns in (("ix_platform_projects_id", ["id"]), ("ix_platform_projects_organization_id", ["organization_id"]), ("ix_platform_projects_status", ["status"])): _index("platform_projects", name, columns)
    if "platform_project_memberships" not in tables:
        op.create_table(
            "platform_project_memberships",
            sa.Column("id", sa.String(), nullable=False), sa.Column("project_id", sa.String(), nullable=False),
            sa.Column("principal_id", sa.String(), nullable=False), sa.Column("role", sa.String(), nullable=False),
            sa.Column("permissions", sa.JSON(), nullable=False), sa.Column("created_at", sa.Integer(), nullable=False),
            sa.Column("updated_at", sa.Integer(), nullable=False), sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("project_id", "principal_id", name="uq_project_membership_principal"),
        )
        for name, columns in (("ix_platform_project_memberships_id", ["id"]), ("ix_platform_project_memberships_project_id", ["project_id"]), ("ix_platform_project_memberships_principal_id", ["principal_id"])): _index("platform_project_memberships", name, columns)
    if "ontology_packages" not in tables:
        op.create_table(
            "ontology_packages",
            sa.Column("id", sa.String(), nullable=False), sa.Column("organization_id", sa.String(), nullable=False),
            sa.Column("owning_project_id", sa.String(), nullable=False), sa.Column("display_name", sa.String(), nullable=False),
            sa.Column("description", sa.String(), nullable=True), sa.Column("status", sa.String(), nullable=False),
            sa.Column("current_version", sa.String(), nullable=True), sa.Column("created_by", sa.String(), nullable=False),
            sa.Column("created_at", sa.Integer(), nullable=False), sa.Column("updated_at", sa.Integer(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        for name, columns in (("ix_ontology_packages_id", ["id"]), ("ix_ontology_packages_organization_id", ["organization_id"]), ("ix_ontology_packages_owning_project_id", ["owning_project_id"]), ("ix_ontology_packages_status", ["status"])): _index("ontology_packages", name, columns)
    if "ontology_package_versions" not in tables:
        op.create_table(
            "ontology_package_versions",
            sa.Column("id", sa.String(), nullable=False), sa.Column("package_id", sa.String(), nullable=False),
            sa.Column("version", sa.String(), nullable=False), sa.Column("status", sa.String(), nullable=False),
            sa.Column("manifest", sa.JSON(), nullable=False), sa.Column("checksum", sa.String(), nullable=False),
            sa.Column("validation", sa.JSON(), nullable=False), sa.Column("author", sa.String(), nullable=False),
            sa.Column("created_at", sa.Integer(), nullable=False), sa.Column("published_at", sa.Integer(), nullable=True),
            sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("package_id", "version", name="uq_ontology_package_version"),
        )
        for name, columns in (("ix_ontology_package_versions_id", ["id"]), ("ix_ontology_package_versions_package_id", ["package_id"]), ("ix_ontology_package_versions_status", ["status"]), ("ix_ontology_package_versions_checksum", ["checksum"])): _index("ontology_package_versions", name, columns)
    if "ontology_package_installations" not in tables:
        op.create_table(
            "ontology_package_installations",
            sa.Column("id", sa.String(), nullable=False), sa.Column("package_id", sa.String(), nullable=False),
            sa.Column("package_version_id", sa.String(), nullable=False), sa.Column("version", sa.String(), nullable=False),
            sa.Column("target_project_id", sa.String(), nullable=False), sa.Column("namespace", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False), sa.Column("installed_resources", sa.JSON(), nullable=False),
            sa.Column("prior_state", sa.JSON(), nullable=False), sa.Column("previous_installation_id", sa.String(), nullable=True),
            sa.Column("installed_by", sa.String(), nullable=False), sa.Column("installed_at", sa.Integer(), nullable=False),
            sa.Column("rolled_back_at", sa.Integer(), nullable=True), sa.PrimaryKeyConstraint("id"),
        )
        for name, columns in (("ix_ontology_package_installations_id", ["id"]), ("ix_ontology_package_installations_package_id", ["package_id"]), ("ix_ontology_package_installations_package_version_id", ["package_version_id"]), ("ix_ontology_package_installations_target_project_id", ["target_project_id"]), ("ix_ontology_package_installations_namespace", ["namespace"]), ("ix_ontology_package_installations_status", ["status"])): _index("ontology_package_installations", name, columns)
    if "ontology_package_resources" not in tables:
        op.create_table(
            "ontology_package_resources",
            sa.Column("id", sa.String(), nullable=False), sa.Column("package_id", sa.String(), nullable=False),
            sa.Column("installation_id", sa.String(), nullable=False), sa.Column("target_project_id", sa.String(), nullable=False),
            sa.Column("namespace", sa.String(), nullable=False), sa.Column("resource_type", sa.String(), nullable=False),
            sa.Column("resource_id", sa.String(), nullable=False), sa.Column("source_resource_id", sa.String(), nullable=False),
            sa.Column("created_at", sa.Integer(), nullable=False), sa.Column("updated_at", sa.Integer(), nullable=False),
            sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("target_project_id", "resource_type", "resource_id", name="uq_package_project_resource"),
        )
        for name, columns in (("ix_ontology_package_resources_id", ["id"]), ("ix_ontology_package_resources_package_id", ["package_id"]), ("ix_ontology_package_resources_installation_id", ["installation_id"]), ("ix_ontology_package_resources_target_project_id", ["target_project_id"]), ("ix_ontology_package_resources_resource_id", ["resource_id"])): _index("ontology_package_resources", name, columns)


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for table in ("ontology_package_resources", "ontology_package_installations", "ontology_package_versions", "ontology_packages", "platform_project_memberships", "platform_projects", "platform_organizations"):
        if table in tables:
            op.drop_table(table)
