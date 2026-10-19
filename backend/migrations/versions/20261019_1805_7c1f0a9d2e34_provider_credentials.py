"""provider credentials per organization

Revision ID: 7c1f0a9d2e34
Revises: 246fdeef0361
Create Date: 2026-10-19 18:05:00.000000+00:00

Notes: one row per (organization, provider, mode). The credentials column is a
Fernet token bound to its organization and provider; the database stores
ciphertext only. `status` records what the last real check observed, never an
assumption.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7c1f0a9d2e34"
down_revision: str | None = "246fdeef0361"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "provider_credentials",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column(
            "mode",
            sa.String(length=20),
            server_default="api",
            nullable=False,
        ),
        sa.Column("encrypted_credentials", sa.LargeBinary(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="untested",
            nullable=False,
        ),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('untested', 'connected', 'error')",
            name="status_is_known",
        ),
        sa.CheckConstraint(
            "mode IN ('api', 'file_import')",
            name="mode_is_known",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "provider",
            "mode",
            name="uq_provider_credentials_connection",
        ),
    )


def downgrade() -> None:
    op.drop_table("provider_credentials")
