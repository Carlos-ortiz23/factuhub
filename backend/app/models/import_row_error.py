"""Per-row import failures.

The job summary says "3 of 120 rows failed"; this table says which rows and why.
Keeping the file row number means the accountant can open the original in Excel
and go straight to the problem instead of guessing.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import ForeignKey, Index, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import CreatedAtMixin, UuidPrimaryKeyMixin

FIELD_MAX_LENGTH = 50
MESSAGE_MAX_LENGTH = 300


class ImportRowError(Base, UuidPrimaryKeyMixin, CreatedAtMixin):
    """One rejected cell or row, with a bounded, human-readable reason."""

    __tablename__ = "import_row_errors"

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    import_job_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("import_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )

    #: Spreadsheet row number, header included, so it matches what the user sees.
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    field: Mapped[str | None] = mapped_column(String(FIELD_MAX_LENGTH), nullable=True)
    message: Mapped[str] = mapped_column(String(MESSAGE_MAX_LENGTH), nullable=False)

    __table_args__ = (Index("ix_import_row_errors_job_row", "import_job_id", "row_number"),)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"ImportRowError(job={self.import_job_id!r}, "
            f"row={self.row_number!r}, message={self.message!r})"
        )
