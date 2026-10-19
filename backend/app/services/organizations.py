"""Organizations and the memberships that link people to them.

Every function here takes the acting user explicitly. There is no ambient
"current user": that lives in the HTTP layer, and keeping it out of the service
is what lets the same code be reused by a future background job or CLI without
re-implementing authorization.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import MembershipRole, Organization, OrganizationMember, User
from app.services.auth import normalize_email


class OrganizationError(ValueError):
    """A refused organization operation, translated to 4xx by the endpoint."""


class OrganizationInputError(OrganizationError):
    """The submitted data is unusable once trimmed."""


class TaxIdAlreadyRegisteredError(OrganizationError):
    """Another company already uses this tax identification."""


class UserNotFoundError(OrganizationError):
    """No account exists for the address being added."""


class MembershipAlreadyExistsError(OrganizationError):
    """That person already holds a role in this company."""


class MembershipNotFoundError(OrganizationError):
    """That person is not a member of this company."""


class LastAdminError(OrganizationError):
    """The change would leave the company without an administrator."""


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


def _lock_organization(db: Session, *, organization_id: UUID) -> None:
    """Take the company's row lock for the rest of the transaction.

    Every membership change is a read-then-write ("is there another admin?"),
    and two admins demoting themselves at the same instant would both read the
    other and both succeed, leaving a company nobody can administer. The lock
    serialises membership changes per company; it is taken on `organizations`
    rather than on a membership row because the row being changed may not exist
    yet.
    """
    db.execute(select(Organization.id).where(Organization.id == organization_id).with_for_update())


def _admin_count(db: Session, *, organization_id: UUID) -> int:
    count = db.scalar(
        select(func.count())
        .select_from(OrganizationMember)
        .where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.role == MembershipRole.ADMIN,
        )
    )
    return count or 0


def add_member(
    db: Session,
    *,
    organization_id: UUID,
    email: str,
    role: MembershipRole,
) -> tuple[OrganizationMember, User]:
    """Give an existing account a role in a company.

    The account must already exist: the platform does not send invitations yet,
    and pretending to would be worse than refusing.
    """
    normalized_email = normalize_email(email)
    user = db.scalar(select(User).where(User.email == normalized_email))
    if user is None:
        raise UserNotFoundError(f"No account exists for {normalized_email}.")

    membership = OrganizationMember(
        organization_id=organization_id,
        user_id=user.id,
        role=role,
    )
    try:
        with db.begin_nested():
            db.add(membership)
            db.flush()
    except IntegrityError as exc:
        # The composite primary key is the guarantee; the unique rule is the
        # pair, so a person cannot hold two roles in the same company.
        raise MembershipAlreadyExistsError(
            f"{normalized_email} is already a member of this organization."
        ) from exc
    return membership, user


def change_member_role(
    db: Session,
    *,
    organization_id: UUID,
    user_id: UUID,
    role: MembershipRole,
) -> OrganizationMember:
    """Change somebody's role, refusing to leave the company without an admin."""
    _lock_organization(db, organization_id=organization_id)

    membership = db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == user_id,
        )
    )
    if membership is None:
        raise MembershipNotFoundError("That person is not a member of this organization.")

    demoting_an_admin = membership.role is MembershipRole.ADMIN and role is not MembershipRole.ADMIN
    if demoting_an_admin and _admin_count(db, organization_id=organization_id) <= 1:
        raise LastAdminError(
            "This is the only administrator: add another one before changing this role."
        )

    membership.role = role
    db.flush()
    return membership


def remove_member(db: Session, *, organization_id: UUID, user_id: UUID) -> None:
    """Remove somebody's membership, refusing to leave the company without an admin."""
    _lock_organization(db, organization_id=organization_id)

    membership = db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == user_id,
        )
    )
    if membership is None:
        raise MembershipNotFoundError("That person is not a member of this organization.")

    if (
        membership.role is MembershipRole.ADMIN
        and _admin_count(db, organization_id=organization_id) <= 1
    ):
        raise LastAdminError(
            "This is the only administrator: add another one before removing this membership."
        )

    db.delete(membership)
    db.flush()
