"""Organization endpoints.

Authorization is not implemented here: every route that touches a company
declares the permission it needs through `require_permission`, and the resolution
of "is this person a member, and with which role" happens there, once, for all
of them.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import (
    AuthContext,
    OrganizationContext,
    get_auth_context,
    get_db_session,
    require_csrf,
    require_permission,
)
from app.core.permissions import Permission
from app.models import MembershipRole
from app.schemas.organizations import (
    OrganizationCreateRequest,
    OrganizationListResponse,
    OrganizationResponse,
)
from app.services import organizations as organizations_service

router = APIRouter(prefix="/organizations", tags=["organizations"])


def _as_response(organization, role: MembershipRole) -> OrganizationResponse:
    return OrganizationResponse(
        id=organization.id,
        name=organization.name,
        tax_id=organization.tax_id,
        role=role,
        created_at=organization.created_at,
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=OrganizationResponse,
    summary="Create a company",
    description=(
        "Creates the company and makes the caller its admin, in one transaction. "
        "A company without an admin would be unreachable, so one is never "
        "created."
    ),
    responses={
        409: {"description": "Another company already uses this tax id"},
        422: {"description": "The name or tax id is empty"},
    },
)
def create_organization(
    payload: OrganizationCreateRequest,
    db: Annotated[Session, Depends(get_db_session)],
    context: Annotated[AuthContext, Depends(get_auth_context)],
    _csrf: Annotated[None, Depends(require_csrf)],
) -> OrganizationResponse:
    try:
        organization = organizations_service.create_organization(
            db,
            owner_id=context.user.id,
            name=payload.name,
            tax_id=payload.tax_id,
        )
    except organizations_service.TaxIdAlreadyRegisteredError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except organizations_service.OrganizationInputError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    db.commit()
    return _as_response(organization, MembershipRole.ADMIN)


@router.get(
    "",
    response_model=OrganizationListResponse,
    summary="Companies I belong to",
    description=(
        "Only the caller's memberships. A company they are not part of is not "
        "filtered out afterwards: it is never selected."
    ),
)
def list_organizations(
    db: Annotated[Session, Depends(get_db_session)],
    context: Annotated[AuthContext, Depends(get_auth_context)],
) -> OrganizationListResponse:
    memberships = organizations_service.list_organizations_for_user(db, user_id=context.user.id)
    return OrganizationListResponse(
        organizations=[_as_response(organization, role) for organization, role in memberships]
    )


@router.get(
    "/{organization_id}",
    response_model=OrganizationResponse,
    summary="One company",
    responses={404: {"description": "No such company, or the caller is not a member"}},
)
def read_organization(
    context: Annotated[OrganizationContext, Depends(require_permission(Permission.READ))],
) -> OrganizationResponse:
    return _as_response(context.organization, context.role)
