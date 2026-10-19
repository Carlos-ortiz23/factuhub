"""Failed-login counters, keyed by email address.

The counter lives in the database rather than in process memory on purpose: a
worker-local dictionary protects exactly the worker that happens to receive the
next request, so with two instances an attacker gets twice the attempts — and
resets the count entirely by reconnecting to the other one.

Only a count and a window start are kept, not a history of attempts: enough to
slow down credential stuffing, nothing that would turn this table into a second,
unreviewed log of who tried to sign in from where.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import UuidPrimaryKeyMixin

#: Same capacity as `users.email`, so the two can never disagree about what a
#: valid address is.
EMAIL_MAX_LENGTH = 320


class LoginThrottle(Base, UuidPrimaryKeyMixin):
    """The attempt budget of one email address within the current window."""

    __tablename__ = "login_throttles"

    # Unique because the row is the lock: `claim_login_attempt` inserts it with
    # ON CONFLICT DO NOTHING and then takes it FOR UPDATE, which serialises
    # concurrent attempts instead of letting them all pass the check.
    email: Mapped[str] = mapped_column(String(EMAIL_MAX_LENGTH), nullable=False, unique=True)

    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"LoginThrottle(email={self.email!r}, failed_count={self.failed_count!r})"
