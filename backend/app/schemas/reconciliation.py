"""Transport contracts for periods, their movements, and matches."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models import (
    MatchStatus,
    MatchType,
    PeriodStatus,
    PeriodTransactionType,
    TransactionDirection,
)

LIMIT_MINOR = 10**18


class PeriodCreateRequest(BaseModel):
    period_start: date
    period_end: date
    opening_balance_minor: int = Field(ge=-LIMIT_MINOR, le=LIMIT_MINOR)
    bank_closing_balance_minor: int = Field(ge=-LIMIT_MINOR, le=LIMIT_MINOR)
    ledger_closing_balance_minor: int = Field(ge=-LIMIT_MINOR, le=LIMIT_MINOR)


class PeriodResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    bank_account_id: UUID
    period_start: date
    period_end: date
    opening_balance_minor: int
    bank_closing_balance_minor: int
    ledger_closing_balance_minor: int
    status: PeriodStatus
    created_by: UUID
    approved_by: UUID | None
    approved_at: datetime | None
    created_at: datetime


class BalancesResponse(BaseModel):
    opening_balance_minor: int
    bank_inflow_minor: int
    bank_outflow_minor: int
    bank_computed_closing_minor: int
    statement_closing_balance_minor: int
    statement_difference_minor: int
    ledger_closing_balance_minor: int
    matched_bank_count: int
    matched_ledger_count: int
    matched_bank_minor: int
    pending_bank_count: int
    pending_ledger_count: int
    pending_bank_net_minor: int
    pending_ledger_net_minor: int
    adjusted_ledger_balance_minor: int
    unexplained_difference_minor: int
    progress_ratio: float
    balanced: bool
    convention: str


class PeriodSummaryResponse(BaseModel):
    period_id: UUID
    status: PeriodStatus
    bank_transaction_count: int
    ledger_transaction_count: int
    balances: BalancesResponse


class PeriodTransactionResponse(BaseModel):
    side: PeriodTransactionType
    id: UUID
    transaction_date: date
    amount_minor: int
    direction: TransactionDirection
    reference: str | None
    description: str | None
    external_id: str | None
    match_id: UUID | None
    match_status: MatchStatus | None


class PeriodTransactionListResponse(BaseModel):
    transactions: list[PeriodTransactionResponse]
    total: int
    limit: int
    offset: int


class MatchItemResponse(BaseModel):
    id: UUID
    bank_transaction_id: UUID | None
    ledger_transaction_id: UUID | None


class MatchResponse(BaseModel):
    id: UUID
    organization_id: UUID
    period_id: UUID
    match_type: MatchType
    score: float
    status: MatchStatus
    reviewed_by: UUID | None
    reviewed_at: datetime | None
    explanation: dict[str, Any]
    created_at: datetime
    items: list[MatchItemResponse]


class MatchListResponse(BaseModel):
    matches: list[MatchResponse]


class SuggestionRunResponse(BaseModel):
    created: int
    truncated: bool
    matches: list[MatchResponse]
