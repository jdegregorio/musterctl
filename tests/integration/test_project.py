from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import musterctl.project as project_module
from musterctl.catalog import Catalog
from musterctl.errors import EXIT_CONFLICT, EXIT_ENVIRONMENT, MusterctlError
from musterctl.project import ProjectInitializer


@pytest.mark.parametrize("name", ["", ".", "..", "has/slash", " space"])
def test_plan_rejects_unsafe_project_names(
    catalog: Catalog, tmp_path: Path, name: str
) -> None:
    with pytest.raises(MusterctlError) as error:
        ProjectInitializer(catalog).plan(name, "base", [], False, tmp_path)
    assert error.value.code == "invalid_project_name"


def test_plan_is_non_mutating_and_defaults_are_explicit(
    project_catalog: Catalog, tmp_path: Path
) -> None:
    plan = ProjectInitializer(project_catalog).plan(
        "example", "python-cli", [], True, tmp_path
    )
    assert not plan.destination.exists()
    assert [skill.name for skill in plan.skills] == ["project-helper"]
    assert "install 1 project skills" in plan.actions


def test_plan_rejects_conflicts(catalog: Catalog, tmp_path: Path) -> None:
    initializer = ProjectInitializer(catalog)
    with pytest.raises(MusterctlError) as parent_error:
        initializer.plan("example", "base", [], False, tmp_path / "missing")
    assert parent_error.value.code == "parent_missing"
    destination = tmp_path / "example"
    destination.mkdir()
    with pytest.raises(MusterctlError) as destination_error:
        initializer.plan("example", "base", [], False, tmp_path)
    assert destination_error.value.exit_code == EXIT_CONFLICT
    destination.rmdir()
    with pytest.raises(MusterctlError) as global_error:
        initializer.plan("example", "base", ["musterctl"], False, tmp_path)
    assert global_error.value.code == "skill_already_global"


def _fake_skill_install(catalog: Catalog, command: tuple[str, ...], cwd: Path) -> None:
    name = command[command.index("--skill") + 1]
    canonical = cwd / ".agents" / "skills" / name
    canonical.parent.mkdir(parents=True)
    shutil.copytree(
        Path(catalog.skill(name).source_url),
        canonical,
        ignore=shutil.ignore_patterns(".git"),
    )
    adapter = cwd / ".claude" / "skills" / name
    adapter.parent.mkdir(parents=True)
    adapter.symlink_to(Path("../../.agents/skills") / name, target_is_directory=True)


def test_python_project_journey_materializes_valid_repo_and_skill(
    project_catalog: Catalog,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "musterctl.state.SkillsManager.run_install",
        staticmethod(
            lambda command, cwd=None: _fake_skill_install(
                project_catalog, command, cwd or tmp_path
            )
        ),
    )
    initializer = ProjectInitializer(project_catalog)
    plan = initializer.plan(
        "demo-cli",
        "python-cli",
        ["project-helper", "project-helper"],
        False,
        tmp_path,
    )
    initializer.apply(plan)
    project = tmp_path / "demo-cli"
    assert (project / ".git").is_dir()
    assert (project / "src" / "demo_cli" / "cli.py").is_file()
    assert "{{PROJECT_NAME}}" not in (project / "README.md").read_text(encoding="utf-8")
    lock = json.loads((project / "skills-lock.json").read_text(encoding="utf-8"))
    assert list(lock["skills"]) == ["project-helper"]
    canonical = project / ".agents" / "skills" / "project-helper"
    adapter = project / ".claude" / "skills" / "project-helper"
    assert (canonical / "SKILL.md").is_file()
    assert adapter.resolve() == canonical.resolve()
    assert not list(tmp_path.glob(".demo-cli.musterctl-*"))


def test_failed_validation_cleans_temporary_tree(
    catalog: Catalog, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    initializer = ProjectInitializer(catalog)
    original_run = initializer._run

    def fail_check(command: tuple[str, ...], cwd: Path, error_code: str) -> None:
        if error_code == "project_validation_failed":
            raise MusterctlError(
                "project_validation_failed", "failed", EXIT_ENVIRONMENT
            )
        original_run(command, cwd, error_code)

    monkeypatch.setattr(initializer, "_run", fail_check)
    plan = initializer.plan("broken", "base", [], False, tmp_path)
    with pytest.raises(MusterctlError) as error:
        initializer.apply(plan)
    assert error.value.code == "project_validation_failed"
    assert not plan.destination.exists()
    assert not list(tmp_path.glob(".broken.musterctl-*"))


def test_concurrent_destination_is_not_overwritten(
    catalog: Catalog, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    initializer = ProjectInitializer(catalog)
    plan = initializer.plan("race", "base", [], False, tmp_path)
    original_publish = project_module._publish_noreplace

    def publish_after_destination(source: Path, destination: Path) -> None:
        destination.mkdir()
        original_publish(source, destination)

    monkeypatch.setattr(project_module, "_publish_noreplace", publish_after_destination)
    with pytest.raises(MusterctlError) as error:
        initializer.apply(plan)
    assert error.value.code == "destination_exists"
    assert list(plan.destination.iterdir()) == []
    assert not list(tmp_path.glob(".race.musterctl-*"))


def test_interruption_removes_temporary_project(
    catalog: Catalog, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    initializer = ProjectInitializer(catalog)
    plan = initializer.plan("interrupted", "base", [], False, tmp_path)

    def interrupt(_command: tuple[str, ...], _cwd: Path, _error_code: str) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(initializer, "_run", interrupt)
    with pytest.raises(KeyboardInterrupt):
        initializer.apply(plan)
    assert not plan.destination.exists()
    assert not list(tmp_path.glob(".interrupted.musterctl-*"))


def test_project_name_with_dot_produces_valid_quoted_script_key(
    catalog: Catalog, tmp_path: Path
) -> None:
    initializer = ProjectInitializer(catalog)
    plan = initializer.plan("demo.tool", "python-cli", [], False, tmp_path)
    initializer.apply(plan)
    pyproject = (plan.destination / "pyproject.toml").read_text(encoding="utf-8")
    assert '"demo.tool" = "demo_tool.cli:main"' in pyproject
