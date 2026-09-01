from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from musterctl.catalog import Catalog
from musterctl.errors import EXIT_ENVIRONMENT, MusterctlError
from musterctl.hashing import hash_tree
from musterctl.state import (
    SKILLS_CLI_PACKAGE,
    SkillsManager,
    find_project_root,
    global_skill_states,
    project_skill_states,
    skill_diff,
)


def _install(catalog: Catalog, home: Path, name: str) -> Path:
    target = home / ".agents" / "skills" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        Path(catalog.skill(name).source_url),
        target,
        ignore=shutil.ignore_patterns(".git"),
    )
    return target


def _write_lock(project: Path, catalog: Catalog, name: str) -> None:
    entry = catalog.skills[name]
    installed = project / ".agents" / "skills" / name
    payload = {
        "version": 1,
        "skills": {
            name: {
                "content_sha256": hash_tree(installed),
                "update_policy": entry.update_policy,
            }
        },
    }
    (project / "skills-lock.json").write_text(json.dumps(payload), encoding="utf-8")


def test_global_status_moves_from_missing_to_current_to_drift(
    catalog: Catalog, isolated_home: Path
) -> None:
    states = {
        state.name: state for state in global_skill_states(catalog, isolated_home)
    }
    assert states["musterctl"].status == "missing"
    installed = _install(catalog, isolated_home, "musterctl")
    states = {
        state.name: state for state in global_skill_states(catalog, isolated_home)
    }
    assert states["musterctl"].status == "current"
    (installed / "SKILL.md").write_text("drift", encoding="utf-8")
    states = {
        state.name: state for state in global_skill_states(catalog, isolated_home)
    }
    assert states["musterctl"].status == "drift"


def test_global_status_deduplicates_adapters_and_reports_unmanaged(
    catalog: Catalog, isolated_home: Path
) -> None:
    canonical = _install(catalog, isolated_home, "musterctl")
    adapter = isolated_home / ".codex" / "skills" / "musterctl"
    adapter.parent.mkdir(parents=True)
    adapter.symlink_to(canonical, target_is_directory=True)
    unmanaged = isolated_home / ".agents" / "skills" / "local-helper"
    unmanaged.mkdir()
    (unmanaged / "SKILL.md").write_text("# Local\n", encoding="utf-8")
    states = {
        state.name: state for state in global_skill_states(catalog, isolated_home)
    }
    assert states["musterctl"].paths == (canonical,)
    assert states["local-helper"].status == "unmanaged"


def test_global_prune_is_explicit_and_never_selects_managed_skills(
    catalog: Catalog, isolated_home: Path
) -> None:
    unmanaged = isolated_home / ".agents" / "skills" / "local-helper"
    unmanaged.mkdir(parents=True)
    (unmanaged / "SKILL.md").write_text("# Local\n", encoding="utf-8")
    adapter = isolated_home / ".codex" / "skills" / "local-helper"
    adapter.parent.mkdir(parents=True)
    adapter.symlink_to(unmanaged, target_is_directory=True)
    manager = SkillsManager(catalog, isolated_home)
    actions = manager.plan_prune(("local-helper",))
    assert actions[0].paths == (unmanaged, adapter)
    manager.apply_prune(actions)
    assert not unmanaged.exists()
    assert not adapter.exists()
    with pytest.raises(MusterctlError) as error:
        manager.plan_prune(("musterctl",))
    assert error.value.code == "managed_skill_prune_blocked"


def test_global_roots_and_skill_links_cannot_escape_home(
    catalog: Catalog, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "SKILL.md").write_text("# Outside\n", encoding="utf-8")
    agents = home / ".agents"
    agents.mkdir(parents=True)
    (agents / "skills").symlink_to(outside, target_is_directory=True)
    with pytest.raises(MusterctlError) as root_error:
        global_skill_states(catalog, home)
    assert root_error.value.code == "global_skill_root_invalid"
    (agents / "skills").unlink()
    skill_root = agents / "skills"
    skill_root.mkdir()
    (skill_root / "musterctl").symlink_to(outside, target_is_directory=True)
    with pytest.raises(MusterctlError) as path_error:
        global_skill_states(catalog, home)
    assert path_error.value.code == "global_skill_path_invalid"


def test_unverified_skill_state(catalog: Catalog, isolated_home: Path) -> None:
    skill = catalog.skill("musterctl")
    catalog.skills["musterctl"] = replace(skill, content_sha256=None)
    _install(catalog, isolated_home, "musterctl")
    states = {
        state.name: state for state in global_skill_states(catalog, isolated_home)
    }
    assert states["musterctl"].status == "unverified"


def test_project_states_cover_lifecycle(
    project_catalog: Catalog, tmp_path: Path
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    installed = project / ".agents" / "skills" / "project-helper"
    installed.parent.mkdir(parents=True)
    shutil.copytree(
        Path(project_catalog.skill("project-helper").source_url),
        installed,
        ignore=shutil.ignore_patterns(".git"),
    )
    _write_lock(project, project_catalog, "project-helper")
    assert project_skill_states(project_catalog, project)[0].status == "current"
    unmanaged = installed.parent / "local-helper"
    unmanaged.mkdir()
    (unmanaged / "SKILL.md").write_text("# Local\n", encoding="utf-8")
    states = {
        item.name: item for item in project_skill_states(project_catalog, project)
    }
    assert states["local-helper"].status == "unmanaged"
    shutil.rmtree(unmanaged)
    (installed / "SKILL.md").write_text("changed", encoding="utf-8")
    assert project_skill_states(project_catalog, project)[0].status == "drift"
    shutil.rmtree(installed)
    assert project_skill_states(project_catalog, project)[0].status == "missing"


def test_project_state_reports_catalog_update(
    project_catalog: Catalog, tmp_path: Path
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    installed = project / ".agents" / "skills" / "project-helper"
    installed.parent.mkdir(parents=True)
    shutil.copytree(
        Path(project_catalog.skill("project-helper").source_url),
        installed,
        ignore=shutil.ignore_patterns(".git"),
    )
    _write_lock(project, project_catalog, "project-helper")
    configured = project_catalog.skill("project-helper")
    project_catalog.skills["project-helper"] = replace(
        configured, update_policy="latest", content_sha256="f" * 64
    )
    payload = json.loads((project / "skills-lock.json").read_text(encoding="utf-8"))
    payload["skills"]["project-helper"]["update_policy"] = "latest"
    (project / "skills-lock.json").write_text(json.dumps(payload), encoding="utf-8")
    assert project_skill_states(project_catalog, project)[0].status == "update"


@pytest.mark.parametrize("payload", ["{", '{"skills": []}', '{"skills": {"x": 1}}'])
def test_invalid_project_locks_are_structured(
    catalog: Catalog, tmp_path: Path, payload: str
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "skills-lock.json").write_text(payload, encoding="utf-8")
    with pytest.raises(MusterctlError) as error:
        project_skill_states(catalog, project)
    assert error.value.code == "project_lock_invalid"
    assert error.value.exit_code == EXIT_ENVIRONMENT


def test_find_project_root_recognizes_git_and_lock(tmp_path: Path) -> None:
    project = tmp_path / "project"
    nested = project / "a" / "b"
    nested.mkdir(parents=True)
    (project / ".git").mkdir()
    assert find_project_root(nested) == project
    shutil.rmtree(project / ".git")
    (project / "skills-lock.json").write_text('{"skills": {}}', encoding="utf-8")
    assert find_project_root(nested) == project
    assert find_project_root(tmp_path / "outside.txt") is None


def test_skills_manager_plan_is_pinned_and_noninteractive(
    catalog: Catalog, isolated_home: Path
) -> None:
    actions = SkillsManager(catalog, isolated_home).plan()
    assert len(actions) == 3
    action = next(item for item in actions if item.skill.name == "gh-axi")
    assert action.skill.pin
    assert action.command[4] == "<verified-source>"
    assert action.command[2] == SKILLS_CLI_PACKAGE
    assert "--yes" in action.command
    assert "--global" in action.command
    assert action.command.count("--agent") == 2


def test_skills_manager_applies_and_verifies(
    catalog: Catalog, isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = SkillsManager(catalog, isolated_home)
    observed_homes: list[str] = []

    def fake_install(
        command: tuple[str, ...],
        cwd: Path | None = None,
        home: Path | None = None,
    ) -> None:
        name = command[command.index("--skill") + 1]
        _install(catalog, isolated_home, name)
        assert cwd is None
        assert home is not None
        observed_homes.append(str(home))

    monkeypatch.setattr(
        "musterctl.state.SkillsManager.run_install", staticmethod(fake_install)
    )
    manager.apply(manager.plan())
    assert all(state.status in {"current", "unmanaged"} for state in manager.statuses())
    assert observed_homes and set(observed_homes) == {str(isolated_home)}


def test_run_install_is_noninteractive_and_uses_selected_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed: dict[str, object] = {}

    def fake_run(
        command: tuple[str, ...], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        observed.update(kwargs)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("musterctl.state.subprocess.run", fake_run)
    SkillsManager.run_install(("installer",), home=tmp_path)
    assert observed["stdin"] is subprocess.DEVNULL
    environment = observed["env"]
    assert isinstance(environment, dict)
    assert environment["HOME"] == str(tmp_path)


def test_skills_manager_rejects_source_drift_before_install(
    catalog: Catalog, isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = SkillsManager(catalog, isolated_home)
    skill = catalog.skill("musterctl")
    catalog.skills["musterctl"] = replace(skill, content_sha256="f" * 64)
    invoked = False

    def fake_run(*_args: object, **_kwargs: object) -> None:
        nonlocal invoked
        invoked = True

    monkeypatch.setattr(manager, "run_install", fake_run)
    with pytest.raises(MusterctlError) as error:
        manager.install_verified(catalog.skill("musterctl"), global_scope=True)
    assert error.value.code == "source_digest_mismatch"
    assert invoked is False


def test_skills_manager_failures(
    catalog: Catalog, isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = SkillsManager(catalog, isolated_home)
    monkeypatch.setattr(
        "musterctl.state.subprocess.run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess((), 9, "", "bad"),
    )
    with pytest.raises(MusterctlError) as failed:
        manager.run_install(("installer",))
    assert failed.value.code == "skill_sync_failed"

    def unavailable(*_args: object, **_kwargs: object) -> None:
        raise OSError("missing")

    monkeypatch.setattr("musterctl.state.subprocess.run", unavailable)
    with pytest.raises(MusterctlError) as missing:
        manager.run_install(("installer",))
    assert missing.value.code == "skills_cli_unavailable"
    monkeypatch.setattr(manager, "install_verified", lambda *_args, **_kwargs: None)
    with pytest.raises(MusterctlError) as incomplete:
        manager.apply(manager.plan())
    assert incomplete.value.code == "skill_sync_incomplete"


def test_skill_diff_fetches_exact_source(catalog: Catalog, tmp_path: Path) -> None:
    installed = tmp_path / "musterctl"
    shutil.copytree(
        Path(catalog.skill("musterctl").source_url),
        installed,
        ignore=shutil.ignore_patterns(".git"),
    )
    assert skill_diff(catalog, "musterctl", installed) == ([], False)
    (installed / "SKILL.md").write_text("changed\n", encoding="utf-8")
    (installed / "extra.txt").write_text("extra", encoding="utf-8")
    lines, truncated = skill_diff(catalog, "musterctl", installed)
    assert any(line.startswith("--- source/SKILL.md") for line in lines)
    assert "only_installed extra.txt" in lines
    assert truncated is False
