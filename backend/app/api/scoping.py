"""Membership checks for routes addressed by an entity id.

Most routes carry `{organization_id}` and `require_permission` can check the
caller directly. A few resources (a bank account, an import) are addressed by
their own id, exactly as the specification's paths show. The entity is loaded
first and its company is the one the caller must belong to.

Both "no such entity" and "not a member" answer with the same 404 and the same
message: distinguishing them would tell an outsider whether an id exists.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, OrganizationContext, get_auth_context, get_db_session
from app.core.permissions import Permission, role_has_permission
from app.models import (
    BankAccount,
    ImportJob,
    ReconciliationMatch,
    ReconciliationPeriod,
)
from app.services import organizations as organizations_service


def _context_for(
    db: Session,
    auth: AuthContext,
    *,
    organization_id: UUID,
    permission: Permission,
    not_found_detail: str,
) -> OrganizationContext:
    found = organizations_service.find_membership(
        db, organization_id=organization_id, user_id=auth.user.id
    )
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=not_found_detail)

    organization, role = found
    if not role_has_permission(role, permission):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Your role in this organization cannot {permission.value}.",
        )
    return OrganizationContext(organization=organization, role=role, user_id=auth.user.id)


def require_bank_account_permission(
    permission: Permission,
) -> Callable[..., OrganizationContext]:
    """Build the dependency for a route carrying `{account_id}`."""

    def dependency(
        account_id: UUID,
        db: Annotated[Session, Depends(get_db_session)],
        auth: Annotated[AuthContext, Depends(get_auth_context)],
    ) -> OrganizationContext:
        account = db.get(BankAccount, account_id)
        if account is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Bank account not found."
            )
        return _context_for(
            db,
            auth,
            organization_id=account.organization_id,
            permission=permission,
            not_found_detail="Bank account not found.",
        )

    return dependency


def require_import_permission(permission: Permission) -> Callable[..., OrganizationContext]:
    """Build the dependency for a route carrying `{import_id}`."""

    def dependency(
        import_id: UUID,
        db: Annotated[Session, Depends(get_db_session)],
        auth: Annotated[AuthContext, Depends(get_auth_context)],
    ) -> OrganizationContext:
        job = db.get(ImportJob, import_id)
        if job is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import not found.")
        return _context_for(
            db,
            auth,
            organization_id=job.organization_id,
            permission=permission,
            not_found_detail="Import not found.",
        )

    return dependency


def require_period_permission(permission: Permission) -> Callable[..., OrganizationContext]:
    """Build the dependency for a route carrying `{period_id}`."""

    def dependency(
        period_id: UUID,
        db: Annotated[Session, Depends(get_db_session)],
        auth: Annotated[AuthContext, Depends(get_auth_context)],
    ) -> OrganizationContext:
        period = db.get(ReconciliationPeriod, period_id)
        if period is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Period not found.")
        return _context_for(
            db,
            auth,
            organization_id=period.organization_id,
            permission=permission,
            not_found_detail="Period not found.",
        )

    return dependency


def require_match_permission(permission: Permission) -> Callable[..., OrganizationContext]:
    """Build the dependency for a route carrying `{match_id}`."""

    def dependency(
        match_id: UUID,
        db: Annotated[Session, Depends(get_db_session)],
        auth: Annotated[AuthContext, Depends(get_auth_context)],
    ) -> OrganizationContext:
        match = db.get(ReconciliationMatch, match_id)
        if match is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Match not found.")
        return _context_for(
            db,
            auth,
            organization_id=match.organization_id,
            permission=permission,
            not_found_detail="Match not found.",
        )

    return dependency
