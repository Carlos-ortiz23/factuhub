"""The rules that keep the provider catalogue honest.

These tests do not check that the catalogue is *correct* — that is a matter of
reviewing real contracts. They check that it cannot overstate what has been
verified, and that the providers the client named are actually present.
"""

from __future__ import annotations

import pytest

from app.integrations import registry
from app.integrations.registry import (
    CATALOGUE,
    AccountingProvider,
    ConnectionMode,
    ProviderConnection,
    Readiness,
    get_provider,
)

pytestmark = pytest.mark.unit


def test_a_reviewed_connection_must_name_its_evidence() -> None:
    with pytest.raises(ValueError, match="without evidence"):
        ProviderConnection(mode=ConnectionMode.API, readiness=Readiness.CONTRACT_REVIEWED)


def test_an_implemented_connection_must_name_its_evidence_too() -> None:
    with pytest.raises(ValueError, match="without evidence"):
        ProviderConnection(mode=ConnectionMode.API, readiness=Readiness.IMPLEMENTED)


def test_a_connection_nothing_was_checked_on_needs_no_evidence() -> None:
    connection = ProviderConnection(mode=ConnectionMode.API, readiness=Readiness.NOT_STARTED)

    assert connection.evidence is None


def test_every_provider_code_is_unique_and_url_safe() -> None:
    codes = [provider.code for provider in CATALOGUE]

    assert len(codes) == len(set(codes))
    assert all(code.islower() and code.replace("_", "").isalnum() for code in codes)


def test_the_providers_the_client_named_are_in_the_catalogue() -> None:
    # The requirement was explicit: Siigo, World Office, "allegra etc... las que
    # existen en colombia y mas usadas". A missing one is a missing requirement.
    assert {provider.code for provider in CATALOGUE} >= {"world_office", "siigo", "allegra"}
    assert get_provider("allegra").display_name == "Allegra"


def test_world_office_declares_the_two_modes_that_were_actually_reviewed() -> None:
    modes = {connection.mode for connection in registry.WORLD_OFFICE.connections}

    assert modes == {ConnectionMode.FILE_IMPORT, ConnectionMode.API}


def test_a_provider_nothing_was_verified_for_is_not_connectable() -> None:
    provider = AccountingProvider(code="invented", display_name="Invented")

    assert provider.is_connectable is False
    assert get_provider("invented") is None


def test_no_provider_claims_a_working_connection_yet() -> None:
    # True today: the integration phase has not started. When it does, this test
    # fails on purpose, forcing whoever implements it to update the claim and the
    # documentation in the same commit instead of quietly editing a status.
    assert all(provider.is_connectable is False for provider in CATALOGUE)
