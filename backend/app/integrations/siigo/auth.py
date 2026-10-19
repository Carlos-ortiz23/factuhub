"""Credentials and the access token they buy.

Siigo issues a JWT with an `expires_in` in seconds (86400 in the documented
example) and accepts it as `Authorization: Bearer <token>` on every request,
alongside a `Partner-Id` header naming the integrated application.

The token is held in memory only. It is never written to the database, a log, or
an exception: `repr=False` on the secret fields exists so that one accidental
`print(credentials)` does not put a credential in a terminal or a log file.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

#: Refresh this many seconds before the provider's deadline. A token that
#: expires while a request is in flight is an authentication error the caller
#: cannot fix.
DEFAULT_EXPIRY_SKEW_SECONDS = 60.0


@dataclass(frozen=True, slots=True)
class SiigoCredentials:
    """What the company supplied, exactly as Siigo expects it."""

    username: str
    access_key: str = field(repr=False)
    #: The application name Siigo requires on every request (3-100 alphanumeric
    #: characters). It is not a secret and not the company's identifier.
    partner_id: str = "FactuHub"


@dataclass(slots=True)
class SiigoTokenCache:
    """One token, with the deadline that decides when to ask for another."""

    clock: Callable[[], float] = time.monotonic
    skew_seconds: float = DEFAULT_EXPIRY_SKEW_SECONDS
    _value: str | None = field(default=None, repr=False)
    _expires_at: float = 0.0

    def get(self) -> str | None:
        if self._value is None or self.clock() >= self._expires_at:
            return None
        return self._value

    def store(self, token: str, *, expires_in: float) -> None:
        self._value = token
        self._expires_at = self.clock() + max(0.0, expires_in - self.skew_seconds)

    def invalidate(self) -> None:
        self._value = None
        self._expires_at = 0.0
