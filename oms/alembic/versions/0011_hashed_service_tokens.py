"""Hash API and worker service token secrets.

Revision ID: 0011_hashed_service_tokens
Revises: 0010_live_connector_runtime
"""
import hashlib

import sqlalchemy as sa
from alembic import op

revision = "0011_hashed_service_tokens"
down_revision = "0010_live_connector_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "admin_api_tokens" not in tables:
        op.create_table(
            "admin_api_tokens",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("token", sa.String(), nullable=False),
            sa.Column("token_hash", sa.String(length=64), nullable=True),
            sa.Column("token_prefix", sa.String(length=20), nullable=True),
            sa.Column("principal_type", sa.String(), nullable=False),
            sa.Column("principal_id", sa.String(), nullable=False),
            sa.Column("scopes", sa.JSON(), nullable=False),
            sa.Column("expires_at", sa.Integer(), nullable=True),
            sa.Column("revoked", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.Integer(), nullable=False),
            sa.Column("last_used_at", sa.Integer(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_admin_api_tokens_id", "admin_api_tokens", ["id"])
        op.create_index("ix_admin_api_tokens_token", "admin_api_tokens", ["token"])
        op.create_index("ix_admin_api_tokens_token_hash", "admin_api_tokens", ["token_hash"], unique=True)
        op.create_index("ix_admin_api_tokens_principal_id", "admin_api_tokens", ["principal_id"])
        return
    columns = {column["name"] for column in sa.inspect(bind).get_columns("admin_api_tokens")}
    if "token_hash" not in columns:
        op.add_column("admin_api_tokens", sa.Column("token_hash", sa.String(length=64), nullable=True))
        op.create_index("ix_admin_api_tokens_token_hash", "admin_api_tokens", ["token_hash"], unique=True)
    if "token_prefix" not in columns:
        op.add_column("admin_api_tokens", sa.Column("token_prefix", sa.String(length=20), nullable=True))
    if "last_used_at" not in columns:
        op.add_column("admin_api_tokens", sa.Column("last_used_at", sa.Integer(), nullable=True))
    rows = bind.execute(sa.text("SELECT id, token FROM admin_api_tokens WHERE token IS NOT NULL AND token <> ''")).mappings().all()
    for row in rows:
        digest = hashlib.sha256(str(row["token"]).encode("utf-8")).hexdigest()
        bind.execute(sa.text("UPDATE admin_api_tokens SET token_hash=:digest, token_prefix=:prefix, token=:marker WHERE id=:id"), {
            "digest": digest, "prefix": str(row["token"])[:12], "marker": f"hashed:{row['id']}", "id": row["id"],
        })


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "admin_api_tokens" not in tables:
        return
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("admin_api_tokens")}
    if "last_used_at" in columns:
        op.drop_column("admin_api_tokens", "last_used_at")
    if "token_prefix" in columns:
        op.drop_column("admin_api_tokens", "token_prefix")
    if "token_hash" in columns:
        op.drop_index("ix_admin_api_tokens_token_hash", table_name="admin_api_tokens")
        op.drop_column("admin_api_tokens", "token_hash")
