from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from musterctl.catalog import Catalog
from musterctl.handlers import (
    catalog_search,
    catalog_show,
    dashboard,
    setup_init,
    setup_inspect,
    skills_available,
    skills_diff,
    status,
    templates_show,
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


def test_read_handlers_expose_context_and_next_actions(
    catalog: Catalog,
    isolated_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    assert "context: global" in dashboard(catalog).render()
    assert "health: attention" in status(catalog).render()
    assert "skills[1]" in catalog_search(catalog, "github").render()
    shown = catalog_show(catalog, "gh-axi").render()
    assert "source_url:" in shown and "pin:" in shown
    assert "recommended_skills[0]" in templates_show(catalog, "base").render()
    assert "available[1]" in skills_available(catalog, None).render()


def test_unmanaged_global_skill_is_visible_without_sync_attention(
    catalog: Catalog,
    isolated_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in catalog.global_profile.skills:
        _install(catalog, isolated_home, name)
    unmanaged = isolated_home / ".agents" / "skills" / "local-helper"
    unmanaged.mkdir()
    (unmanaged / "SKILL.md").write_text("# Local helper\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    rendered = status(catalog).render()
    assert "health: ok" in rendered
    assert "local-helper,unmanaged,unknown" in rendered
    assert "musterctl skills sync --dry-run" not in rendered


def test_skills_diff_prefers_project_installation(
    project_catalog: Catalog,
    isolated_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    installed = project / ".agents" / "skills" / "project-helper"
    installed.parent.mkdir(parents=True)
    shutil.copytree(
        Path(project_catalog.skill("project-helper").source_url),
        installed,
        ignore=shutil.ignore_patterns(".git"),
    )
    (project / ".git").mkdir()
    monkeypatch.chdir(project)
    assert "status: current" in skills_diff(project_catalog, "project-helper").render()
    (installed / "SKILL.md").write_text("changed", encoding="utf-8")
    rendered = skills_diff(project_catalog, "project-helper").render()
    assert "status: different" in rendered
    assert "scope: project" in rendered
    assert "--- source/SKILL.md" in rendered
    assert "restore .agents/skills/project-helper" in rendered


def test_skills_diff_reports_missing(catalog: Catalog, isolated_home: Path) -> None:
    rendered = skills_diff(catalog, "musterctl").render()
    assert "status: missing" in rendered
    assert "diff[0]:" in rendered
    assert "musterctl skills sync --dry-run" in rendered


def test_setup_handlers_work_before_catalog_exists(
    isolated_home: Path, tmp_path: Path
) -> None:
    skill = isolated_home / ".agents" / "skills" / "tracked"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: tracked\ndescription: Tracked skill.\n---\n",
        encoding="utf-8",
    )
    lock = isolated_home / ".agents" / ".skill-lock.json"
    lock.write_text(
        json.dumps(
            {
                "skills": {
                    "tracked": {
                        "source": "owner/repo",
                        "sourceUrl": "https://github.com/owner/repo.git",
                        "skillPath": "skills/tracked/SKILL.md",
                        "skillFolderHash": "abc",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    inspected = setup_inspect().render()
    assert "tracked,tracked,owner/repo,skills/tracked,true" in inspected
    destination = tmp_path / "bootstrap" / "catalog.toml"
    planned = setup_init(["tracked"], False, destination, True).render()
    assert "mode: plan" in planned
    assert "mutations: 0" in planned
    assert not destination.exists()
    applied = setup_init(["tracked"], False, destination, False).render()
    assert "mode: apply" in applied
    assert "mutations: 1" in applied
    assert destination.is_file()


def test_dashboard_reports_project_context(
    catalog: Catalog,
    isolated_home: Path,
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    rendered = dashboard(catalog, project).render()
    assert "context: project" in rendered
    assert "project_skills_installed: 0" in rendered
