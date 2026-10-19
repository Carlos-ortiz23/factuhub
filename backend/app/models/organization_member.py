"""Membership: which role a user holds inside an organization."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Uuid
from sqlalchemy import Enum as SaEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import CreatedAtMixin

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.user import User

ROLE_COLUMN_LENGTH = 32


class MembershipRole(StrEnum):
    """The four roles named in the specification (§7.2)."""

    ADMIN = "admin"
    ACCOUNTANT = "accountant"
    REVIEWER = "reviewer"
    VIEWER = "viewer"


ROLE_VALUES: tuple[str, ...] = tuple(member.value for member in MembershipRole)

#: The allowed roles as a SQL list: `'admin', 'accountant', 'reviewer', 'viewer'`.
#: Derived from the enum above so a new role cannot be added to Python without
#: appearing here.
ROLES_SQL_LIST = ", ".join(f"'{value}'" for value in ROLE_VALUES)


class OrganizationMember(Base, CreatedAtMixin):
    """Composite-key membership row.

    The primary key is the pair itself: a user can hold exactly one role in a
    given company, which the database enforces instead of the application
    remembering to check.
    """

    __tablename__ = "organization_members"

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role: Mapped[MembershipRole] = mapped_column(
        SaEnum(
            MembershipRole,
            name="membership_role",
            native_enum=False,
            # The valid values are enforced by the explicit CheckConstraint
            # below; letting the Enum emit its own constraint too creates a
            # second, identical constraint in the database.
            create_constraint=False,
            length=ROLE_COLUMN_LENGTH,
            validate_strings=True,
            # Without this, SQLAlchemy persists the member NAME ("ADMIN")
            # instead of its value ("admin"), which would silently disagree
            # with every API payload and test fixture.
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )

    organization: Mapped[Organization] = relationship(back_populates="members")
    user: Mapped[User] = relationship(back_populates="memberships")

    __table_args__ = (CheckConstraint(f"role IN ({ROLES_SQL_LIST})", name="role_is_known"),)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"OrganizationMember(organization_id={self.organization_id!r}, "
            f"user_id={self.user_id!r}, role={self.role.value!r})"
        )
