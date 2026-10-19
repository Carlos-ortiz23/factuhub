"""Registration, credential verification and session lifecycle.

The service layer owns the rules that must hold no matter who calls it — an HTTP
endpoint today, a CLI or an import job tomorrow. It does not know about cookies,
HTTP status codes or request bodies; those belong to the API layer.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from functools import lru_cache
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import (
    generate_session_token,
    hash_password,
    hash_session_token,
    verify_password,
)
from app.models import User, UserSession


class RegistrationError(ValueError):
    """The registration request cannot produce a usable account."""


class EmailAlreadyRegisteredError(RegistrationError):
    """An account already exists for the normalized email address."""


def normalize_email(email: str) -> str:
    """Return the canonical form of an email address.

    Lowercased and trimmed because `Contador@Example.com ` and
    `contador@example.com` are the same mailbox, and treating them as two
    accounts splits one person's history in two.
    """
    return email.strip().lower()


def _clean_full_name(full_name: str) -> str:
    cleaned = full_name.strip()
    if not cleaned:
        raise RegistrationError("Full name must not be empty.")
    return cleaned


@lru_cache(maxsize=1)
def _dummy_password_hash() -> str:
    """A valid hash used only to spend the same time on an unknown user.

    Without it, `authenticate` would return faster for an email that does not
    exist than for one that does, and that difference is a reliable oracle for
    discovering which accounts are real. Computed once, not per request.
    """
    return hash_password("timing-equalizer-not-a-real-password")


def register_user(
    db: Session,
    *,
    email: str,
    full_name: str,
    password: str,
) -> User:
    """Create a user, or raise if the email is taken.

    The password policy is checked by `hash_password` before anything is
    written, so a rejected password cannot leave a half-created account.
    """
    normalized_email = normalize_email(email)
    cleaned_name = _clean_full_name(full_name)
    password_hash = hash_password(password)

    existing = db.scalar(select(User.id).where(User.email == normalized_email))
    if existing is not None:
        raise EmailAlreadyRegisteredError(f"An account already exists for {normalized_email}.")

    user = User(email=normalized_email, full_name=cleaned_name, password_hash=password_hash)
    try:
        # The uniqueness check above is only a courtesy: two requests can pass it
        # at the same time. The database constraint is the real guarantee, and
        # the savepoint keeps the caller's transaction usable after it fires.
        with db.begin_nested():
            db.add(user)
            db.flush()
    except IntegrityError as exc:
        raise EmailAlreadyRegisteredError(
            f"An account already exists for {normalized_email}."
        ) from exc
    return user


def authenticate(db: Session, *, email: str, password: str) -> User | None:
    """Return the user for valid credentials, or `None` for every failure.

    A wrong password, an unknown email and a disabled account are deliberately
    indistinguishable to the caller.
    """
    user = db.scalar(select(User).where(User.email == normalize_email(email)))

    if user is None:
        verify_password(password, _dummy_password_hash())
        return None

    if not verify_password(password, user.password_hash):
        return None

    return user if user.is_active else None


def create_session(
    db: Session,
    *,
    user: User,
    ttl: timedelta | None = None,
) -> tuple[str, UserSession]:
    """Issue a new session and return `(raw_token, stored_row)`.

    The raw token is returned exactly once, to be placed in a cookie. Only its
    digest is persisted.
    """
    effective_ttl = ttl if ttl is not None else timedelta(hours=get_settings().session_ttl_hours)
    token = generate_session_token()
    session_row = UserSession(
        user_id=user.id,
        token_hash=hash_session_token(token),
        expires_at=datetime.now(UTC) + effective_ttl,
    )
    db.add(session_row)
    db.flush()
    return token, session_row


def resolve_session(db: Session, *, token: str) -> User | None:
    """Return the active user behind a raw token, or `None`.

    Checks the token's digest, the session's deadline, its revocation state and
    the account's current `is_active` flag. The last check is why this is a
    database read and not a signature verification: disabling a person must take
    effect now, not when their cookie happens to expire.
    """
    if not token:
        return None

    session_row = db.scalar(
        select(UserSession).where(UserSession.token_hash == hash_session_token(token))
    )
    if session_row is None or not session_row.is_usable_at(datetime.now(UTC)):
        return None

    user = db.get(User, session_row.user_id)
    if user is None or not user.is_active:
        return None
    return user


def revoke_session(db: Session, *, token: str) -> bool:
    """End one session. Returns whether there was a live session to end."""
    if not token:
        return False

    session_row = db.scalar(
        select(UserSession).where(UserSession.token_hash == hash_session_token(token))
    )
    if session_row is None or session_row.revoked_at is not None:
        return False

    session_row.revoked_at = datetime.now(UTC)
    db.flush()
    return True


def revoke_all_sessions(db: Session, *, user_id: UUID) -> int:
    """End every live session of a user and return how many were ended.

    Used when a password changes or permissions are reduced: the old cookie must
    not keep the permissions it was issued under.
    """
    now = datetime.now(UTC)
    sessions = db.scalars(
        select(UserSession).where(
            UserSession.user_id == user_id,
            UserSession.revoked_at.is_(None),
        )
    ).all()
    for session_row in sessions:
        session_row.revoked_at = now
    db.flush()
    return len(sessions)
