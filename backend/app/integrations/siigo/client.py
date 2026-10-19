"""HTTP client for Siigo API (Colombia).

Verified against the official documentation on 2026-10-19:

* `POST https://api.siigo.com/auth` with `partner_id` in the `Partner-Id` header
  and `{username, access_key}` in the body returns
  `{access_token, expires_in, token_type: "Bearer"}`.
* Every request carries `Authorization: Bearer <token>` and `Partner-Id`.
* `GET /v1/journals` lists journal entries with `date_start`, `date_end`,
  `page` and `page_size`, and answers
  `{pagination: {page, page_size, total_results}, results: [...]}`.

What it deliberately does not do: log a request, a header or a body. The only
place a credential could escape is an exception message, and `_safe_detail`
strips it before the exception is built.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any

import httpx
from pydantic import ValidationError

from app.integrations.siigo.auth import SiigoCredentials, SiigoTokenCache
from app.integrations.siigo.exceptions import (
    SiigoAuthError,
    SiigoError,
    SiigoMappingError,
    SiigoNotFoundError,
    SiigoRateLimitedError,
    SiigoRequestError,
    SiigoUnavailableError,
)
from app.integrations.siigo.schemas import (
    SiigoJournal,
    SiigoJournalPage,
    SiigoTokenResponse,
)

DEFAULT_BASE_URL = "https://api.siigo.com"
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_PAGE_SIZE = 100

#: A hard stop for pagination. `total_results` is the normal exit; this exists so
#: a provider that keeps answering with a full page cannot loop forever.
MAX_PAGES = 100

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
AUTH_STATUS = frozenset({401, 403})


def _rfc3339(value: date, *, end_of_day: bool) -> str:
    # The API documents RFC3339 date-times. The range is inclusive on both ends,
    # so the last day must run to 23:59:59 rather than midnight.
    suffix = "T23:59:59Z" if end_of_day else "T00:00:00Z"
    return f"{value.isoformat()}{suffix}"


class SiigoClient:
    """One company's Siigo session: credentials, token, transport, retries."""

    def __init__(
        self,
        credentials: SiigoCredentials,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        page_size: int = DEFAULT_PAGE_SIZE,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        token_cache: SiigoTokenCache | None = None,
    ) -> None:
        self._credentials = credentials
        self._max_retries = max(0, max_retries)
        self._page_size = page_size
        self._sleep = sleep
        self._tokens = token_cache or SiigoTokenCache()
        self._auth_lock = asyncio.Lock()
        #: Tokens already issued to this client. A provider error can echo one
        #: sent before a refresh, and redacting only the current token would miss
        #: it. Bounded: this is a redaction list, not a token store.
        self._token_history: list[str] = []
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            transport=transport,
            headers={"Partner-Id": credentials.partner_id},
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> SiigoClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def authenticate(self) -> None:
        """Ask for a token now, regardless of what is cached."""
        response = await self._send(
            "POST",
            "/auth",
            json={
                "username": self._credentials.username,
                "access_key": self._credentials.access_key,
            },
        )
        if response.status_code >= 400:
            raise self._error_for(response.status_code, "POST /auth", response)

        try:
            payload = SiigoTokenResponse.model_validate(response.json())
        except (ValidationError, ValueError):
            # `from None` on purpose: pydantic's ValidationError embeds the input
            # body, which here contains a freshly issued access token. Chaining it
            # would print the token in any traceback.
            raise SiigoMappingError(
                "Siigo answered the authentication request with a shape this adapter cannot read."
            ) from None

        self._tokens.store(payload.access_token, expires_in=payload.expires_in)
        self._token_history.append(payload.access_token)
        del self._token_history[:-10]

    async def _token(self) -> str:
        cached = self._tokens.get()
        if cached is not None:
            return cached
        # Concurrent requests must not each buy a token. The lock is per client;
        # the double check means the second waiter reuses the first one's token.
        async with self._auth_lock:
            cached = self._tokens.get()
            if cached is None:
                await self.authenticate()
                cached = self._tokens.get()
        if cached is None:
            raise SiigoAuthError("Siigo did not issue a usable access token.")
        return cached

    async def _send(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        """One logical request, with bounded retries for transient failures.

        Shared by `/auth` and data requests on purpose: a network failure on the
        authentication call must be the same typed error as everywhere else,
        never a raw httpx exception whose `request.content` holds the access key.
        """
        attempt = 0

        while True:
            try:
                response = await self._http.request(
                    method,
                    path,
                    params=params,
                    json=json,
                    headers=headers,
                )
            except httpx.HTTPError:
                if attempt >= self._max_retries:
                    raise SiigoUnavailableError(f"{method} {path} could not reach Siigo.") from None
                await self._sleep(self._backoff(attempt))
                attempt += 1
                continue

            if response.status_code in RETRYABLE_STATUS and attempt < self._max_retries:
                await self._sleep(self._backoff(attempt))
                attempt += 1
                continue

            return response

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        refreshed = False

        while True:
            token = await self._token()
            response = await self._send(
                method,
                path,
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )

            if response.status_code in AUTH_STATUS and not refreshed:
                # The token may have been revoked or expired early. One refresh,
                # not a loop: a second rejection is a credentials problem.
                refreshed = True
                self._tokens.invalidate()
                continue

            if response.status_code >= 400:
                raise self._error_for(
                    response.status_code,
                    f"{method} {path}",
                    response,
                    used_token=token,
                )

            return response

    async def get_json(self, path: str, *, params: dict[str, Any] | None = None) -> dict:
        response = await self._request("GET", path, params=params)
        try:
            payload = response.json()
        except ValueError:
            # Never chain the decoder error: its message quotes the body.
            raise SiigoMappingError(
                f"Siigo answered {path} with a body that is not JSON."
            ) from None
        if not isinstance(payload, dict):
            raise SiigoMappingError(f"Siigo answered {path} with an unexpected JSON shape.")
        return payload

    async def list_journals(self, start_date: date, end_date: date) -> list[SiigoJournal]:
        """Every journal entry in the inclusive range, across pages.

        The provider filters by date; the range is also applied locally. That is
        not redundant paranoia: it keeps the adapter correct if the provider
        interprets `date_end` as exclusive, which is exactly the kind of silent
        off-by-one that leaves the last day of a month unreconciled.
        """
        journals: list[SiigoJournal] = []
        seen = 0
        seen_ids: set[str] = set()
        page = 1

        while page <= MAX_PAGES:
            payload = await self.get_json(
                "/v1/journals",
                params={
                    "date_start": _rfc3339(start_date, end_of_day=False),
                    "date_end": _rfc3339(end_date, end_of_day=True),
                    "page": page,
                    "page_size": self._page_size,
                },
            )
            try:
                parsed = SiigoJournalPage.model_validate(payload)
            except ValidationError:
                # Same reason as authentication: a ValidationError carries the
                # payload, and a journal item can contain sensitive free text.
                raise SiigoMappingError(
                    "Siigo returned a journal page this adapter cannot read."
                ) from None

            new_ids = {journal.id for journal in parsed.results} - seen_ids
            if parsed.results and not new_ids:
                # A provider that ignores `page` would otherwise hand us the same
                # rows MAX_PAGES times.
                break
            seen_ids.update(new_ids)

            journals.extend(
                journal for journal in parsed.results if start_date <= journal.date <= end_date
            )
            seen += len(parsed.results)

            # Terminate against the page size the provider actually applied, not
            # the one requested: a server-side cap (say 50 for a requested 100)
            # would otherwise look like a short last page and silently drop the
            # rest of the ledger.
            applied_page_size = max(1, parsed.pagination.page_size)
            if not parsed.results or len(parsed.results) < applied_page_size:
                break
            if seen >= parsed.pagination.total_results:
                break
            page += 1

        return journals

    def _error_for(
        self,
        status: int,
        operation: str,
        response: httpx.Response,
        *,
        used_token: str | None = None,
    ) -> SiigoError:
        detail = self._safe_detail(response, used_token=used_token)
        message = f"Siigo rejected {operation} with HTTP {status}"
        if detail:
            message = f"{message}: {detail}"

        if status in AUTH_STATUS:
            return SiigoAuthError(message)
        if status == 404:
            return SiigoNotFoundError(message)
        if status == 429:
            return SiigoRateLimitedError(message)
        if status >= 500:
            return SiigoUnavailableError(message)
        return SiigoRequestError(message)

    def _safe_detail(self, response: httpx.Response, *, used_token: str | None = None) -> str:
        """Extract a bounded provider message, with every secret removed.

        The response body is provider-controlled, so it is treated as untrusted:
        it is truncated and any occurrence of the credentials or of a token this
        client has used is replaced before the text reaches an exception.
        `used_token` matters because the cached token is already invalidated when
        a rejected request is being explained.
        """
        try:
            payload = response.json()
        except ValueError:
            text = response.text
        else:
            text = ""
            if isinstance(payload, dict):
                for key in ("Message", "message", "detail", "error", "Errors", "errors"):
                    value = payload.get(key)
                    if value:
                        text = str(value)
                        break
            if not text:
                text = str(payload)

        text = " ".join(text.split())
        secrets = (
            self._credentials.access_key,
            self._credentials.username,
            *self._token_history,
            self._tokens.get(),
            used_token,
        )
        for secret in secrets:
            if secret:
                text = text.replace(secret, "[redacted]")
        return text[:300]

    @staticmethod
    def _backoff(attempt: int) -> float:
        # 0.5s, 1s, 2s: bounded, and the caller can inject a no-op sleeper in
        # tests so the suite never actually waits.
        return 0.5 * (2**attempt)
