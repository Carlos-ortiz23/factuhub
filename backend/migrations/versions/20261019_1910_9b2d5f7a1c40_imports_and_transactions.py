"""bank accounts, imports and imported movements

Revision ID: 9b2d5f7a1c40
Revises: 7c1f0a9d2e34
Create Date: 2026-10-19 19:10:00.000000+00:00

Notes: the fingerprint is indexed but not unique. Two legitimate transactions can
share every visible field; a unique constraint would turn a duplicate *signal*
into silent data loss (spec §8.5). Idempotency lives on `import_jobs`, keyed by
the file hash plus the interpretation hash.

`bank_accounts.connection_id` is nullable: file-only companies must be able to
reconcile without a provider connection.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "9b2d5f7a1c40"
down_revision: str | None = "7c1f0a9d2e34"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bank_accounts",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=True),
        sa.Column("account_name", sa.String(length=120), nullable=False),
        sa.Column("bank_name", sa.String(length=120), nullable=False),
        sa.Column("account_number_masked", sa.String(length=32), nullable=True),
        sa.Column("currency", sa.String(length=3), server_default="COP", nullable=False),
        sa.Column("ledger_account_code", sa.String(length=32), nullable=True),
        sa.Column("external_account_id", sa.String(length=100), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "currency ~ '^[A-Z]{3}$'",
            name="ck_bank_accounts_currency_is_iso_shape",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"], ["provider_credentials.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "import_jobs",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("bank_account_id", sa.Uuid(), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("file_sha256", sa.String(length=64), nullable=False),
        sa.Column("request_sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("rows_read", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("rows_imported", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("error_summary", sa.String(length=1000), nullable=True),
        sa.Column(
            "mapping_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "options_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source_type IN ('bank_statement', 'ledger_export', 'api_sync')",
            name="ck_import_jobs_source_is_known",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed')",
            name="ck_import_jobs_status_is_known",
        ),
        sa.CheckConstraint("rows_read >= 0", name="ck_import_jobs_rows_read_is_not_negative"),
        sa.CheckConstraint(
            "rows_imported >= 0", name="ck_import_jobs_rows_imported_is_not_negative"
        ),
        sa.ForeignKeyConstraint(["bank_account_id"], ["bank_accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "bank_account_id",
            "source_type",
            "file_sha256",
            "request_sha256",
            name="uq_import_jobs_request",
        ),
    )
    op.create_index(
        "ix_import_jobs_organization_id_created_at",
        "import_jobs",
        ["organization_id", sa.text("created_at DESC")],
    )
    op.create_index("ix_import_jobs_bank_account_id", "import_jobs", ["bank_account_id"])

    op.create_table(
        "import_row_errors",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("import_job_id", sa.Uuid(), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("field", sa.String(length=50), nullable=True),
        sa.Column("message", sa.String(length=300), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["import_job_id"], ["import_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_import_row_errors_job_row",
        "import_row_errors",
        ["import_job_id", "row_number"],
    )

    op.create_table(
        "bank_transactions",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("bank_account_id", sa.Uuid(), nullable=False),
        sa.Column("import_job_id", sa.Uuid(), nullable=False),
        sa.Column("transaction_date", sa.Date(), nullable=False),
        sa.Column("value_date", sa.Date(), nullable=True),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("direction", sa.String(length=10), nullable=False),
        sa.Column("reference", sa.String(length=100), nullable=True),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("external_id", sa.String(length=100), nullable=True),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("amount_minor > 0", name="ck_bank_transactions_amount_is_positive"),
        sa.CheckConstraint(
            "direction IN ('debit', 'credit')",
            name="ck_bank_transactions_direction_is_known",
        ),
        sa.ForeignKeyConstraint(["bank_account_id"], ["bank_accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["import_job_id"], ["import_jobs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_bank_transactions_account_date",
        "bank_transactions",
        ["organization_id", "bank_account_id", "transaction_date"],
    )
    op.create_index(
        "ix_bank_transactions_organization_fingerprint",
        "bank_transactions",
        ["organization_id", "fingerprint"],
    )
    op.create_index("ix_bank_transactions_import_job_id", "bank_transactions", ["import_job_id"])

    op.create_table(
        "ledger_transactions",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("bank_account_id", sa.Uuid(), nullable=False),
        sa.Column("import_job_id", sa.Uuid(), nullable=False),
        sa.Column("source_system", sa.String(length=50), nullable=False),
        sa.Column("external_id", sa.String(length=100), nullable=True),
        sa.Column("transaction_date", sa.Date(), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("direction", sa.String(length=10), nullable=False),
        sa.Column("reference", sa.String(length=100), nullable=True),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("amount_minor > 0", name="ck_ledger_transactions_amount_is_positive"),
        sa.CheckConstraint(
            "direction IN ('debit', 'credit')",
            name="ck_ledger_transactions_direction_is_known",
        ),
        sa.ForeignKeyConstraint(["bank_account_id"], ["bank_accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["import_job_id"], ["import_jobs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ledger_transactions_account_date",
        "ledger_transactions",
        ["organization_id", "bank_account_id", "transaction_date"],
    )
    op.create_index(
        "ix_ledger_transactions_organization_fingerprint",
        "ledger_transactions",
        ["organization_id", "fingerprint"],
    )
    op.create_index(
        "ix_ledger_transactions_import_job_id", "ledger_transactions", ["import_job_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_ledger_transactions_import_job_id", table_name="ledger_transactions")
    op.drop_index(
        "ix_ledger_transactions_organization_fingerprint",
        table_name="ledger_transactions",
    )
    op.drop_index("ix_ledger_transactions_account_date", table_name="ledger_transactions")
    op.drop_table("ledger_transactions")
    op.drop_index("ix_bank_transactions_import_job_id", table_name="bank_transactions")
    op.drop_index("ix_bank_transactions_organization_fingerprint", table_name="bank_transactions")
    op.drop_index("ix_bank_transactions_account_date", table_name="bank_transactions")
    op.drop_table("bank_transactions")
    op.drop_index("ix_import_row_errors_job_row", table_name="import_row_errors")
    op.drop_table("import_row_errors")
    op.drop_index("ix_import_jobs_bank_account_id", table_name="import_jobs")
    op.drop_index("ix_import_jobs_organization_id_created_at", table_name="import_jobs")
    op.drop_table("import_jobs")
    op.drop_table("bank_accounts")
