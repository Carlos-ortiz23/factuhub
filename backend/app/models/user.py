"""User account."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, String, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import CreatedAtMixin, UuidPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.organization_member import OrganizationMember

MAX_EMAIL_LENGTH = 320  # the RFC 5321 upper bound for an email address


class User(Base, UuidPrimaryKeyMixin, CreatedAtMixin):
    """A person who can sign in.

    A user is global, not owned by an organization: the same person may work for
    two companies, and their audit trail must survive leaving one of them. The
    link to a company lives in `organization_members`.
    """

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(MAX_EMAIL_LENGTH), nullable=False, unique=True)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)

    # Assumption, not part of the specification's field list: authentication
    # requires a stored credential. The hash, never the password.
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    # An account must be disableable without deleting its history.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=true())

    memberships: Mapped[list[OrganizationMember]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        # Enforced in the database, not only in the request schema: an
        # uppercase variant would otherwise create a second account that looks
        # like a duplicate to every human, and login would be case-sensitive
        # by accident.
        CheckConstraint("email = lower(email)", name="email_is_lowercase"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"User(id={self.id!r}, email={self.email!r})"
