"""The values the reconciliation engine works with.

The engine is pure: it receives movements, returns suggestions, and knows nothing
about SQLAlchemy. Persistence can therefore change without re-testing the
financial rules, and every rule is testable without a database transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from uuid import UUID

from app.models import TransactionDirection

#: Largest amount, in minor units, that an approximate match may differ by
#: before it stops being a candidate. 5,000 COP: bank fees and rounding, not a
#: different payment. Configurable and to be calibrated with real data (§8.3).
DEFAULT_AMOUNT_TOLERANCE_MINOR = 500_000

#: Bank movements and ledger postings of the same event rarely share a date.
DEFAULT_DATE_WINDOW_DAYS = 3


class MovementSide(StrEnum):
    BANK = "bank"
    LEDGER = "ledger"


class EconomicDirection(StrEnum):
    """Money entering or leaving the bank account, whatever the source calls it."""

    INFLOW = "inflow"
    OUTFLOW = "outflow"


class MatchBand(StrEnum):
    HIGH = "high"
    SUGGESTION = "suggestion"
    LOW = "low"


@dataclass(frozen=True, slots=True)
class Movement:
    """One movement as the engine sees it, detached from its ORM row."""

    id: UUID
    side: MovementSide
    transaction_date: date
    amount_minor: int
    direction: TransactionDirection
    reference: str | None = None
    description: str | None = None
    external_id: str | None = None
    fingerprint: str | None = None
    import_job_id: UUID | None = None

    def __post_init__(self) -> None:
        if self.amount_minor <= 0:
            raise ValueError("amount_minor must be positive; direction carries the sign")


@dataclass(frozen=True, slots=True)
class MatchConfig:
    """Weights, tolerances and bands. Every default is an assumption to calibrate."""

    amount_weight: float = 0.40
    date_weight: float = 0.25
    reference_weight: float = 0.25
    description_weight: float = 0.10
    date_window_days: int = DEFAULT_DATE_WINDOW_DAYS
    amount_tolerance_minor: int = DEFAULT_AMOUNT_TOLERANCE_MINOR
    high_confidence_threshold: float = 0.95
    suggestion_threshold: float = 0.80

    def __post_init__(self) -> None:
        weights = (
            self.amount_weight,
            self.date_weight,
            self.reference_weight,
            self.description_weight,
        )
        if any(weight < 0 for weight in weights):
            raise ValueError("weights must not be negative")
        if abs(sum(weights) - 1.0) > 1e-9:
            raise ValueError("weights must sum to 1.0")
        if self.date_window_days < 0:
            raise ValueError("date_window_days must not be negative")
        if self.amount_tolerance_minor < 0:
            raise ValueError("amount_tolerance_minor must not be negative")
        if not 0.0 <= self.suggestion_threshold <= self.high_confidence_threshold <= 1.0:
            raise ValueError("thresholds must be ordered inside [0, 1]")

    def weight_of(self, component: str) -> float:
        return {
            "amount": self.amount_weight,
            "date": self.date_weight,
            "reference": self.reference_weight,
            "description": self.description_weight,
        }[component]


DEFAULT_CONFIG = MatchConfig()
