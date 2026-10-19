"""Service identity and version, resolved from installed distribution metadata."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

SERVICE_NAME = "factuhub-backend"
DISTRIBUTION_NAME = "factuhub-backend"
_FALLBACK_VERSION = "0.0.0"


def get_app_version() -> str:
    """Return the installed package version, or a safe fallback in editable runs."""
    try:
        return version(DISTRIBUTION_NAME)
    except PackageNotFoundError:  # pragma: no cover - only when running uninstalled
        return _FALLBACK_VERSION
