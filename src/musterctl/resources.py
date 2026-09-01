"""Resolve external configuration and runtime home directories."""

from __future__ import annotations

import os
from pathlib import Path

from musterctl.errors import EXIT_ENVIRONMENT, MusterctlError


def config_catalog_path() -> Path:
    config_home = os.environ.get("XDG_CONFIG_HOME")
    base = (
        Path(config_home).expanduser().resolve()
        if config_home
        else runtime_home() / ".config"
    )
    return base / "musterctl" / "catalog.toml"


def catalog_path(explicit: Path | None = None) -> Path:
    """Resolve the external catalog without package-owned fallback policy."""

    configured = explicit
    if configured is None:
        override = os.environ.get("MUSTERCTL_CATALOG")
        if override:
            configured = Path(override)
    candidate = (
        configured.expanduser().resolve()
        if configured is not None
        else config_catalog_path()
    )
    if candidate.is_file():
        return candidate.resolve()
    raise MusterctlError(
        "catalog_missing",
        "No musterctl catalog is configured.",
        EXIT_ENVIRONMENT,
        {"path": candidate},
        (
            "run musterctl setup inspect",
            "run musterctl setup init --plan",
            "or pass --catalog <path>",
        ),
    )


def runtime_home() -> Path:
    override = os.environ.get("MUSTERCTL_HOME")
    return Path(override).expanduser().resolve() if override else Path.home()
