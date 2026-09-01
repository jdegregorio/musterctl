from __future__ import annotations

from pathlib import Path

import pytest

import musterctl.resources as resources_module
from musterctl.errors import EXIT_ENVIRONMENT, MusterctlError
from musterctl.resources import catalog_path


def _catalog(root: Path) -> Path:
    path = root / "musterctl" / "catalog.toml"
    path.parent.mkdir(parents=True)
    path.write_text("version = 1\n", encoding="utf-8")
    return path


def test_catalog_path_prefers_explicit_then_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    explicit = _catalog(tmp_path / "explicit")
    configured = _catalog(tmp_path / "configured")
    monkeypatch.setenv("MUSTERCTL_CATALOG", str(configured))

    assert catalog_path(explicit) == explicit.resolve()
    assert catalog_path() == configured.resolve()


def test_catalog_path_uses_xdg_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured = _catalog(tmp_path)
    monkeypatch.delenv("MUSTERCTL_CATALOG", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    assert catalog_path() == configured.resolve()


def test_catalog_path_reports_missing_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MUSTERCTL_CATALOG", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(
        resources_module,
        "__file__",
        str(tmp_path / "installed" / "musterctl" / "resources.py"),
    )

    with pytest.raises(MusterctlError) as error:
        catalog_path()

    assert error.value.code == "catalog_missing"
    assert error.value.exit_code == EXIT_ENVIRONMENT
    assert (
        error.value.fields["path"] == tmp_path / "config" / "musterctl" / "catalog.toml"
    )


def test_explicit_missing_catalog_is_structured(tmp_path: Path) -> None:
    missing = tmp_path / "missing.toml"

    with pytest.raises(MusterctlError) as error:
        catalog_path(missing)

    assert error.value.code == "catalog_missing"
    assert error.value.fields["path"] == missing
