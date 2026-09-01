from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from musterctl.catalog import Catalog
from musterctl.errors import MusterctlError
from musterctl.inventory import discover_projects, inventory


def test_inventory_discovers_projects_and_reports_name_conflicts(
    catalog: Catalog, isolated_home: Path, tmp_path: Path
) -> None:
    global_skill = isolated_home / ".agents" / "skills" / "shared-name"
    global_skill.mkdir(parents=True)
    (global_skill / "SKILL.md").write_text("# Global variant\n", encoding="utf-8")
    project = tmp_path / "repos" / "project"
    project_skill = project / ".agents" / "skills" / "shared-name"
    project_skill.mkdir(parents=True)
    (project_skill / "SKILL.md").write_text("# Project variant\n", encoding="utf-8")
    (project / "skills-lock.json").write_text(
        json.dumps({"version": 1, "skills": {}}), encoding="utf-8"
    )
    found = inventory(catalog, search_roots=(tmp_path / "repos",))
    variants = [item for item in found if item.name == "shared-name"]
    assert {item.scope for item in variants} == {"global", "project"}
    assert len({item.content_sha256 for item in variants}) == 2
    assert discover_projects((tmp_path / "repos",)) == (project,)


def test_project_inventory_reports_updates_without_calling_source(
    catalog: Catalog, tmp_path: Path
) -> None:
    skill = catalog.skill("project-helper")
    project = tmp_path / "project"
    installed = project / ".agents" / "skills" / skill.name
    installed.parent.mkdir(parents=True)
    shutil.copytree(
        Path(skill.source_url),
        installed,
        ignore=shutil.ignore_patterns(".git"),
    )
    adapters = []
    for root in (".codex/skills", ".claude/skills"):
        target = project / root / skill.name
        target.parent.mkdir(parents=True)
        shutil.copytree(installed, target)
        adapters.append(f"{root}/{skill.name}")
    (project / "skills-lock.json").write_text(
        json.dumps(
            {
                "skills": {
                    skill.name: {
                        "adapters": adapters,
                        "content_sha256": skill.content_sha256,
                        "source": skill.source,
                        "source_path": skill.source_path,
                        "source_pin": "0" * 40,
                        "source_ref": "HEAD",
                        "source_url": skill.source_url,
                        "update_policy": skill.update_policy,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    observed = inventory(catalog, projects=(project,), search_roots=(tmp_path,))
    project_item = next(item for item in observed if item.scope == "project")
    assert project_item.catalog_status == "lineage_update"
    assert len(project_item.paths) == 3


@pytest.mark.parametrize(
    "skills",
    [
        {"../../escape": {}},
        {
            "safe-name": {
                "adapters": ["../../outside/safe-name"],
                "content_sha256": "0" * 64,
            }
        },
    ],
)
def test_project_inventory_rejects_escaping_lock_paths(
    catalog: Catalog, tmp_path: Path, skills: dict[str, object]
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "skills-lock.json").write_text(
        json.dumps({"skills": skills}), encoding="utf-8"
    )
    with pytest.raises(MusterctlError) as error:
        inventory(catalog, projects=(project,))
    assert error.value.code == "project_lock_invalid"
