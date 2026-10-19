"""Private storage for the original import files.

The files are financial data and are never served by an API route. The local
adapter writes under a configured directory with owner-only permissions and an
atomic replace; the S3-compatible adapter belongs to the deployment phase and
implements the same two methods.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol


class ImportStorageError(RuntimeError):
    """The stored file cannot be written or read."""


class ImportStorage(Protocol):
    """The seam the deployment phase replaces with an S3 adapter."""

    def save(self, key: str, data: bytes) -> None: ...

    def read(self, key: str) -> bytes: ...


class LocalImportStorage:
    """Files under a private directory, never reachable through the API."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def _resolve(self, key: str) -> Path:
        root = self._root.resolve()
        path = (root / key).resolve()
        if path != root and root not in path.parents:
            raise ImportStorageError("Invalid storage key.")
        return path

    def save(self, key: str, data: bytes) -> None:
        path = self._resolve(key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            temporary = path.with_name(f".{path.name}.tmp")
            with temporary.open("wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
        except OSError as exc:
            raise ImportStorageError("The file could not be stored.") from exc

    def read(self, key: str) -> bytes:
        path = self._resolve(key)
        try:
            return path.read_bytes()
        except OSError as exc:
            raise ImportStorageError("The stored file is no longer available.") from exc
