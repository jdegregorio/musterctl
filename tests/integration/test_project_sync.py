from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from musterctl.catalog import Catalog
from musterctl.errors import MusterctlError
from musterctl.handlers import projects_status, projects_sync
from musterctl.hashing import hash_tree
from musterctl.project_sync import ProjectSkillsManager
from musterctl.sources import source_selector


def _commit_change(source: Path) -> tuple[str, str]:
    (source / "SKILL.md").write_text("# Project helper v2\n", encoding="utf-8")
    subprocess.run(("git", "add", "."), cwd=source, check=True)
    subprocess.run(
        (
            "git",
            "-c",
            "user.name=Tests",
            "-c",
            "user.email=tests@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "v2",
        ),
        cwd=source,
        check=True,
    )
    revision = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=source,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return revision, hash_tree(source)


def _project(catalog: Catalog, path: Path, *, failing_check: bool = False) -> Path:
    path.mkdir()
    name = "project-helper"
    skill = catalog.skill(name)
    canonical = path / ".agents" / "skills" / name
    canonical.parent.mkdir(parents=True)
    shutil.copytree(
        Path(skill.source_url),
        canonical,
        ignore=shutil.ignore_patterns(".git"),
    )
    adapters = [f".codex/skills/{name}", f".claude/skills/{name}"]
    for relative in adapters:
        target = path / relative
        target.parent.mkdir(parents=True)
        shutil.copytree(canonical, target)
    lock = {
        "skills": {
            name: {
                "adapters": adapters,
                "content_sha256": skill.content_sha256,
                "path": f".agents/skills/{name}",
                "source": skill.source,
                "source_path": skill.source_path,
                "source_pin": skill.pin,
                "source_ref": skill.source_ref,
                "source_skill": skill.source_skill,
                "source_url": skill.source_url,
                "update_policy": skill.update_policy,
            }
        },
        "version": 1,
    }
    (path / "skills-lock.json").write_text(json.dumps(lock), encoding="utf-8")
    scripts = path / "scripts"
    scripts.mkdir()
    check = scripts / "check"
    check.write_text(
        "#!/bin/sh\nexit 1\n" if failing_check else "#!/bin/sh\nexit 0\n",
        encoding="utf-8",
    )
    check.chmod(0o755)
    return canonical


def _advance_catalog(catalog: Catalog) -> None:
    old = catalog.skill("project-helper")
    revision, digest = _commit_change(Path(old.source_url))
    catalog.skills[old.name] = replace(
        old,
        pin=revision,
        source=source_selector(old.source_url, revision, old.source_path),
        content_sha256=digest,
    )


def test_project_sync_advances_canonical_adapters_and_lock(
    project_catalog: Catalog, tmp_path: Path
) -> None:
    project = tmp_path / "project"
    canonical = _project(project_catalog, project)
    old_hash = hash_tree(canonical)
    _advance_catalog(project_catalog)
    manager = ProjectSkillsManager(project_catalog, (project,))
    actions = manager.plan()
    assert [(action.name, action.operation) for action in actions] == [
        ("project-helper", "replace")
    ]
    manager.apply(actions)
    expected = project_catalog.skill("project-helper").content_sha256
    assert expected and expected != old_hash
    for relative in (
        ".agents/skills/project-helper",
        ".codex/skills/project-helper",
        ".claude/skills/project-helper",
    ):
        assert hash_tree(project / relative) == expected
    lock = json.loads((project / "skills-lock.json").read_text(encoding="utf-8"))
    assert lock["skills"]["project-helper"]["content_sha256"] == expected


def test_project_sync_blocks_local_changes_without_overwriting(
    project_catalog: Catalog, tmp_path: Path
) -> None:
    project = tmp_path / "project"
    canonical = _project(project_catalog, project)
    (canonical / "SKILL.md").write_text("intentional edit\n", encoding="utf-8")
    manager = ProjectSkillsManager(project_catalog, (project,))
    actions = manager.plan()
    assert actions[0].operation == "blocked_local_changes"
    with pytest.raises(MusterctlError) as error:
        manager.apply(actions)
    assert error.value.code == "blocked_local_changes"
    assert (canonical / "SKILL.md").read_text(encoding="utf-8") == (
        "intentional edit\n"
    )


def test_project_sync_rolls_back_when_project_check_fails(
    project_catalog: Catalog, tmp_path: Path
) -> None:
    project = tmp_path / "project"
    canonical = _project(project_catalog, project, failing_check=True)
    old_hash = hash_tree(canonical)
    old_lock = (project / "skills-lock.json").read_bytes()
    _advance_catalog(project_catalog)
    manager = ProjectSkillsManager(project_catalog, (project,))
    with pytest.raises(MusterctlError) as error:
        manager.apply(manager.plan())
    assert error.value.code == "project_validation_failed"
    assert hash_tree(canonical) == old_hash
    assert (project / "skills-lock.json").read_bytes() == old_lock


def test_project_handlers_expose_plan_apply_and_drift_recovery(
    project_catalog: Catalog, tmp_path: Path
) -> None:
    project = tmp_path / "project"
    canonical = _project(project_catalog, project)
    _advance_catalog(project_catalog)
    status = projects_status(project_catalog, (), (project,)).render()
    assert "projects_scanned: 1" in status
    assert "update_available" in status
    planned = projects_sync(project_catalog, (), (), (project,), True, False).render()
    assert "mode: plan" in planned
    assert "mutations: 0" in planned
    assert "operation" in planned and "replace" in planned
    applied = projects_sync(project_catalog, (), (), (project,), False, False).render()
    assert "mutations: 1" in applied
    assert (
        hash_tree(canonical) == project_catalog.skill("project-helper").content_sha256
    )

    (canonical / "SKILL.md").write_text("new local edit\n", encoding="utf-8")
    blocked = projects_sync(project_catalog, (), (), (project,), True, False).render()
    assert "blocked_local_changes" in blocked
    assert "musterctl skills source project-helper" in blocked


@pytest.mark.parametrize(
    ("policy_change", "expected"),
    [
        ("remove", "blocked_not_in_catalog"),
        ("global", "blocked_now_global"),
        ("scope", "blocked_scope"),
    ],
)
def test_project_sync_blocks_catalog_policy_conflicts(
    project_catalog: Catalog,
    tmp_path: Path,
    policy_change: str,
    expected: str,
) -> None:
    project = tmp_path / "project"
    _project(project_catalog, project)
    name = "project-helper"
    if policy_change == "remove":
        del project_catalog.skills[name]
    elif policy_change == "global":
        profile = project_catalog.global_profile
        project_catalog.profiles["global"] = replace(
            profile, skills=(*profile.skills, name)
        )
    else:
        project_catalog.skills[name] = replace(
            project_catalog.skill(name), scopes=("global",)
        )
    actions = ProjectSkillsManager(project_catalog, (project,)).plan()
    assert actions[0].operation == expected


def test_project_sync_rejects_requested_skill_not_found(
    project_catalog: Catalog, tmp_path: Path
) -> None:
    with pytest.raises(MusterctlError) as error:
        ProjectSkillsManager(project_catalog, ()).plan(names=("missing",))
    assert error.value.code == "project_skill_not_found"
