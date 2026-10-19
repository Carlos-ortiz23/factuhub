"""Session and CSRF cookies.

Two cookies, two audiences:

- the **session** cookie is `HttpOnly`, so JavaScript cannot read it and an XSS
  bug cannot exfiltrate a working session;
- the **CSRF** cookie is readable on purpose, because the frontend has to copy it
  into the `X-CSRF-Token` header. On its own it grants nothing: the server
  compares it against the value bound to the session in the database.

`SameSite=Lax` is the baseline defence, and it is not negotiable: it stops a
cross-site POST from carrying the session cookie at all. The header check exists
because a sibling subdomain can still set cookies for the whole site, and
`SameSite` cannot see that.
"""

from __future__ import annotations

from fastapi import Response

from app.core.config import Settings

#: Header the client must echo the CSRF cookie in.
CSRF_HEADER_NAME = "X-CSRF-Token"


def csrf_cookie_name(settings: Settings) -> str:
    """Return the CSRF cookie name, derived from the session cookie name.

    Derived so a deployment that renames the session cookie cannot end up with a
    CSRF cookie whose name still points at the old one.
    """
    return f"{settings.session_cookie_name}_csrf"


def _cookie_kwargs(settings: Settings, *, httponly: bool) -> dict[str, object]:
    return {
        "httponly": httponly,
        "secure": settings.session_cookie_is_secure,
        "samesite": "lax",
        "path": "/",
    }


def set_auth_cookies(
    response: Response,
    *,
    session_token: str,
    csrf_token: str,
    settings: Settings,
) -> None:
    """Attach the session and CSRF cookies to a response."""
    max_age = settings.session_ttl_hours * 3600
    response.set_cookie(
        key=settings.session_cookie_name,
        value=session_token,
        max_age=max_age,
        **_cookie_kwargs(settings, httponly=True),
    )
    response.set_cookie(
        key=csrf_cookie_name(settings),
        value=csrf_token,
        max_age=max_age,
        **_cookie_kwargs(settings, httponly=False),
    )


def clear_auth_cookies(response: Response, settings: Settings) -> None:
    """Remove both cookies, matching the attributes they were set with.

    A cookie deleted without the same `path` and `secure` attributes is a second
    cookie, not a deletion.
    """
    response.delete_cookie(
        key=settings.session_cookie_name,
        **_cookie_kwargs(settings, httponly=True),
    )
    response.delete_cookie(
        key=csrf_cookie_name(settings),
        **_cookie_kwargs(settings, httponly=False),
    )
