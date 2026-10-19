"""The Siigo adapter against a fake transport.

Nothing here touches the network. What is being tested is the contract the
adapter claims to honour: the documented authentication exchange, pagination
over `/v1/journals`, the money conversion, and — the part that matters most — that
a credential cannot escape through an exception message.

The date filters and pagination are real: they were verified in the official
documentation on 2026-10-19 (see docs/siigo-integration.md).
"""

from __future__ import annotations

import json
import traceback
from datetime import date

import httpx
import pytest

from app.integrations.base import CapabilityNotSupported
from app.integrations.siigo.auth import SiigoCredentials, SiigoTokenCache
from app.integrations.siigo.client import SiigoClient
from app.integrations.siigo.exceptions import (
    SiigoAuthError,
    SiigoMappingError,
    SiigoRequestError,
    SiigoUnavailableError,
)
from app.integrations.siigo.mapper import to_ledger_movements
from app.integrations.siigo.schemas import SiigoJournal
from app.integrations.siigo.service import SiigoConnector

pytestmark = pytest.mark.unit

USERNAME = "contador@example.com"
ACCESS_KEY = "super-secret-access-key"
TOKEN = "eyJhbGciOiJIUzI1NiJ9.demo-token"


async def _no_sleep(_: float) -> None:
    return None


def _client(
    handler: httpx.MockTransportHandler,
    *,
    token_cache: SiigoTokenCache | None = None,
    max_retries: int = 3,
    page_size: int = 100,
) -> SiigoClient:
    return SiigoClient(
        SiigoCredentials(username=USERNAME, access_key=ACCESS_KEY),
        transport=httpx.MockTransport(handler),
        sleep=_no_sleep,
        token_cache=token_cache,
        max_retries=max_retries,
        page_size=page_size,
    )


def _token_response(token: str = TOKEN, expires_in: float = 86400) -> httpx.Response:
    return httpx.Response(
        201,
        json={"access_token": token, "expires_in": expires_in, "token_type": "Bearer"},
    )


def _item(
    *,
    code: str = "11050501",
    movement: str = "Debit",
    value: float | str = 119000.50,
    description: str | None = "Pago proveedor",
) -> dict:
    return {
        "account": {"code": code, "movement": movement},
        "description": description,
        "value": value,
    }


def _journal(
    *,
    journal_id: str = "journal-1",
    name: str | None = "CC-10-20",
    posted_on: str = "2026-01-15",
    items: list[dict] | None = None,
) -> dict:
    return {
        "id": journal_id,
        "name": name,
        "date": posted_on,
        "items": items if items is not None else [_item()],
    }


def _page(
    results: list[dict],
    *,
    page: int = 1,
    page_size: int = 100,
    total_results: int | None = None,
) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total_results": total_results if total_results is not None else len(results),
            },
            "results": results,
        },
    )


async def test_authentication_sends_the_documented_exchange() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _token_response()

    async with _client(handler) as client:
        await client.authenticate()

    assert len(seen) == 1
    request = seen[0]
    assert request.method == "POST"
    assert request.url.path == "/auth"
    assert request.headers["Partner-Id"] == "FactuHub"
    assert json.loads(request.content) == {"username": USERNAME, "access_key": ACCESS_KEY}


async def test_the_token_is_cached_across_requests() -> None:
    auth_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal auth_calls
        if request.url.path == "/auth":
            auth_calls += 1
            return _token_response()
        return httpx.Response(200, json={"results": []})

    async with _client(handler) as client:
        await client.get_json("/v1/document-types")
        await client.get_json("/v1/document-types")

    assert auth_calls == 1


async def test_an_expired_token_is_replaced_before_the_next_request() -> None:
    now = 1000.0
    clock = lambda: now  # noqa: E731 - a two-line fake is clearer than a class
    tokens = SiigoTokenCache(clock=clock)
    issued: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth":
            token = f"token-{len(issued)}"
            issued.append(token)
            return _token_response(token, expires_in=120)
        return httpx.Response(200, json={})

    async with _client(handler, token_cache=tokens) as client:
        await client.get_json("/v1/document-types")
        now += 61.0  # past the 60-second safety margin, before the real deadline
        await client.get_json("/v1/document-types")

    assert issued == ["token-0", "token-1"]


async def test_a_rejected_token_is_refreshed_once_and_the_request_retried() -> None:
    auth_calls = 0
    journal_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal auth_calls, journal_calls
        if request.url.path == "/auth":
            auth_calls += 1
            return _token_response(f"token-{auth_calls}")
        journal_calls += 1
        if journal_calls == 1:
            return httpx.Response(401, json={"Message": "Token inválido"})
        return _page([_journal()])

    async with _client(handler) as client:
        journals = await client.list_journals(date(2026, 1, 1), date(2026, 1, 31))

    assert len(journals) == 1
    assert auth_calls == 2
    assert journal_calls == 2


async def test_a_rate_limited_request_is_retried_after_the_backoff() -> None:
    delays: list[float] = []
    calls = 0

    async def sleeper(delay: float) -> None:
        delays.append(delay)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        if request.url.path == "/auth":
            return _token_response()
        calls += 1
        if calls == 1:
            return httpx.Response(429, json={"Message": "Too many requests"})
        return httpx.Response(200, json={})

    client = SiigoClient(
        SiigoCredentials(username=USERNAME, access_key=ACCESS_KEY),
        transport=httpx.MockTransport(handler),
        sleep=sleeper,
    )
    async with client:
        await client.get_json("/v1/document-types")

    assert calls == 2
    assert delays == [0.5]


async def test_a_persistent_server_error_is_reported_after_the_bounded_retries() -> None:
    journal_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal journal_calls
        if request.url.path == "/auth":
            return _token_response()
        journal_calls += 1
        return httpx.Response(503, json={"Message": "Servicio no disponible"})

    async with _client(handler, max_retries=2) as client:
        with pytest.raises(SiigoUnavailableError):
            await client.get_json("/v1/journals")

    assert journal_calls == 3  # the first attempt plus two retries


async def test_a_provider_message_never_leaks_the_access_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"Message": f"credenciales inválidas: {ACCESS_KEY}"},
        )

    async with _client(handler) as client:
        with pytest.raises(SiigoAuthError) as caught:
            await client.authenticate()

    message = str(caught.value)
    assert ACCESS_KEY not in message
    assert "[redacted]" in message


async def test_a_provider_message_never_leaks_the_live_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth":
            return _token_response()
        return httpx.Response(400, json={"Message": f"token rechazado: {TOKEN}"})

    async with _client(handler, max_retries=0) as client:
        with pytest.raises(SiigoRequestError) as caught:
            await client.get_json("/v1/document-types")

    message = str(caught.value)
    assert TOKEN not in message
    assert "[redacted]" in message


async def test_journals_are_paginated_and_mapped_to_minor_units() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth":
            return _token_response()
        page = int(request.url.params["page"])
        if page == 1:
            return _page(
                [
                    _journal(journal_id="j-1", name="CC-1"),
                    _journal(
                        journal_id="j-2",
                        name="CC-2",
                        items=[_item(movement="Credit", value=50000)],
                    ),
                ],
                page=1,
                page_size=2,
                total_results=3,
            )
        return _page(
            [_journal(journal_id="j-3", name="CC-3")],
            page=2,
            page_size=2,
            total_results=3,
        )

    async with _client(handler, page_size=2) as client:
        connector = SiigoConnector(client)
        movements = await connector.fetch_ledger_transactions(
            "11050501", date(2026, 1, 1), date(2026, 1, 31)
        )

    assert [movement.journal_id for movement in movements] == ["j-1", "j-2", "j-3"]
    first = movements[0]
    assert first.external_id == "j-1:0"
    assert first.debit_minor == 11900050
    assert first.credit_minor == 0
    assert first.posted_on == date(2026, 1, 15)
    assert movements[1].debit_minor == 0
    assert movements[1].credit_minor == 5000000


async def test_the_date_range_is_sent_and_also_enforced_locally() -> None:
    seen_params: list[httpx.QueryParams] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth":
            return _token_response()
        seen_params.append(request.url.params)
        return _page(
            [
                _journal(journal_id="inside", posted_on="2026-01-31"),
                _journal(journal_id="outside", posted_on="2026-02-01"),
            ]
        )

    async with _client(handler) as client:
        journals = await client.list_journals(date(2026, 1, 1), date(2026, 1, 31))

    assert seen_params[0]["date_start"] == "2026-01-01T00:00:00Z"
    assert seen_params[0]["date_end"] == "2026-01-31T23:59:59Z"
    assert [journal.id for journal in journals] == ["inside"]


async def test_only_the_requested_account_code_is_returned() -> None:
    journal = _journal(
        items=[
            _item(code="11050501", movement="Debit", value=1000),
            _item(code="11050502", movement="Credit", value=1000),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth":
            return _token_response()
        return _page([journal])

    async with _client(handler) as client:
        connector = SiigoConnector(client)
        movements = await connector.fetch_ledger_transactions(
            "11050501", date(2026, 1, 1), date(2026, 1, 31)
        )

    assert len(movements) == 1
    assert movements[0].account_code == "11050501"
    assert movements[0].external_id == "journal-1:0"


async def test_an_unknown_movement_is_an_error_not_a_skipped_row() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth":
            return _token_response()
        return _page([_journal(items=[_item(movement="Sideways")])])

    async with _client(handler) as client:
        connector = SiigoConnector(client)
        with pytest.raises(SiigoMappingError, match="unknown movement"):
            await connector.fetch_ledger_transactions(
                "11050501", date(2026, 1, 1), date(2026, 1, 31)
            )


async def test_a_negative_value_is_refused() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth":
            return _token_response()
        return _page([_journal(items=[_item(value=-1000)])])

    async with _client(handler) as client:
        connector = SiigoConnector(client)
        with pytest.raises(SiigoMappingError, match="negative value"):
            await connector.fetch_ledger_transactions(
                "11050501", date(2026, 1, 1), date(2026, 1, 31)
            )


async def test_an_unreadable_journal_page_is_reported_as_a_mapping_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth":
            return _token_response()
        return httpx.Response(200, json={"results": [{"id": "no-date"}]})

    async with _client(handler) as client:
        with pytest.raises(SiigoMappingError):
            await client.list_journals(date(2026, 1, 1), date(2026, 1, 31))


async def test_bank_accounts_are_declared_unsupported_instead_of_empty() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _token_response()

    async with _client(handler) as client:
        connector = SiigoConnector(client)

        assert connector.capabilities.ledger_transactions is True
        assert connector.capabilities.bank_accounts is False
        with pytest.raises(CapabilityNotSupported, match="no bank-accounts resource"):
            await connector.list_bank_accounts()


async def test_the_connection_check_reports_failure_without_raising() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth":
            return _token_response()
        return httpx.Response(401, json={"Message": "Token inválido"})

    async with _client(handler, max_retries=0) as client:
        connector = SiigoConnector(client)
        assert await connector.test_connection() is False


async def test_the_connection_check_succeeds_on_an_authenticated_read() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/auth":
            return _token_response()
        return httpx.Response(200, json={"results": []})

    async with _client(handler) as client:
        connector = SiigoConnector(client)
        assert await connector.test_connection() is True

    assert paths == ["/auth", "/v1/document-types"]


def test_the_mapper_uses_the_journal_name_when_the_item_has_no_description() -> None:
    journal = _journal(items=[_item(description=None)])

    movements = to_ledger_movements(SiigoJournal.model_validate(journal))

    assert movements[0].description == "CC-10-20"
    assert movements[0].reference == "CC-10-20"


# --- Verifier-driven regressions -------------------------------------------------
# Each of these exists because the first implementation got it wrong and an
# independent review proved it with a probe.


async def test_a_token_in_a_malformed_auth_response_cannot_reach_a_traceback() -> None:
    short_token = "short-secret-token"

    def handler(request: httpx.Request) -> httpx.Response:
        # `expires_in` is missing, so validation fails with the body as input.
        return httpx.Response(201, json={"access_token": short_token})

    async with _client(handler) as client:
        with pytest.raises(SiigoMappingError) as caught:
            await client.authenticate()

    rendered = "".join(traceback.format_exception(caught.value))
    assert short_token not in rendered


async def test_a_token_used_before_a_refresh_is_redacted_from_later_errors() -> None:
    issued: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth":
            token = "eyJ.TOKEN-ZERO" if not issued else "eyJ.TOKEN-ONE"
            issued.append(token)
            return _token_response(token)
        sent = request.headers["Authorization"].split(" ", 1)[1]
        if sent == "eyJ.TOKEN-ZERO":
            return httpx.Response(401, json={"Message": "Token inválido"})
        return httpx.Response(401, json={"Message": "token anterior: eyJ.TOKEN-ZERO"})

    async with _client(handler, max_retries=0) as client:
        with pytest.raises(SiigoAuthError) as caught:
            await client.get_json("/v1/journals")

    message = str(caught.value)
    assert "eyJ.TOKEN-ZERO" not in message
    assert "[redacted]" in message


async def test_the_username_is_redacted_from_provider_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"Message": f"usuario {USERNAME} no autorizado"})

    async with _client(handler) as client:
        with pytest.raises(SiigoAuthError) as caught:
            await client.authenticate()

    assert USERNAME not in str(caught.value)


async def test_a_network_failure_during_authentication_is_a_typed_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("network down")

    async with _client(handler, max_retries=2) as client:
        with pytest.raises(SiigoUnavailableError):
            await client.get_json("/v1/journals")


async def test_the_connection_check_returns_false_when_the_network_is_down() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("network down")

    async with _client(handler, max_retries=0) as client:
        assert await SiigoConnector(client).test_connection() is False


async def test_authentication_failures_are_retried_a_bounded_number_of_times() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, json={"Message": "down"})

    async with _client(handler, max_retries=2) as client:
        with pytest.raises(SiigoUnavailableError):
            await client.get_json("/v1/journals")

    assert calls == 3  # the first attempt plus two retries


async def test_a_second_rejection_does_not_buy_another_token() -> None:
    api_calls = 0
    auth_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal api_calls, auth_calls
        if request.url.path == "/auth":
            auth_calls += 1
            return _token_response()
        api_calls += 1
        return httpx.Response(401, json={"Message": "no"})

    async with _client(handler, max_retries=0) as client:
        with pytest.raises(SiigoAuthError):
            await client.get_json("/v1/journals")

    assert (api_calls, auth_calls) == (2, 2)


async def test_a_client_error_is_not_retried() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        if request.url.path == "/auth":
            return _token_response()
        calls += 1
        return httpx.Response(400, json={"Message": "bad request"})

    async with _client(handler, max_retries=3) as client:
        with pytest.raises(SiigoRequestError):
            await client.get_json("/v1/journals")

    assert calls == 1


async def test_a_server_capped_page_size_does_not_truncate_the_ledger() -> None:
    pages: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth":
            return _token_response()
        page = int(request.url.params["page"])
        pages.append(page)
        start = (page - 1) * 50
        return httpx.Response(
            200,
            json={
                "pagination": {"page": page, "page_size": 50, "total_results": 100},
                "results": [
                    {"id": f"j{index}", "date": "2026-01-15", "items": []}
                    for index in range(start, start + 50)
                ],
            },
        )

    async with _client(handler, page_size=100) as client:
        journals = await client.list_journals(date(2026, 1, 1), date(2026, 1, 31))

    assert len(journals) == 100
    assert pages == [1, 2]


async def test_a_provider_that_ignores_the_page_parameter_terminates() -> None:
    pages: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth":
            return _token_response()
        pages.append(int(request.url.params["page"]))
        return _page(
            [_journal(journal_id="same", posted_on="2026-01-15")],
            page_size=1,
            total_results=5,
        )

    async with _client(handler, page_size=1) as client:
        journals = await client.list_journals(date(2026, 1, 1), date(2026, 1, 31))

    assert [journal.id for journal in journals] == ["same"]
    assert pages == [1, 2]


@pytest.mark.parametrize(
    ("value", "minor"),
    [("10.005", 1001), ("2.675", 268), ("0.005", 1)],
)
def test_half_cent_values_round_half_up(value: str, minor: int) -> None:
    journal = SiigoJournal.model_validate(
        {
            "id": "J",
            "name": "N",
            "date": "2026-01-15",
            "items": [
                {
                    "account": {"code": "11050501", "movement": "Debit"},
                    "value": value,
                }
            ],
        }
    )

    assert to_ledger_movements(journal)[0].debit_minor == minor
