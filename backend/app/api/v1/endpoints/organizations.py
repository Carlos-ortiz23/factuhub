"""Organization endpoints.

Authorization is not implemented here: every route that touches a company
declares the permission it needs through `require_permission`, and the resolution
of "is this person a member, and with which role" happens there, once, for all
of them.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

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
from app.models import MembershipRole, User
from app.schemas.organizations import (
    AddMemberRequest,
    ChangeMemberRoleRequest,
    MemberResponse,
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


def _translate(exc: organizations_service.OrganizationError) -> HTTPException:
    """Map a domain refusal onto the status that describes it.

    A duplicate membership and a last-admin refusal are both 409: the request is
    well-formed, and the current state of the company is what refuses it.
    """
    if isinstance(exc, organizations_service.UserNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, organizations_service.MembershipNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(
        exc,
        (
            organizations_service.MembershipAlreadyExistsError,
            organizations_service.LastAdminError,
        ),
    ):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


@router.post(
    "/{organization_id}/members",
    status_code=status.HTTP_201_CREATED,
    response_model=MemberResponse,
    summary="Add a member",
    description=(
        "Requires `manage_members`: admin only. The account must already exist — "
        "the platform does not send invitations yet."
    ),
    responses={
        403: {"description": "The caller's role cannot manage members"},
        404: {"description": "No such company, no such account, or not a member"},
        409: {"description": "That person is already a member"},
    },
)
def add_member(
    payload: AddMemberRequest,
    db: Annotated[Session, Depends(get_db_session)],
    context: Annotated[OrganizationContext, Depends(require_permission(Permission.MANAGE_MEMBERS))],
    _csrf: Annotated[None, Depends(require_csrf)],
) -> MemberResponse:
    try:
        membership, user = organizations_service.add_member(
            db,
            organization_id=context.organization_id,
            email=payload.email,
            role=payload.role,
        )
    except organizations_service.OrganizationError as exc:
        raise _translate(exc) from exc

    db.commit()
    return MemberResponse(
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=membership.role,
        created_at=membership.created_at,
    )


@router.patch(
    "/{organization_id}/members/{user_id}",
    response_model=MemberResponse,
    summary="Change a member's role",
    description=(
        "Requires `manage_members`: admin only. Refuses to demote the only "
        "administrator of a company."
    ),
    responses={
        403: {"description": "The caller's role cannot manage members"},
        404: {"description": "No such company, no such member, or not a member"},
        409: {"description": "This is the only administrator"},
    },
)
def change_member_role(
    user_id: UUID,
    payload: ChangeMemberRoleRequest,
    db: Annotated[Session, Depends(get_db_session)],
    context: Annotated[OrganizationContext, Depends(require_permission(Permission.MANAGE_MEMBERS))],
    _csrf: Annotated[None, Depends(require_csrf)],
) -> MemberResponse:
    try:
        membership = organizations_service.change_member_role(
            db,
            organization_id=context.organization_id,
            user_id=user_id,
            role=payload.role,
        )
    except organizations_service.OrganizationError as exc:
        raise _translate(exc) from exc

    user = db.get(User, user_id)
    db.commit()
    return MemberResponse(
        user_id=user_id,
        email=user.email,
        full_name=user.full_name,
        role=membership.role,
        created_at=membership.created_at,
    )


@router.delete(
    "/{organization_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a member",
    description=(
        "Requires `manage_members`: admin only. Removes the membership, not the "
        "account, and refuses to remove the only administrator."
    ),
    responses={
        403: {"description": "The caller's role cannot manage members"},
        404: {"description": "No such company, no such member, or not a member"},
        409: {"description": "This is the only administrator"},
    },
)
def remove_member(
    user_id: UUID,
    db: Annotated[Session, Depends(get_db_session)],
    context: Annotated[OrganizationContext, Depends(require_permission(Permission.MANAGE_MEMBERS))],
    _csrf: Annotated[None, Depends(require_csrf)],
) -> None:
    try:
        organizations_service.remove_member(
            db,
            organization_id=context.organization_id,
            user_id=user_id,
        )
    except organizations_service.OrganizationError as exc:
        raise _translate(exc) from exc

    db.commit()
