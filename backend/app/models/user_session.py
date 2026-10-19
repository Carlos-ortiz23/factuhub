"""Server-side sessions.

A session is a row, not a self-contained token. That choice costs one indexed
lookup per authenticated request and buys the ability to revoke: logging out,
disabling an account, or removing someone from a company can end access
immediately. A signed stateless token would remain valid until it expired, no
matter what the database says about the person holding it.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import CreatedAtMixin, UuidPrimaryKeyMixin

#: Hex SHA-256 digest of the session token.
TOKEN_HASH_LENGTH = 64

#: Capacity for the CSRF token, which is a 43-character base64url value. It is
#: intentionally *not* hashed: the browser must be able to read it to echo it
#: back, and on its own it grants nothing.
CSRF_TOKEN_MAX_LENGTH = 64


class UserSession(Base, UuidPrimaryKeyMixin, CreatedAtMixin):
    """One issued session token, stored as a digest."""

    __tablename__ = "sessions"

    # Deleting an account ends its sessions; an orphaned live session would be
    # access nobody can account for.
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    # The raw token is never stored, so a leaked backup or a read-only database
    # dump does not hand out working sessions.
    token_hash: Mapped[str] = mapped_column(String(TOKEN_HASH_LENGTH), nullable=False, unique=True)

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Sent to the browser in a cookie the frontend can read, and echoed back in
    # the `X-CSRF-Token` header. Stored server-side so that comparing it against
    # the cookie alone is not the whole check: a cookie injected from a sibling
    # domain does not match the token bound to this session.
    csrf_token: Mapped[str] = mapped_column(String(CSRF_TOKEN_MAX_LENGTH), nullable=False)

    # Set instead of deleting the row: a revoked session is evidence, and
    # "cuándo se cerró esta sesión" is a question a client will eventually ask.
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # "Revoke every session of this user" is the query a permission change or
        # a password reset runs.
        Index("ix_sessions_user_id", "user_id"),
    )

    def is_usable_at(self, moment: datetime) -> bool:
        """Return whether this session is neither revoked nor expired."""
        return self.revoked_at is None and self.expires_at > moment

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"UserSession(id={self.id!r}, user_id={self.user_id!r})"
