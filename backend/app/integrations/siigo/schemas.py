"""The shapes Siigo actually returns, validated before anything else uses them.

These models are a contract with an external service, so they are deliberately
lenient about *extra* fields (Siigo adds them without warning) and strict about
the fields the adapter maps. A missing field is a hard failure: guessing a
movement's direction would silently corrupt a reconciliation.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class _SiigoModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class SiigoTokenResponse(_SiigoModel):
    access_token: str = Field(repr=False)
    expires_in: float
    token_type: str = "Bearer"


class SiigoAccount(_SiigoModel):
    code: str
    movement: str


class SiigoJournalItem(_SiigoModel):
    account: SiigoAccount
    description: str | None = None
    value: Decimal


class SiigoJournal(_SiigoModel):
    id: str
    name: str | None = None
    date: date
    items: list[SiigoJournalItem]


class SiigoPagination(_SiigoModel):
    page: int
    page_size: int
    total_results: int


class SiigoJournalPage(_SiigoModel):
    pagination: SiigoPagination
    results: list[SiigoJournal]
