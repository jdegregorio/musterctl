from __future__ import annotations

import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from musterctl.catalog import Catalog
from musterctl.errors import MusterctlError
from musterctl.global_lock import global_lock_path, read_global_lock, write_global_lock
from musterctl.hashing import hash_tree
from musterctl.state import global_skill_states


def test_global_lock_distinguishes_catalog_update_from_local_changes(
    catalog: Catalog, isolated_home: Path
) -> None:
    name = "musterctl"
    skill = catalog.skill(name)
    installed = isolated_home / ".agents" / "skills" / name
    installed.parent.mkdir(parents=True)
    shutil.copytree(
        Path(skill.source_url),
        installed,
        ignore=shutil.ignore_patterns(".git"),
    )
    write_global_lock(catalog, isolated_home)
    catalog.skills[name] = replace(
        skill,
        pin="f" * 40,
        source=f"{skill.source_url}@{'f' * 40}",
        content_sha256="e" * 64,
    )
    states = {item.name: item for item in global_skill_states(catalog, isolated_home)}
    assert states[name].status == "update"

    (installed / "SKILL.md").write_text("local edit\n", encoding="utf-8")
    assert hash_tree(installed) != skill.content_sha256
    states = {item.name: item for item in global_skill_states(catalog, isolated_home)}
    assert states[name].status == "drift"


def test_global_lock_uses_explicit_state_home_and_rejects_corruption(
    catalog: Catalog, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_home = tmp_path / "state"
    monkeypatch.setenv("MUSTERCTL_STATE_HOME", str(state_home))
    path = write_global_lock(catalog)
    assert path == state_home / "musterctl" / "global-lock.json"
    assert read_global_lock()["musterctl"]["source_pin"]
    path.write_text("{", encoding="utf-8")
    with pytest.raises(MusterctlError) as error:
        read_global_lock()
    assert error.value.code == "global_lock_invalid"
    monkeypatch.delenv("MUSTERCTL_STATE_HOME")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg-state"))
    assert global_lock_path() == tmp_path / "xdg-state" / "musterctl" / (
        "global-lock.json"
    )
