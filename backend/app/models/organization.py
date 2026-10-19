"""Organization: the tenant boundary of the whole platform."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import CreatedAtMixin, UuidPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.organization_member import OrganizationMember


class Organization(Base, UuidPrimaryKeyMixin, CreatedAtMixin):
    """A company whose financial data is isolated from every other company."""

    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(200), nullable=False)

    # Tax identification (NIT in Colombia). Unique because two records for the
    # same legal entity would silently split its reconciliation history.
    tax_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)

    members: Mapped[list[OrganizationMember]] = relationship(
        back_populates="organization",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Organization(id={self.id!r}, tax_id={self.tax_id!r})"
