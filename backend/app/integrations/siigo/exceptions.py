"""Errors a Siigo call can raise.

Every message here is safe to log and to return to the browser: it carries the
HTTP status and a bounded provider message, never a header, a username or a
token. The client strips those before constructing the exception, so the rule
does not depend on every caller remembering it.
"""

from __future__ import annotations


class SiigoError(Exception):
    """Base class for every refusal from the Siigo adapter."""


class SiigoAuthError(SiigoError):
    """The credentials were rejected, or no token could be obtained."""


class SiigoRequestError(SiigoError):
    """The provider rejected a well-formed request."""


class SiigoNotFoundError(SiigoRequestError):
    """The requested resource does not exist."""


class SiigoRateLimitedError(SiigoError):
    """The provider kept asking us to slow down after the retries ran out."""


class SiigoUnavailableError(SiigoError):
    """The provider could not be reached, or kept failing after the retries."""


class SiigoMappingError(SiigoError):
    """The provider answered with a shape the adapter cannot map safely."""
