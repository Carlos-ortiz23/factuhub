"""Authentication endpoints.

Every rule worth protecting lives in `app.services.auth`; this module only
translates HTTP into those calls and back. In particular it never hashes,
compares or mints anything itself.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.api.cookies import clear_auth_cookies, set_auth_cookies
from app.api.deps import (
    AuthContext,
    get_app_settings,
    get_auth_context,
    get_db_session,
    require_csrf,
)
from app.core.config import Settings
from app.core.security import PasswordPolicyError
from app.models import User
from app.schemas.auth import LoginRequest, RegisterRequest, UserResponse
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    response_model=UserResponse,
    summary="Create an account",
    description=(
        "Creates a user. It does not sign the user in: the client is expected to "
        "call /auth/login next, so registration never leaves a session behind."
    ),
    responses={
        409: {"description": "An account already exists for this email address"},
        422: {"description": "The email or password does not satisfy the policy"},
    },
)
def register(
    payload: RegisterRequest,
    db: Annotated[Session, Depends(get_db_session)],
) -> User:
    try:
        user = auth_service.register_user(
            db,
            email=payload.email,
            full_name=payload.full_name,
            password=payload.password,
        )
    except auth_service.EmailAlreadyRegisteredError as exc:
        # Same answer whether the address belongs to an account or not would be
        # better, but registration inherently reveals that: the alternative is an
        # endpoint that silently does nothing. The rate limiter on /auth/login is
        # what protects the enumeration that matters.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account already exists for this email address.",
        ) from exc
    except PasswordPolicyError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    db.commit()
    return user


@router.post(
    "/login",
    response_model=UserResponse,
    summary="Sign in",
    description=(
        "Returns the user and sets two cookies: the session (HttpOnly) and the "
        "CSRF token (readable, to be echoed in the X-CSRF-Token header)."
    ),
    responses={
        401: {"description": "Wrong password, unknown email or disabled account"},
        429: {"description": "Too many failed attempts for this address"},
    },
)
def login(
    payload: LoginRequest,
    response: Response,
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> User:
    retry_after = auth_service.claim_login_attempt(db, email=payload.email)
    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed attempts. Try again later.",
            headers={"Retry-After": str(retry_after)},
        )

    # Commit the reserved attempt before checking the password. A failed login
    # ends in an exception, and the request-scoped session would roll the counter
    # back with it — which is precisely how a rate limiter stops limiting.
    db.commit()

    user = auth_service.authenticate(db, email=payload.email, password=payload.password)
    if user is None:
        # One message for a wrong password, an unknown email and a disabled
        # account: three different answers would be three different oracles.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    auth_service.clear_login_attempts(db, email=payload.email)
    session_token, csrf_token, _ = auth_service.create_session(db, user=user)
    db.commit()

    set_auth_cookies(
        response,
        session_token=session_token,
        csrf_token=csrf_token,
        settings=settings,
    )
    return user


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Sign out",
    description=(
        "Revokes the current session and clears both cookies. Requires a valid "
        "session and the CSRF header; a client whose session already expired "
        "should discard its own cookies instead."
    ),
    responses={403: {"description": "CSRF token missing or invalid"}},
)
def logout(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db_session)],
    context: Annotated[AuthContext, Depends(get_auth_context)],
    settings: Annotated[Settings, Depends(get_app_settings)],
    _csrf: Annotated[None, Depends(require_csrf)],
) -> None:
    auth_service.revoke_session(db, token=request.cookies.get(settings.session_cookie_name, ""))
    db.commit()
    clear_auth_cookies(response, settings)
    # `context` is not otherwise used, but requiring it is the point: an
    # unauthenticated logout would be a way to learn whether a token is valid.


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Current user",
    description="Returns the authenticated user. Used by the frontend on page load.",
    responses={401: {"description": "No valid session"}},
)
def read_me(context: Annotated[AuthContext, Depends(get_auth_context)]) -> User:
    return context.user
