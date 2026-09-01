from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from musterctl.errors import EXIT_CONFLICT, MusterctlError
from musterctl.setup import (
    inspect_installed_skills,
    render_initial_catalog,
    select_installed_skills,
    write_initial_catalog,
)


def _installed(home: Path, name: str) -> Path:
    skill = home / ".agents" / "skills" / name
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {name} description\n---\n",
        encoding="utf-8",
    )
    return skill


def _lock(home: Path, name: str) -> None:
    path = home / ".agents" / ".skill-lock.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": 3,
                "skills": {
                    name: {
                        "source": "owner/repo",
                        "sourceType": "github",
                        "sourceUrl": "https://github.com/owner/repo.git",
                        "skillPath": f"skills/{name}/SKILL.md",
                        "skillFolderHash": "abc123",
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def test_inspect_distinguishes_tracked_untracked_and_adapters(tmp_path: Path) -> None:
    home = tmp_path / "home"
    tracked = _installed(home, "tracked")
    _lock(home, "tracked")
    _installed(home, "local")
    adapter = home / ".codex" / "skills" / "tracked"
    adapter.parent.mkdir(parents=True)
    adapter.symlink_to(tracked, target_is_directory=True)
    candidates = inspect_installed_skills(home)
    assert [(item.name, item.lineage) for item in candidates] == [
        ("tracked", "tracked"),
        ("local", "untracked"),
    ]
    assert candidates[0].source_path == "skills/tracked"
    assert len(candidates[0].content_sha256 or "") == 64


def test_selection_and_catalog_render_are_deterministic(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _installed(home, "tracked")
    _lock(home, "tracked")
    candidates = inspect_installed_skills(home)
    selected = select_installed_skills(candidates, [], True)
    content = render_initial_catalog(selected)
    parsed = tomllib.loads(content)
    assert parsed["profiles"]["global"]["skills"] == ["tracked"]
    assert parsed["skills"]["tracked"]["source"] == "owner/repo"
    assert parsed["skills"]["tracked"]["ownership"] == "imported"
    assert render_initial_catalog(selected) == content


def test_selection_rejects_unknown_and_untracked(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _installed(home, "local")
    candidates = inspect_installed_skills(home)
    with pytest.raises(MusterctlError) as unknown:
        select_installed_skills(candidates, ["missing"], False)
    assert unknown.value.code == "unknown_installed_skill"
    with pytest.raises(MusterctlError) as untracked:
        select_installed_skills(candidates, ["local"], False)
    assert untracked.value.code == "source_lineage_missing"


def test_write_initial_catalog_refuses_overwrite(tmp_path: Path) -> None:
    destination = tmp_path / "config" / "catalog.toml"
    written = write_initial_catalog(render_initial_catalog([]), destination)
    assert written == destination.resolve()
    assert tomllib.loads(written.read_text(encoding="utf-8"))["version"] == 1
    with pytest.raises(MusterctlError) as error:
        write_initial_catalog(render_initial_catalog([]), destination)
    assert error.value.code == "catalog_exists"
    assert error.value.exit_code == EXIT_CONFLICT


def test_invalid_skills_lock_is_structured(tmp_path: Path) -> None:
    home = tmp_path / "home"
    path = home / ".agents" / ".skill-lock.json"
    path.parent.mkdir(parents=True)
    path.write_text("{", encoding="utf-8")
    with pytest.raises(MusterctlError) as error:
        inspect_installed_skills(home)
    assert error.value.code == "skills_lock_invalid"
