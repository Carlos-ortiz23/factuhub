"""The accounting provider catalogue endpoint.

This is the contract the Configuración screen will read. It exists now, before
the screen, so the interface can be built against real data instead of a list
hardcoded in a component.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

CATALOGUE = "/api/v1/accounting-providers"


def test_the_catalogue_requires_an_authenticated_user(client: TestClient) -> None:
    # Not a secret, but it is a product surface reached from a signed-in screen;
    # exposing it anonymously would be a needless thing to maintain.
    assert client.get(CATALOGUE).status_code == 401


def test_the_catalogue_lists_the_requested_providers(auth_client: TestClient) -> None:
    response = auth_client.get(CATALOGUE)

    assert response.status_code == 200
    codes = [provider["code"] for provider in response.json()["providers"]]
    assert codes == ["world_office", "siigo", "alegra"]


def test_the_catalogue_states_plainly_that_nothing_is_connectable_yet(
    auth_client: TestClient,
) -> None:
    providers = {p["code"]: p for p in auth_client.get(CATALOGUE).json()["providers"]}

    assert all(provider["connectable"] is False for provider in providers.values())
    # Siigo's contract has been reviewed, so it publishes one connection — but a
    # reviewed contract is not a working connection, and `connectable` stays
    # False until a real credential exchange is verified.
    assert [c["mode"] for c in providers["siigo"]["connections"]] == ["api"]
    assert providers["siigo"]["connections"][0]["readiness"] == "contract_reviewed"
    # Alegra still claims nothing: its contract has not been reviewed.
    assert providers["alegra"]["connections"] == []


def test_a_reviewed_connection_carries_the_evidence_that_supports_it(
    auth_client: TestClient,
) -> None:
    providers = {p["code"]: p for p in auth_client.get(CATALOGUE).json()["providers"]}
    connections = {c["mode"]: c for c in providers["world_office"]["connections"]}

    assert set(connections) == {"file_import", "api"}
    assert connections["api"]["readiness"] == "contract_reviewed"
    assert "2026-10-19" in connections["api"]["evidence"]
