"""Periods, their movements, suggestions, and match decisions.

The routes carry no financial logic: they translate the service's domain errors
to HTTP and build responses before committing, so a serialization failure cannot
leave a committed decision with no response.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import (
    OrganizationContext,
    get_db_session,
    require_csrf,
)
from app.api.scoping import (
    require_bank_account_permission,
    require_match_permission,
    require_period_permission,
)
from app.core.permissions import Permission
from app.models import (
    BankAccount,
    MatchStatus,
    Organization,
    ReconciliationMatch,
    ReconciliationMatchItem,
)
from app.reports.period_export import ReportHeader, build_period_workbook
from app.schemas.reconciliation import (
    BalancesResponse,
    MatchItemResponse,
    MatchListResponse,
    MatchResponse,
    PeriodCreateRequest,
    PeriodResponse,
    PeriodSummaryResponse,
    PeriodTransactionListResponse,
    PeriodTransactionResponse,
    SuggestionRunResponse,
)
from app.services import audit
from app.services import reconciliation as reconciliation_service

router = APIRouter(tags=["reconciliation"])


def _translate(exc: reconciliation_service.ReconciliationServiceError) -> HTTPException:
    if isinstance(
        exc,
        (
            reconciliation_service.PeriodNotFoundError,
            reconciliation_service.MatchNotFoundError,
        ),
    ):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(
        exc,
        (
            reconciliation_service.PeriodConflictError,
            reconciliation_service.MatchNotActionableError,
            reconciliation_service.MovementUnavailableError,
        ),
    ):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


def _as_match(match: ReconciliationMatch, items: list[ReconciliationMatchItem]) -> MatchResponse:
    return MatchResponse(
        id=match.id,
        organization_id=match.organization_id,
        period_id=match.period_id,
        match_type=match.match_type,
        score=float(match.score),
        status=match.status,
        reviewed_by=match.reviewed_by,
        reviewed_at=match.reviewed_at,
        released=match.released,
        explanation=match.explanation_json,
        created_at=match.created_at,
        items=[
            MatchItemResponse(
                id=item.id,
                bank_transaction_id=item.bank_transaction_id,
                ledger_transaction_id=item.ledger_transaction_id,
            )
            for item in items
        ],
    )


def _build_matches(db: Session, matches: list[ReconciliationMatch]) -> list[MatchResponse]:
    items = reconciliation_service.match_items(db, match_ids=[match.id for match in matches])
    return [_as_match(match, items.get(match.id, [])) for match in matches]


@router.post(
    "/bank-accounts/{account_id}/periods",
    response_model=PeriodResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Open a reconciliation period",
    description=(
        "Requires `reconcile`. The window must not overlap another period for the "
        "same account. Movements already imported are linked to the period."
    ),
    responses={409: {"description": "The window overlaps an existing period"}},
)
def create_period(
    account_id: UUID,
    payload: PeriodCreateRequest,
    context: Annotated[
        OrganizationContext, Depends(require_bank_account_permission(Permission.RECONCILE))
    ],
    db: Annotated[Session, Depends(get_db_session)],
    _csrf: Annotated[None, Depends(require_csrf)] = None,
) -> PeriodResponse:
    try:
        period = reconciliation_service.create_period(
            db,
            organization_id=context.organization_id,
            actor_id=context.user_id,
            bank_account_id=account_id,
            period_start=payload.period_start,
            period_end=payload.period_end,
            opening_balance_minor=payload.opening_balance_minor,
            bank_closing_balance_minor=payload.bank_closing_balance_minor,
            ledger_closing_balance_minor=payload.ledger_closing_balance_minor,
        )
    except reconciliation_service.ReconciliationServiceError as exc:
        raise _translate(exc) from exc

    response = PeriodResponse.model_validate(period)
    db.commit()
    return response


@router.get(
    "/periods/{period_id}",
    response_model=PeriodResponse,
    summary="One reconciliation period",
)
def get_period(
    period_id: UUID,
    context: Annotated[OrganizationContext, Depends(require_period_permission(Permission.READ))],
    db: Annotated[Session, Depends(get_db_session)],
) -> PeriodResponse:
    period = reconciliation_service.get_period(
        db, organization_id=context.organization_id, period_id=period_id
    )
    if period is None:  # pragma: no cover - the dependency already 404s
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Period not found.")
    return PeriodResponse.model_validate(period)


@router.get(
    "/periods/{period_id}/summary",
    response_model=PeriodSummaryResponse,
    summary="Balances, progress and differences",
)
def get_summary(
    period_id: UUID,
    context: Annotated[OrganizationContext, Depends(require_period_permission(Permission.READ))],
    db: Annotated[Session, Depends(get_db_session)],
) -> PeriodSummaryResponse:
    period = reconciliation_service.get_period(
        db, organization_id=context.organization_id, period_id=period_id
    )
    if period is None:  # pragma: no cover - the dependency already 404s
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Period not found.")

    balances = reconciliation_service.period_summary(
        db, organization_id=context.organization_id, period=period
    )
    bank_count, ledger_count = reconciliation_service.period_counts(
        db, organization_id=context.organization_id, period=period
    )
    return PeriodSummaryResponse(
        period_id=period.id,
        status=period.status,
        bank_transaction_count=bank_count,
        ledger_transaction_count=ledger_count,
        balances=BalancesResponse(**asdict(balances)),
    )


XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get(
    "/periods/{period_id}/export",
    summary="Download the period as an Excel workbook",
    description=(
        "Requires `read`. The workbook has four sheets: summary, movements, "
        "pending movements and matches. Every text cell is written as text, so "
        "a reference starting with `=` cannot become a formula."
    ),
    response_class=Response,
    responses={200: {"content": {XLSX_MEDIA_TYPE: {}}}},
)
def export_period(
    period_id: UUID,
    context: Annotated[OrganizationContext, Depends(require_period_permission(Permission.READ))],
    db: Annotated[Session, Depends(get_db_session)],
) -> Response:
    period = reconciliation_service.get_period(
        db, organization_id=context.organization_id, period_id=period_id
    )
    if period is None:  # pragma: no cover - the dependency already 404s
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Period not found.")

    account = db.get(BankAccount, period.bank_account_id)
    organization = db.get(Organization, period.organization_id)
    if account is None or organization is None:  # pragma: no cover - FK guarantees
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Period not found.")

    balances = reconciliation_service.period_summary(
        db, organization_id=context.organization_id, period=period
    )
    movements = reconciliation_service.all_period_movements(
        db, organization_id=context.organization_id, period=period
    )
    matches = reconciliation_service.list_matches(db, period=period)
    match_models = _build_matches(db, matches)

    content = build_period_workbook(
        period=PeriodResponse.model_validate(period),
        header=ReportHeader(
            organization_name=organization.name,
            organization_tax_id=organization.tax_id,
            bank_name=account.bank_name,
            account_masked=account.account_number_masked,
            currency=account.currency,
        ),
        balances=balances,
        movements=movements,
        matches=match_models,
    )
    audit.record(
        db,
        organization_id=context.organization_id,
        user_id=context.user_id,
        action="reconciliation_period.exported",
        entity_type="reconciliation_period",
        entity_id=period.id,
        metadata={"movements": len(movements), "matches": len(matches)},
    )
    db.commit()

    filename = (
        f"conciliacion-{period.period_start.isoformat()}-{period.period_end.isoformat()}.xlsx"
    )
    return Response(
        content=content,
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/periods/{period_id}/transactions",
    response_model=PeriodTransactionListResponse,
    summary="Bank and ledger movements inside the period",
)
def list_period_transactions(
    period_id: UUID,
    context: Annotated[OrganizationContext, Depends(require_period_permission(Permission.READ))],
    db: Annotated[Session, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PeriodTransactionListResponse:
    period = reconciliation_service.get_period(
        db, organization_id=context.organization_id, period_id=period_id
    )
    if period is None:  # pragma: no cover - the dependency already 404s
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Period not found.")

    views, total = reconciliation_service.period_movements(
        db,
        organization_id=context.organization_id,
        period=period,
        limit=limit,
        offset=offset,
    )
    return PeriodTransactionListResponse(
        transactions=[
            PeriodTransactionResponse(
                side=view.side,
                id=view.id,
                transaction_date=view.transaction_date,
                amount_minor=view.amount_minor,
                direction=view.direction,
                reference=view.reference,
                description=view.description,
                external_id=view.external_id,
                match_id=view.match_id,
                match_status=view.match_status,
            )
            for view in views
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/periods/{period_id}/match-suggestions",
    response_model=SuggestionRunResponse,
    summary="Recalculate suggestions",
    description=(
        "Requires `reconcile`. Replaces the previous suggested set. Confirmed "
        "matches and rejected decisions are kept; a rejected or cancelled "
        "combination is not offered again."
    ),
)
def generate_suggestions(
    period_id: UUID,
    context: Annotated[
        OrganizationContext, Depends(require_period_permission(Permission.RECONCILE))
    ],
    db: Annotated[Session, Depends(get_db_session)],
    _csrf: Annotated[None, Depends(require_csrf)] = None,
) -> SuggestionRunResponse:
    period = reconciliation_service.get_period(
        db, organization_id=context.organization_id, period_id=period_id
    )
    if period is None:  # pragma: no cover - the dependency already 404s
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Period not found.")

    try:
        created, truncated = reconciliation_service.generate_suggestions(
            db,
            organization_id=context.organization_id,
            actor_id=context.user_id,
            period=period,
        )
    except reconciliation_service.ReconciliationServiceError as exc:
        raise _translate(exc) from exc

    response = SuggestionRunResponse(
        created=len(created), truncated=truncated, matches=_build_matches(db, created)
    )
    db.commit()
    return response


@router.get(
    "/periods/{period_id}/matches",
    response_model=MatchListResponse,
    summary="Matches in a period",
)
def list_matches(
    period_id: UUID,
    context: Annotated[OrganizationContext, Depends(require_period_permission(Permission.READ))],
    db: Annotated[Session, Depends(get_db_session)],
    status_filter: Annotated[MatchStatus | None, Query(alias="status")] = None,
) -> MatchListResponse:
    period = reconciliation_service.get_period(
        db, organization_id=context.organization_id, period_id=period_id
    )
    if period is None:  # pragma: no cover - the dependency already 404s
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Period not found.")

    matches = reconciliation_service.list_matches(db, period=period, status=status_filter)
    return MatchListResponse(matches=_build_matches(db, matches))


@router.get(
    "/matches/{match_id}",
    response_model=MatchResponse,
    summary="One match with its movements",
)
def get_match(
    match_id: UUID,
    context: Annotated[OrganizationContext, Depends(require_match_permission(Permission.READ))],
    db: Annotated[Session, Depends(get_db_session)],
) -> MatchResponse:
    match = reconciliation_service.get_match(
        db, organization_id=context.organization_id, match_id=match_id
    )
    if match is None:  # pragma: no cover - the dependency already 404s
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Match not found.")
    return _build_matches(db, [match])[0]


@router.post(
    "/periods/{period_id}/submit-review",
    response_model=PeriodResponse,
    summary="Submit a period for review",
)
def submit_review(
    period_id: UUID,
    context: Annotated[
        OrganizationContext, Depends(require_period_permission(Permission.RECONCILE))
    ],
    db: Annotated[Session, Depends(get_db_session)],
    _csrf: Annotated[None, Depends(require_csrf)] = None,
) -> PeriodResponse:
    period = reconciliation_service.get_period(
        db, organization_id=context.organization_id, period_id=period_id
    )
    if period is None:  # pragma: no cover - the dependency already 404s
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Period not found.")
    try:
        updated = reconciliation_service.submit_review(
            db,
            organization_id=context.organization_id,
            actor_id=context.user_id,
            period=period,
        )
    except reconciliation_service.ReconciliationServiceError as exc:
        raise _translate(exc) from exc
    response = PeriodResponse.model_validate(updated)
    db.commit()
    return response


@router.post(
    "/periods/{period_id}/approve",
    response_model=PeriodResponse,
    summary="Approve a reconciled period",
    description=(
        "Requires `approve`. Refused while any movement is pending or any "
        "difference remains: this phase has no justification model, so it never "
        "approves something it cannot explain."
    ),
    responses={409: {"description": "The period still has pending items or differences"}},
)
def approve_period(
    period_id: UUID,
    context: Annotated[OrganizationContext, Depends(require_period_permission(Permission.APPROVE))],
    db: Annotated[Session, Depends(get_db_session)],
    _csrf: Annotated[None, Depends(require_csrf)] = None,
) -> PeriodResponse:
    period = reconciliation_service.get_period(
        db, organization_id=context.organization_id, period_id=period_id
    )
    if period is None:  # pragma: no cover - the dependency already 404s
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Period not found.")
    try:
        updated = reconciliation_service.approve_period(
            db,
            organization_id=context.organization_id,
            actor_id=context.user_id,
            period=period,
        )
    except reconciliation_service.ReconciliationServiceError as exc:
        raise _translate(exc) from exc
    response = PeriodResponse.model_validate(updated)
    db.commit()
    return response


@router.post(
    "/periods/{period_id}/reopen",
    response_model=PeriodResponse,
    summary="Reopen an approved period",
)
def reopen_period(
    period_id: UUID,
    context: Annotated[OrganizationContext, Depends(require_period_permission(Permission.APPROVE))],
    db: Annotated[Session, Depends(get_db_session)],
    _csrf: Annotated[None, Depends(require_csrf)] = None,
) -> PeriodResponse:
    period = reconciliation_service.get_period(
        db, organization_id=context.organization_id, period_id=period_id
    )
    if period is None:  # pragma: no cover - the dependency already 404s
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Period not found.")
    try:
        updated = reconciliation_service.reopen_period(
            db,
            organization_id=context.organization_id,
            actor_id=context.user_id,
            period=period,
        )
    except reconciliation_service.ReconciliationServiceError as exc:
        raise _translate(exc) from exc
    response = PeriodResponse.model_validate(updated)
    db.commit()
    return response


@router.post(
    "/matches/{match_id}/confirm",
    response_model=MatchResponse,
    summary="Confirm a suggested match",
    description=(
        "Requires `reconcile`. Locks the movements, refuses if one is already "
        "confirmed elsewhere, and cancels the suggested alternatives that shared "
        "them."
    ),
    responses={409: {"description": "A movement is unavailable or the match is not suggested"}},
)
def confirm_match(
    match_id: UUID,
    context: Annotated[
        OrganizationContext, Depends(require_match_permission(Permission.RECONCILE))
    ],
    db: Annotated[Session, Depends(get_db_session)],
    _csrf: Annotated[None, Depends(require_csrf)] = None,
) -> MatchResponse:
    try:
        match = reconciliation_service.confirm_match(
            db,
            organization_id=context.organization_id,
            actor_id=context.user_id,
            match_id=match_id,
        )
    except reconciliation_service.ReconciliationServiceError as exc:
        raise _translate(exc) from exc
    response = _build_matches(db, [match])[0]
    db.commit()
    return response


@router.post(
    "/matches/{match_id}/reject",
    response_model=MatchResponse,
    summary="Reject a suggested match",
)
def reject_match(
    match_id: UUID,
    context: Annotated[
        OrganizationContext, Depends(require_match_permission(Permission.RECONCILE))
    ],
    db: Annotated[Session, Depends(get_db_session)],
    _csrf: Annotated[None, Depends(require_csrf)] = None,
) -> MatchResponse:
    try:
        match = reconciliation_service.reject_match(
            db,
            organization_id=context.organization_id,
            actor_id=context.user_id,
            match_id=match_id,
        )
    except reconciliation_service.ReconciliationServiceError as exc:
        raise _translate(exc) from exc
    response = _build_matches(db, [match])[0]
    db.commit()
    return response


@router.post(
    "/matches/{match_id}/cancel",
    response_model=MatchResponse,
    summary="Cancel a suggestion or undo a confirmation",
    description=(
        "Requires `reconcile`. Cancelling a **confirmed** match releases its "
        "movements so they can be suggested again; it is the correction path for "
        "a wrong confirmation. Reopening the period is not required."
    ),
)
def cancel_match(
    match_id: UUID,
    context: Annotated[
        OrganizationContext, Depends(require_match_permission(Permission.RECONCILE))
    ],
    db: Annotated[Session, Depends(get_db_session)],
    _csrf: Annotated[None, Depends(require_csrf)] = None,
) -> MatchResponse:
    try:
        match = reconciliation_service.cancel_match(
            db,
            organization_id=context.organization_id,
            actor_id=context.user_id,
            match_id=match_id,
        )
    except reconciliation_service.ReconciliationServiceError as exc:
        raise _translate(exc) from exc
    response = _build_matches(db, [match])[0]
    db.commit()
    return response
