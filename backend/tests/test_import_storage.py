"""The private local adapter for original files."""

from __future__ import annotations

import stat

import pytest

from app.imports.storage import ImportStorageError, LocalImportStorage


def test_a_file_round_trips_and_is_owner_only(tmp_path) -> None:
    storage = LocalImportStorage(tmp_path / "imports")

    storage.save("organization/job.csv", b"Fecha;Valor\n01/02/2026;1\n")

    assert storage.read("organization/job.csv").startswith(b"Fecha")
    path = tmp_path / "imports" / "organization" / "job.csv"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_a_key_cannot_escape_the_storage_root(tmp_path) -> None:
    storage = LocalImportStorage(tmp_path / "imports")

    with pytest.raises(ImportStorageError):
        storage.save("../outside.csv", b"data")


def test_a_missing_file_is_a_controlled_error(tmp_path) -> None:
    storage = LocalImportStorage(tmp_path / "imports")

    with pytest.raises(ImportStorageError):
        storage.read("organization/missing.csv")
