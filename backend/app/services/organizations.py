"""Organizations and the memberships that link people to them.

Every function here takes the acting user explicitly. There is no ambient
"current user": that lives in the HTTP layer, and keeping it out of the service
is what lets the same code be reused by a future background job or CLI without
re-implementing authorization.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import MembershipRole, Organization, OrganizationMember


class OrganizationError(ValueError):
    """A refused organization operation, translated to 4xx by the endpoint."""


class OrganizationInputError(OrganizationError):
    """The submitted data is unusable once trimmed."""


class TaxIdAlreadyRegisteredError(OrganizationError):
    """Another company already uses this tax identification."""


def _clean_required(value: str, field: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise OrganizationInputError(f"{field} must not be blank.")
    return cleaned


def create_organization(
    db: Session,
    *,
    owner_id: UUID,
    name: str,
    tax_id: str,
) -> Organization:
    """Create a company and make `owner_id` its admin, atomically.

    Both rows are written inside one savepoint: a company without an admin would
    be unreachable, so it must never be possible to observe one.
    """
    cleaned_name = _clean_required(name, "Name")
    cleaned_tax_id = _clean_required(tax_id, "Tax id")

    organization = Organization(name=cleaned_name, tax_id=cleaned_tax_id)
    try:
        with db.begin_nested():
            db.add(organization)
            db.flush()
            db.add(
                OrganizationMember(
                    organization_id=organization.id,
                    user_id=owner_id,
                    role=MembershipRole.ADMIN,
                )
            )
            db.flush()
    except IntegrityError as exc:
        # The uniqueness constraint is the real guarantee: a prior SELECT would
        # still race. The tax id is the only unique column written here.
        raise TaxIdAlreadyRegisteredError(
            "A company with this tax id is already registered."
        ) from exc
    return organization


def list_organizations_for_user(
    db: Session, *, user_id: UUID
) -> list[tuple[Organization, MembershipRole]]:
    """Every company `user_id` belongs to, with the role held in each."""
    rows = db.execute(
        select(Organization, OrganizationMember.role)
        .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
        .where(OrganizationMember.user_id == user_id)
        .order_by(Organization.created_at, Organization.id)
    ).all()
    return [(organization, role) for organization, role in rows]


def find_membership(
    db: Session, *, organization_id: UUID, user_id: UUID
) -> tuple[Organization, MembershipRole] | None:
    """The company and the caller's role in it, or `None` if not a member.

    `None` covers both "no such company" and "not yours". The caller must turn
    both into the same 404; distinguishing them would let anyone enumerate
    companies by watching for 403.
    """
    row = db.execute(
        select(Organization, OrganizationMember.role)
        .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
        .where(
            Organization.id == organization_id,
            OrganizationMember.user_id == user_id,
        )
    ).one_or_none()
    if row is None:
        return None
    organization, role = row
    return organization, role
