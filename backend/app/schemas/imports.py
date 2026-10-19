"""Transport contracts for bank accounts and imports."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models import ImportSourceType, ImportStatus


class BankAccountCreateRequest(BaseModel):
    """Register an account. Only a masked number is accepted."""

    account_name: str = Field(min_length=1, max_length=120)
    bank_name: str = Field(min_length=1, max_length=120)
    account_number_masked: str | None = Field(default=None, max_length=32)
    currency: str = Field(default="COP", min_length=3, max_length=3)
    ledger_account_code: str | None = Field(default=None, max_length=32)
    external_account_id: str | None = Field(default=None, max_length=100)
    connection_id: UUID | None = None


class BankAccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    connection_id: UUID | None
    account_name: str
    bank_name: str
    account_number_masked: str | None
    currency: str
    ledger_account_code: str | None
    external_account_id: str | None
    active: bool
    created_at: datetime


class BankAccountListResponse(BaseModel):
    accounts: list[BankAccountResponse]


class ImportResponse(BaseModel):
    """The job as the interface shows it.

    `mapping` and `options` are echoed back because they explain how the numbers
    were read; without them a user cannot tell why `1.234` became 1234.
    """

    id: UUID
    organization_id: UUID
    bank_account_id: UUID
    source_type: ImportSourceType
    file_name: str
    status: ImportStatus
    rows_read: int
    rows_imported: int
    error_summary: str | None
    mapping: dict[str, Any]
    options: dict[str, Any]
    created_at: datetime
    completed_at: datetime | None


class ImportListResponse(BaseModel):
    imports: list[ImportResponse]
    total: int
    limit: int
    offset: int


class ImportRowErrorResponse(BaseModel):
    row_number: int
    field: str | None
    message: str


class ImportRowErrorListResponse(BaseModel):
    errors: list[ImportRowErrorResponse]
    total: int
    limit: int
    offset: int
