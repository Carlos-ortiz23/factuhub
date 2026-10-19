"""Periods, match suggestions, and the human decisions on them.

A suggestion is cheap and disposable; a confirmation is a financial decision.
That asymmetry drives the design: generating suggestions replaces the previous
suggested set, while confirming locks the movements, checks that nobody else
confirmed them, and cancels the alternatives that shared them.

Approval is deliberately strict. The specification forbids approving a period
with unjustified differences, and this phase has no justification model yet, so
approval requires every bank and ledger movement to be matched and both the
statement difference and the unexplained difference to be zero. That is stricter
than the specification's minimum; it never approves something it cannot explain.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from app.models import (
    BankAccount,
    BankTransaction,
    LedgerTransaction,
    MatchStatus,
    MatchType,
    PeriodStatus,
    PeriodTransactionType,
    ReconciliationMatch,
    ReconciliationMatchItem,
    ReconciliationPeriod,
    ReconciliationPeriodTransaction,
    TransactionDirection,
)
from app.reconciliation.balances import PeriodBalances, compute_period_balances
from app.reconciliation.grouping import find_groups
from app.reconciliation.matcher import exact_candidates, suggest_candidates
from app.reconciliation.types import Movement, MovementSide
from app.services import audit

MAX_SUGGESTIONS_PER_RUN = 500
MAX_PERIOD_DAYS = 366 * 5


class ReconciliationServiceError(ValueError):
    """A request the service refuses, translated to HTTP by the route."""


class PeriodNotFoundError(ReconciliationServiceError):
    pass


class MatchNotFoundError(ReconciliationServiceError):
    pass


class PeriodConflictError(ReconciliationServiceError):
    pass


class MatchNotActionableError(ReconciliationServiceError):
    pass


class MovementUnavailableError(ReconciliationServiceError):
    pass


@dataclass(frozen=True, slots=True)
class PeriodMovementView:
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


def create_period(
    db: Session,
    *,
    organization_id: UUID,
    actor_id: UUID,
    bank_account_id: UUID,
    period_start: date,
    period_end: date,
    opening_balance_minor: int,
    bank_closing_balance_minor: int,
    ledger_closing_balance_minor: int,
) -> ReconciliationPeriod:
    account = db.get(BankAccount, bank_account_id)
    if account is None or account.organization_id != organization_id:
        raise PeriodNotFoundError("Bank account not found.")
    if period_start > period_end:
        raise ReconciliationServiceError("period_start must not be after period_end.")
    if (period_end - period_start).days > MAX_PERIOD_DAYS:
        raise ReconciliationServiceError("The period is longer than five years.")

    overlap = db.scalar(
        select(ReconciliationPeriod).where(
            ReconciliationPeriod.organization_id == organization_id,
            ReconciliationPeriod.bank_account_id == bank_account_id,
            ReconciliationPeriod.period_start <= period_end,
            ReconciliationPeriod.period_end >= period_start,
        )
    )
    if overlap is not None:
        raise PeriodConflictError("Another period for this account overlaps the requested window.")

    period = ReconciliationPeriod(
        organization_id=organization_id,
        bank_account_id=bank_account_id,
        period_start=period_start,
        period_end=period_end,
        opening_balance_minor=opening_balance_minor,
        bank_closing_balance_minor=bank_closing_balance_minor,
        ledger_closing_balance_minor=ledger_closing_balance_minor,
        status=PeriodStatus.OPEN,
        created_by=actor_id,
    )
    db.add(period)
    db.flush()

    _sync_period_transactions(db, period)
    audit.record(
        db,
        organization_id=organization_id,
        user_id=actor_id,
        action="reconciliation_period.created",
        entity_type="reconciliation_period",
        entity_id=period.id,
        metadata={
            "bank_account_id": str(bank_account_id),
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
        },
    )
    db.flush()
    return period


def get_period(
    db: Session, *, organization_id: UUID, period_id: UUID
) -> ReconciliationPeriod | None:
    period = db.get(ReconciliationPeriod, period_id)
    if period is None or period.organization_id != organization_id:
        return None
    return period


def get_match(db: Session, *, organization_id: UUID, match_id: UUID) -> ReconciliationMatch | None:
    match = db.get(ReconciliationMatch, match_id)
    if match is None or match.organization_id != organization_id:
        return None
    return match


def period_movements(
    db: Session,
    *,
    organization_id: UUID,
    period: ReconciliationPeriod,
    limit: int,
    offset: int,
) -> tuple[list[PeriodMovementView], int]:
    banks, ledgers = _movements_in_period(db, organization_id=organization_id, period=period)
    match_map = _match_map(db, period.id)

    views: list[PeriodMovementView] = []
    for row in banks:
        match = match_map.get(("bank", row.id))
        views.append(
            PeriodMovementView(
                side=PeriodTransactionType.BANK,
                id=row.id,
                transaction_date=row.transaction_date,
                amount_minor=row.amount_minor,
                direction=row.direction,
                reference=row.reference,
                description=row.description,
                external_id=row.external_id,
                match_id=match[0] if match else None,
                match_status=match[1] if match else None,
            )
        )
    for row in ledgers:
        match = match_map.get(("ledger", row.id))
        views.append(
            PeriodMovementView(
                side=PeriodTransactionType.LEDGER,
                id=row.id,
                transaction_date=row.transaction_date,
                amount_minor=row.amount_minor,
                direction=row.direction,
                reference=row.reference,
                description=row.description,
                external_id=row.external_id,
                match_id=match[0] if match else None,
                match_status=match[1] if match else None,
            )
        )

    views.sort(key=lambda view: (view.transaction_date, view.side.value, str(view.id)))
    total = len(views)
    return views[offset : offset + limit], total


def period_counts(
    db: Session, *, organization_id: UUID, period: ReconciliationPeriod
) -> tuple[int, int]:
    banks, ledgers = _movements_in_period(db, organization_id=organization_id, period=period)
    return len(banks), len(ledgers)


def period_summary(
    db: Session, *, organization_id: UUID, period: ReconciliationPeriod
) -> PeriodBalances:
    banks, ledgers = _movements_in_period(db, organization_id=organization_id, period=period)
    confirmed_bank, confirmed_ledger = _confirmed_ids(db, period.id)
    return compute_period_balances(
        [_to_engine(row, MovementSide.BANK) for row in banks],
        [_to_engine(row, MovementSide.LEDGER) for row in ledgers],
        opening_balance_minor=period.opening_balance_minor,
        statement_closing_balance_minor=period.bank_closing_balance_minor,
        ledger_closing_balance_minor=period.ledger_closing_balance_minor,
        confirmed_bank_ids=confirmed_bank,
        confirmed_ledger_ids=confirmed_ledger,
    )


def generate_suggestions(
    db: Session,
    *,
    organization_id: UUID,
    actor_id: UUID,
    period: ReconciliationPeriod,
) -> tuple[list[ReconciliationMatch], bool]:
    """Replace the suggested set with a fresh calculation."""
    if period.status not in {PeriodStatus.OPEN, PeriodStatus.REOPENED}:
        raise PeriodConflictError(
            "Suggestions can only be regenerated while the period is open or reopened."
        )

    _sync_period_transactions(db, period)
    db.execute(
        delete(ReconciliationMatch).where(
            ReconciliationMatch.period_id == period.id,
            ReconciliationMatch.status == MatchStatus.SUGGESTED,
        )
    )

    banks, ledgers = _movements_in_period(db, organization_id=organization_id, period=period)
    confirmed_bank, confirmed_ledger = _confirmed_ids(db, period.id)
    rejected = _rejected_item_sets(db, period.id)

    available_banks = [
        _to_engine(row, MovementSide.BANK) for row in banks if row.id not in confirmed_bank
    ]
    available_ledgers = [
        _to_engine(row, MovementSide.LEDGER) for row in ledgers if row.id not in confirmed_ledger
    ]

    created: list[ReconciliationMatch] = []
    truncated = False

    for bank in available_banks:
        if len(created) >= MAX_SUGGESTIONS_PER_RUN:
            truncated = True
            break
        exact_ids = {candidate.ledger.id for candidate in exact_candidates(bank, available_ledgers)}
        for candidate in suggest_candidates(bank, available_ledgers):
            if len(created) >= MAX_SUGGESTIONS_PER_RUN:
                truncated = True
                break
            key = frozenset({("bank", bank.id), ("ledger", candidate.ledger.id)})
            if key in rejected:
                continue
            match_type = (
                MatchType.EXACT if candidate.ledger.id in exact_ids else MatchType.APPROXIMATE
            )
            match = _new_match(
                db,
                period=period,
                match_type=match_type,
                score=candidate.score,
                explanation={
                    "reasons": list(candidate.reasons),
                    "components": candidate.components,
                    "amount_difference_minor": candidate.amount_difference_minor,
                    "date_distance_days": candidate.date_distance_days,
                    "reference": candidate.ledger.reference,
                    "description": candidate.ledger.description,
                },
                bank_ids=[bank.id],
                ledger_ids=[candidate.ledger.id],
            )
            created.append(match)

    if not truncated:
        for group in find_groups(available_banks, available_ledgers):
            if len(created) >= MAX_SUGGESTIONS_PER_RUN:
                truncated = True
                break
            key = frozenset(
                [("bank", movement.id) for movement in group.bank_movements]
                + [("ledger", movement.id) for movement in group.ledger_movements]
            )
            if key in rejected:
                continue
            match = _new_match(
                db,
                period=period,
                match_type=MatchType.GROUPED,
                score=group.score,
                explanation={
                    "reasons": list(group.reasons),
                    "total_minor": group.total_minor,
                    "date_span_days": group.date_span_days,
                },
                bank_ids=[movement.id for movement in group.bank_movements],
                ledger_ids=[movement.id for movement in group.ledger_movements],
            )
            created.append(match)

    db.flush()
    audit.record(
        db,
        organization_id=organization_id,
        user_id=actor_id,
        action="reconciliation.suggestions_generated",
        entity_type="reconciliation_period",
        entity_id=period.id,
        metadata={
            "suggestions": len(created),
            "truncated": truncated,
            "available_bank": len(available_banks),
            "available_ledger": len(available_ledgers),
        },
    )
    db.flush()
    return created, truncated


def list_matches(
    db: Session,
    *,
    period: ReconciliationPeriod,
    status: MatchStatus | None = None,
) -> list[ReconciliationMatch]:
    statement = select(ReconciliationMatch).where(ReconciliationMatch.period_id == period.id)
    if status is not None:
        statement = statement.where(ReconciliationMatch.status == status)
    return list(
        db.scalars(
            statement.order_by(ReconciliationMatch.score.desc(), ReconciliationMatch.created_at)
        )
    )


def match_items(db: Session, *, match_ids: list[UUID]) -> dict[UUID, list[ReconciliationMatchItem]]:
    if not match_ids:
        return {}
    items: dict[UUID, list[ReconciliationMatchItem]] = {match_id: [] for match_id in match_ids}
    for item in db.scalars(
        select(ReconciliationMatchItem).where(ReconciliationMatchItem.match_id.in_(match_ids))
    ):
        items[item.match_id].append(item)
    return items


def confirm_match(
    db: Session,
    *,
    organization_id: UUID,
    actor_id: UUID,
    match_id: UUID,
) -> ReconciliationMatch:
    match = db.get(ReconciliationMatch, match_id, with_for_update=True)
    if match is None or match.organization_id != organization_id:
        raise MatchNotFoundError("Match not found.")
    if match.status is not MatchStatus.SUGGESTED:
        raise MatchNotActionableError("Only a suggested match can be confirmed.")

    period = db.get(ReconciliationPeriod, match.period_id, with_for_update=True)
    if period is None:
        raise PeriodNotFoundError("Period not found.")
    if period.status not in {
        PeriodStatus.OPEN,
        PeriodStatus.REOPENED,
        PeriodStatus.IN_REVIEW,
    }:
        raise PeriodConflictError("The period is approved; reopen it to change matches.")

    items = list(
        db.scalars(
            select(ReconciliationMatchItem).where(ReconciliationMatchItem.match_id == match.id)
        )
    )
    bank_ids = [item.bank_transaction_id for item in items if item.bank_transaction_id]
    ledger_ids = [item.ledger_transaction_id for item in items if item.ledger_transaction_id]
    if not items:
        raise MatchNotActionableError("The match has no movements.")

    _lock_movements(db, bank_ids=bank_ids, ledger_ids=ledger_ids)
    _require_movements_belong(
        db,
        period=period,
        bank_ids=bank_ids,
        ledger_ids=ledger_ids,
    )

    shared = _other_confirmed_item_match_ids(
        db, period_id=period.id, match_id=match.id, bank_ids=bank_ids, ledger_ids=ledger_ids
    )
    if shared:
        raise MovementUnavailableError(
            "At least one movement in this match is already confirmed in another match."
        )

    match.status = MatchStatus.CONFIRMED
    match.reviewed_by = actor_id
    match.reviewed_at = datetime.now(UTC)

    competing = _suggested_matches_sharing(
        db, period_id=period.id, match_id=match.id, bank_ids=bank_ids, ledger_ids=ledger_ids
    )
    for other in competing:
        other.status = MatchStatus.CANCELLED
        other.reviewed_by = actor_id
        other.reviewed_at = datetime.now(UTC)
        other.explanation_json = {
            **other.explanation_json,
            "cancelled_reason": "another match sharing these movements was confirmed",
        }

    audit.record(
        db,
        organization_id=organization_id,
        user_id=actor_id,
        action="reconciliation.match_confirmed",
        entity_type="reconciliation_match",
        entity_id=match.id,
        metadata={
            "period_id": str(period.id),
            "match_type": match.match_type.value,
            "cancelled_alternatives": len(competing),
        },
    )
    db.flush()
    return match


def reject_match(
    db: Session, *, organization_id: UUID, actor_id: UUID, match_id: UUID
) -> ReconciliationMatch:
    return _decide(
        db,
        organization_id=organization_id,
        actor_id=actor_id,
        match_id=match_id,
        status=MatchStatus.REJECTED,
        action="reconciliation.match_rejected",
    )


def cancel_match(
    db: Session, *, organization_id: UUID, actor_id: UUID, match_id: UUID
) -> ReconciliationMatch:
    return _decide(
        db,
        organization_id=organization_id,
        actor_id=actor_id,
        match_id=match_id,
        status=MatchStatus.CANCELLED,
        action="reconciliation.match_cancelled",
    )


def submit_review(
    db: Session, *, organization_id: UUID, actor_id: UUID, period: ReconciliationPeriod
) -> ReconciliationPeriod:
    locked = _lock_period(db, organization_id=organization_id, period_id=period.id)
    if locked.status not in {PeriodStatus.OPEN, PeriodStatus.REOPENED}:
        raise PeriodConflictError("Only an open or reopened period can be submitted for review.")
    locked.status = PeriodStatus.IN_REVIEW
    audit.record(
        db,
        organization_id=organization_id,
        user_id=actor_id,
        action="reconciliation_period.submitted_for_review",
        entity_type="reconciliation_period",
        entity_id=locked.id,
        metadata={},
    )
    db.flush()
    return locked


def approve_period(
    db: Session, *, organization_id: UUID, actor_id: UUID, period: ReconciliationPeriod
) -> ReconciliationPeriod:
    locked = _lock_period(db, organization_id=organization_id, period_id=period.id)
    if locked.status is not PeriodStatus.IN_REVIEW:
        raise PeriodConflictError("Only a period under review can be approved.")

    balances = period_summary(db, organization_id=organization_id, period=locked)
    if not balances.balanced:
        raise PeriodConflictError(
            "The period cannot be approved: "
            f"{balances.pending_bank_count} bank and {balances.pending_ledger_count} ledger "
            f"movements are pending, statement difference "
            f"{balances.statement_difference_minor}, unexplained difference "
            f"{balances.unexplained_difference_minor} (minor units)."
        )

    locked.status = PeriodStatus.APPROVED
    locked.approved_by = actor_id
    locked.approved_at = datetime.now(UTC)
    audit.record(
        db,
        organization_id=organization_id,
        user_id=actor_id,
        action="reconciliation_period.approved",
        entity_type="reconciliation_period",
        entity_id=locked.id,
        metadata={"matched_bank": balances.matched_bank_count},
    )
    db.flush()
    return locked


def reopen_period(
    db: Session, *, organization_id: UUID, actor_id: UUID, period: ReconciliationPeriod
) -> ReconciliationPeriod:
    locked = _lock_period(db, organization_id=organization_id, period_id=period.id)
    if locked.status is not PeriodStatus.APPROVED:
        raise PeriodConflictError("Only an approved period can be reopened.")
    locked.status = PeriodStatus.REOPENED
    locked.approved_by = None
    locked.approved_at = None
    audit.record(
        db,
        organization_id=organization_id,
        user_id=actor_id,
        action="reconciliation_period.reopened",
        entity_type="reconciliation_period",
        entity_id=locked.id,
        metadata={},
    )
    db.flush()
    return locked


def _lock_period(db: Session, *, organization_id: UUID, period_id: UUID) -> ReconciliationPeriod:
    period = db.get(ReconciliationPeriod, period_id, with_for_update=True)
    if period is None or period.organization_id != organization_id:
        raise PeriodNotFoundError("Period not found.")
    return period


def _decide(
    db: Session,
    *,
    organization_id: UUID,
    actor_id: UUID,
    match_id: UUID,
    status: MatchStatus,
    action: str,
) -> ReconciliationMatch:
    match = db.get(ReconciliationMatch, match_id, with_for_update=True)
    if match is None or match.organization_id != organization_id:
        raise MatchNotFoundError("Match not found.")
    if match.status is not MatchStatus.SUGGESTED:
        raise MatchNotActionableError("Only a suggested match can be decided.")
    match.status = status
    match.reviewed_by = actor_id
    match.reviewed_at = datetime.now(UTC)
    audit.record(
        db,
        organization_id=organization_id,
        user_id=actor_id,
        action=action,
        entity_type="reconciliation_match",
        entity_id=match.id,
        metadata={"period_id": str(match.period_id)},
    )
    db.flush()
    return match


def _movements_in_period(
    db: Session, *, organization_id: UUID, period: ReconciliationPeriod
) -> tuple[list[BankTransaction], list[LedgerTransaction]]:
    banks = list(
        db.scalars(
            select(BankTransaction)
            .where(
                BankTransaction.organization_id == organization_id,
                BankTransaction.bank_account_id == period.bank_account_id,
                BankTransaction.transaction_date >= period.period_start,
                BankTransaction.transaction_date <= period.period_end,
            )
            .order_by(BankTransaction.transaction_date, BankTransaction.id)
        )
    )
    ledgers = list(
        db.scalars(
            select(LedgerTransaction)
            .where(
                LedgerTransaction.organization_id == organization_id,
                LedgerTransaction.bank_account_id == period.bank_account_id,
                LedgerTransaction.transaction_date >= period.period_start,
                LedgerTransaction.transaction_date <= period.period_end,
            )
            .order_by(LedgerTransaction.transaction_date, LedgerTransaction.id)
        )
    )
    return banks, ledgers


def _sync_period_transactions(db: Session, period: ReconciliationPeriod) -> None:
    banks, ledgers = _movements_in_period(db, organization_id=period.organization_id, period=period)
    existing = {
        (row.transaction_type, row.transaction_id)
        for row in db.scalars(
            select(ReconciliationPeriodTransaction).where(
                ReconciliationPeriodTransaction.period_id == period.id
            )
        )
    }
    for row in banks:
        key = (PeriodTransactionType.BANK, row.id)
        if key not in existing:
            db.add(
                ReconciliationPeriodTransaction(
                    organization_id=period.organization_id,
                    period_id=period.id,
                    transaction_type=PeriodTransactionType.BANK,
                    transaction_id=row.id,
                )
            )
    for row in ledgers:
        key = (PeriodTransactionType.LEDGER, row.id)
        if key not in existing:
            db.add(
                ReconciliationPeriodTransaction(
                    organization_id=period.organization_id,
                    period_id=period.id,
                    transaction_type=PeriodTransactionType.LEDGER,
                    transaction_id=row.id,
                )
            )
    db.flush()


def _match_map(db: Session, period_id: UUID) -> dict[tuple[str, UUID], tuple[UUID, MatchStatus]]:
    rows = db.execute(
        select(ReconciliationMatchItem, ReconciliationMatch)
        .join(
            ReconciliationMatch,
            ReconciliationMatch.id == ReconciliationMatchItem.match_id,
        )
        .where(
            ReconciliationMatch.period_id == period_id,
            ReconciliationMatch.status.in_([MatchStatus.SUGGESTED, MatchStatus.CONFIRMED]),
        )
    ).all()
    result: dict[tuple[str, UUID], tuple[UUID, MatchStatus]] = {}
    for item, match in rows:
        if item.bank_transaction_id is not None:
            result[("bank", item.bank_transaction_id)] = (match.id, match.status)
        if item.ledger_transaction_id is not None:
            result[("ledger", item.ledger_transaction_id)] = (match.id, match.status)
    return result


def _confirmed_ids(db: Session, period_id: UUID) -> tuple[set[UUID], set[UUID]]:
    rows = db.execute(
        select(
            ReconciliationMatchItem.bank_transaction_id,
            ReconciliationMatchItem.ledger_transaction_id,
        )
        .join(
            ReconciliationMatch,
            ReconciliationMatch.id == ReconciliationMatchItem.match_id,
        )
        .where(
            ReconciliationMatch.period_id == period_id,
            ReconciliationMatch.status == MatchStatus.CONFIRMED,
        )
    ).all()
    banks = {row[0] for row in rows if row[0] is not None}
    ledgers = {row[1] for row in rows if row[1] is not None}
    return banks, ledgers


def _rejected_item_sets(db: Session, period_id: UUID) -> set[frozenset[tuple[str, UUID]]]:
    rows = db.execute(
        select(ReconciliationMatchItem, ReconciliationMatch)
        .join(
            ReconciliationMatch,
            ReconciliationMatch.id == ReconciliationMatchItem.match_id,
        )
        .where(
            ReconciliationMatch.period_id == period_id,
            ReconciliationMatch.status.in_([MatchStatus.REJECTED, MatchStatus.CANCELLED]),
        )
    ).all()
    grouped: dict[UUID, list[tuple[str, UUID]]] = {}
    for item, match in rows:
        members = grouped.setdefault(match.id, [])
        if item.bank_transaction_id is not None:
            members.append(("bank", item.bank_transaction_id))
        if item.ledger_transaction_id is not None:
            members.append(("ledger", item.ledger_transaction_id))
    return {frozenset(members) for members in grouped.values() if members}


def _new_match(
    db: Session,
    *,
    period: ReconciliationPeriod,
    match_type: MatchType,
    score: float,
    explanation: dict,
    bank_ids: list[UUID],
    ledger_ids: list[UUID],
) -> ReconciliationMatch:
    match = ReconciliationMatch(
        organization_id=period.organization_id,
        period_id=period.id,
        match_type=match_type,
        score=Decimal(str(round(score, 4))),
        status=MatchStatus.SUGGESTED,
        explanation_json=explanation,
    )
    db.add(match)
    db.flush()
    for bank_id in bank_ids:
        db.add(ReconciliationMatchItem(match_id=match.id, bank_transaction_id=bank_id))
    for ledger_id in ledger_ids:
        db.add(ReconciliationMatchItem(match_id=match.id, ledger_transaction_id=ledger_id))
    db.flush()
    return match


def _lock_movements(db: Session, *, bank_ids: list[UUID], ledger_ids: list[UUID]) -> None:
    if bank_ids:
        db.scalars(
            select(BankTransaction)
            .where(BankTransaction.id.in_(bank_ids))
            .order_by(BankTransaction.id)
            .with_for_update()
        ).all()
    if ledger_ids:
        db.scalars(
            select(LedgerTransaction)
            .where(LedgerTransaction.id.in_(ledger_ids))
            .order_by(LedgerTransaction.id)
            .with_for_update()
        ).all()


def _require_movements_belong(
    db: Session,
    *,
    period: ReconciliationPeriod,
    bank_ids: list[UUID],
    ledger_ids: list[UUID],
) -> None:
    for row in db.scalars(select(BankTransaction).where(BankTransaction.id.in_(bank_ids))):
        if (
            row.organization_id != period.organization_id
            or row.bank_account_id != period.bank_account_id
            or not period.period_start <= row.transaction_date <= period.period_end
        ):
            raise MovementUnavailableError("A bank movement does not belong to this period.")
    for row in db.scalars(select(LedgerTransaction).where(LedgerTransaction.id.in_(ledger_ids))):
        if (
            row.organization_id != period.organization_id
            or row.bank_account_id != period.bank_account_id
            or not period.period_start <= row.transaction_date <= period.period_end
        ):
            raise MovementUnavailableError("A ledger movement does not belong to this period.")


def _other_confirmed_item_match_ids(
    db: Session,
    *,
    period_id: UUID,
    match_id: UUID,
    bank_ids: list[UUID],
    ledger_ids: list[UUID],
) -> list[UUID]:
    conditions = []
    if bank_ids:
        conditions.append(ReconciliationMatchItem.bank_transaction_id.in_(bank_ids))
    if ledger_ids:
        conditions.append(ReconciliationMatchItem.ledger_transaction_id.in_(ledger_ids))
    if not conditions:
        return []
    return list(
        db.scalars(
            select(ReconciliationMatchItem.match_id)
            .join(
                ReconciliationMatch,
                ReconciliationMatch.id == ReconciliationMatchItem.match_id,
            )
            .where(
                ReconciliationMatch.period_id == period_id,
                ReconciliationMatch.status == MatchStatus.CONFIRMED,
                ReconciliationMatch.id != match_id,
                or_(*conditions),
            )
        )
    )


def _suggested_matches_sharing(
    db: Session,
    *,
    period_id: UUID,
    match_id: UUID,
    bank_ids: list[UUID],
    ledger_ids: list[UUID],
) -> list[ReconciliationMatch]:
    conditions = []
    if bank_ids:
        conditions.append(ReconciliationMatchItem.bank_transaction_id.in_(bank_ids))
    if ledger_ids:
        conditions.append(ReconciliationMatchItem.ledger_transaction_id.in_(ledger_ids))
    if not conditions:
        return []
    shared_ids = select(ReconciliationMatchItem.match_id).where(or_(*conditions))
    return list(
        db.scalars(
            select(ReconciliationMatch)
            .where(
                ReconciliationMatch.period_id == period_id,
                ReconciliationMatch.id != match_id,
                ReconciliationMatch.status == MatchStatus.SUGGESTED,
                ReconciliationMatch.id.in_(shared_ids),
            )
            .with_for_update()
        )
    )


def _to_engine(row: BankTransaction | LedgerTransaction, side: MovementSide) -> Movement:
    return Movement(
        id=row.id,
        side=side,
        transaction_date=row.transaction_date,
        amount_minor=row.amount_minor,
        direction=row.direction,
        reference=row.reference,
        description=row.description,
        external_id=row.external_id,
        fingerprint=row.fingerprint,
        import_job_id=row.import_job_id,
    )
