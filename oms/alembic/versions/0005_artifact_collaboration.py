"""Add real-time artifact collaboration presence and event records.

Revision ID: 0005_artifact_collaboration
Revises: 0004_agent_execution_evidence
"""
import sqlalchemy as sa
from alembic import op

revision = "0005_artifact_collaboration"
down_revision = "0004_agent_execution_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "platform_artifact_collaborators" not in tables:
        op.create_table(
            "platform_artifact_collaborators",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("artifact_id", sa.String(), nullable=False),
            sa.Column("principal_id", sa.String(), nullable=False),
            sa.Column("display_name", sa.String(), nullable=False),
            sa.Column("client_id", sa.String(), nullable=False),
            sa.Column("token", sa.String(), nullable=False),
            sa.Column("color", sa.String(), nullable=False),
            sa.Column("cursor", sa.JSON(), nullable=False),
            sa.Column("selection", sa.JSON(), nullable=False),
            sa.Column("joined_at", sa.Integer(), nullable=False),
            sa.Column("heartbeat_at", sa.Integer(), nullable=False),
            sa.Column("expires_at", sa.Integer(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("artifact_id", "principal_id", "client_id", name="uq_artifact_collaborator_client"),
            sa.UniqueConstraint("token"),
        )
        for name, columns in (
            ("ix_platform_artifact_collaborators_id", ["id"]),
            ("ix_platform_artifact_collaborators_artifact_id", ["artifact_id"]),
            ("ix_platform_artifact_collaborators_principal_id", ["principal_id"]),
            ("ix_platform_artifact_collaborators_client_id", ["client_id"]),
            ("ix_platform_artifact_collaborators_token", ["token"]),
            ("ix_platform_artifact_collaborators_expires_at", ["expires_at"]),
        ):
            op.create_index(name, "platform_artifact_collaborators", columns)
    if "platform_artifact_collaboration_events" not in tables:
        op.create_table(
            "platform_artifact_collaboration_events",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("artifact_id", sa.String(), nullable=False),
            sa.Column("participant_id", sa.String(), nullable=True),
            sa.Column("actor", sa.String(), nullable=False),
            sa.Column("event_type", sa.String(), nullable=False),
            sa.Column("lock_version", sa.Integer(), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.Integer(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        for name, columns in (
            ("ix_platform_artifact_collaboration_events_artifact_id", ["artifact_id"]),
            ("ix_platform_artifact_collaboration_events_participant_id", ["participant_id"]),
            ("ix_platform_artifact_collaboration_events_actor", ["actor"]),
            ("ix_platform_artifact_collaboration_events_event_type", ["event_type"]),
            ("ix_platform_artifact_collaboration_events_created_at", ["created_at"]),
        ):
            op.create_index(name, "platform_artifact_collaboration_events", columns)


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "platform_artifact_collaboration_events" in tables:
        op.drop_table("platform_artifact_collaboration_events")
    if "platform_artifact_collaborators" in tables:
        op.drop_table("platform_artifact_collaborators")
