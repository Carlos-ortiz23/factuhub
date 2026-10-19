"""Shared FastAPI dependencies."""

from __future__ import annotations

import secrets
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.cookies import CSRF_HEADER_NAME, csrf_cookie_name
from app.core.config import Settings
from app.core.crypto import CredentialCipher
from app.core.permissions import Permission, role_has_permission
from app.db.session import get_session_factory
from app.imports.storage import ImportStorage, LocalImportStorage
from app.integrations.connectors import ConnectorFactory, build_connector
from app.models import MembershipRole, Organization, User, UserSession
from app.services import auth as auth_service
from app.services import organizations as organizations_service

#: Methods that do not change state and therefore do not need a CSRF token.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


def get_db_session() -> Iterator[Session]:
    """Yield a database session for one request, always closing it afterwards.

    The session is not committed here: a request handler decides whether it
    completes a unit of work, so a failed handler can never leave a half-applied
    financial mutation behind.
    """
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def get_app_settings(request: Request) -> Settings:
    """Return the settings attached to the running application.

    Read from `app.state` instead of the module-level cache so a test or a
    factory-built app can be configured without touching the environment.
    """
    return request.app.state.settings


def get_credential_cipher(
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> CredentialCipher:
    """Build the cipher from the deployment key, failing loudly if it is invalid."""
    return CredentialCipher.from_key(settings.credentials_encryption_key)


def get_connector_factory() -> ConnectorFactory:
    """The adapter builder, as a dependency tests can override.

    Keeping this behind a dependency is what lets the connection test run against
    a stand-in connector in the suite without any provider-specific test branch in
    the endpoint.
    """
    return build_connector


def get_import_storage(
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> ImportStorage:
    """Private storage for uploaded originals, overridable in tests."""
    return LocalImportStorage(settings.import_storage_dir)


@dataclass(frozen=True, slots=True)
class AuthContext:
    """The authenticated user and the session that vouched for them."""

    user: User
    session: UserSession


def get_auth_context(
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> AuthContext:
    """Resolve the session cookie into an authenticated user.

    A missing, expired, revoked or orphaned session is the same 401: the client
    learns nothing about which of those it was.
    """
    token = request.cookies.get(settings.session_cookie_name)
    context = auth_service.resolve_session_context(db, token=token) if token else None
    if context is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )

    user, session_row = context
    return AuthContext(user=user, session=session_row)


def require_csrf(
    request: Request,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> None:
    """Reject a state-changing request that does not prove it can read the cookie.

    Three values must agree: the header, the cookie, and the token stored with
    the session. Comparing against the stored value is what makes an injected
    cookie from a sibling domain useless.
    """
    if request.method in SAFE_METHODS:
        return

    header_value = request.headers.get(CSRF_HEADER_NAME)
    cookie_value = request.cookies.get(csrf_cookie_name(settings))
    expected = context.session.csrf_token

    # Compared as bytes: `compare_digest` on str refuses non-ASCII input, and a
    # malformed header must be a 403, not a 500.
    header_matches = bool(header_value) and secrets.compare_digest(
        header_value.encode("utf-8"), expected.encode("utf-8")
    )
    cookie_matches = bool(cookie_value) and secrets.compare_digest(
        cookie_value.encode("utf-8"), expected.encode("utf-8")
    )

    if not (header_matches and cookie_matches):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF token missing or invalid.",
        )


@dataclass(frozen=True, slots=True)
class OrganizationContext:
    """The company being operated on, and who is acting in it, with which role."""

    organization: Organization
    role: MembershipRole
    user_id: UUID

    @property
    def organization_id(self) -> UUID:
        return self.organization.id

    def can(self, permission: Permission) -> bool:
        """Whether the caller may perform `permission` in this company.

        Handlers use this for decisions the route cannot express — showing a
        field only to an approver, for instance — while the dependency below
        remains the enforcement point.
        """
        return role_has_permission(self.role, permission)


def require_permission(permission: Permission) -> Callable[..., OrganizationContext]:
    """Build the dependency that enforces `permission` on one company.

    Usage: `context: Annotated[OrganizationContext, Depends(require_permission(Permission.READ))]`
    on a route carrying `{organization_id}`.

    Two rules are deliberate:

    * Membership is checked before the permission, and a non-member gets 404,
      not 403. Answering 403 would confirm the company exists.
    * The role is resolved from the database on every request, never from
      anything the client sent. A role carried in a token would be a role that
      stays valid after it was revoked.
    """

    def dependency(
        organization_id: UUID,
        db: Annotated[Session, Depends(get_db_session)],
        auth: Annotated[AuthContext, Depends(get_auth_context)],
    ) -> OrganizationContext:
        found = organizations_service.find_membership(
            db, organization_id=organization_id, user_id=auth.user.id
        )
        if found is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Organization not found.",
            )

        organization, role = found
        if not role_has_permission(role, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Your role in this organization cannot {permission.value}.",
            )

        return OrganizationContext(organization=organization, role=role, user_id=auth.user.id)

    return dependency
