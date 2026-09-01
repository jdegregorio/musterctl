from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from musterctl.catalog import Catalog
from musterctl.cli import main
from musterctl.hashing import hash_tree
from musterctl.sources import source_selector


def _git_skill(path: Path, name: str) -> tuple[str, str]:
    path.mkdir()
    (path / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {name} helper.\n---\n# {name}\n",
        encoding="utf-8",
    )
    subprocess.run(("git", "init", "--quiet", "-b", "main"), cwd=path, check=True)
    subprocess.run(("git", "add", "."), cwd=path, check=True)
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
            "initial",
        ),
        cwd=path,
        check=True,
    )
    return _snapshot(path)


def _snapshot(path: Path) -> tuple[str, str]:
    revision = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return revision, hash_tree(path)


def _commit(path: Path, content: str) -> tuple[str, str]:
    (path / "SKILL.md").write_text(content, encoding="utf-8")
    subprocess.run(("git", "add", "."), cwd=path, check=True)
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
            "update",
        ),
        cwd=path,
        check=True,
    )
    return _snapshot(path)


def test_catalog_lifecycle_from_add_through_update_and_remove(
    catalog: Catalog,
    isolated_home: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "lifecycle-source"
    revision, _digest = _git_skill(source, "lifecycle-helper")
    arguments = [
        "catalog",
        "add",
        "lifecycle-helper",
        "--source",
        str(source),
        "--ref",
        "main",
        "--description",
        "Lifecycle helper.",
        "--source-skill",
        "upstream-helper",
        "--category",
        "Test",
        "--scope",
        "project",
        "--global",
        "--license",
        "Proprietary",
    ]
    assert main([*arguments, "--plan"]) == 0
    planned = capsys.readouterr().out
    assert "resolved_revision: null" in planned
    assert "lifecycle-helper" not in Catalog.load(catalog.path).skills
    assert main(arguments) == 0
    added = capsys.readouterr().out
    assert f"resolved_revision: {revision}" in added
    loaded = Catalog.load(catalog.path)
    assert loaded.skill("lifecycle-helper").source_ref == "main"
    assert loaded.skill("lifecycle-helper").source_skill == "upstream-helper"
    assert main(["catalog", "check-updates", "lifecycle-helper"]) == 0
    assert "lifecycle-helper,current" in capsys.readouterr().out

    assert main(["catalog", "configure", "lifecycle-helper"]) == 2
    assert "configuration_change_missing" in capsys.readouterr().err
    assert (
        main(
            [
                "catalog",
                "configure",
                "lifecycle-helper",
                "--no-global",
                "--plan",
            ]
        )
        == 0
    )
    assert "--no-global" in capsys.readouterr().out

    configure = [
        "catalog",
        "configure",
        "lifecycle-helper",
        "--global",
        "--scope",
        "project",
    ]
    assert main([*configure, "--plan"]) == 0
    assert "mutations: 0" in capsys.readouterr().out
    assert main(configure) == 0
    capsys.readouterr()
    loaded = Catalog.load(catalog.path)
    assert "lifecycle-helper" in loaded.global_profile.skills
    assert loaded.skill("lifecycle-helper").scopes == ("project", "global")

    new_revision, _new_digest = _commit(source, "# Lifecycle helper v2\n")
    assert main(["catalog", "check-updates", "lifecycle-helper"]) == 0
    update_check = capsys.readouterr().out
    assert "lifecycle-helper,available" in update_check
    assert new_revision in update_check
    assert (
        main(
            [
                "catalog",
                "update",
                "lifecycle-helper",
                "--ref",
                "main",
                "--plan",
            ]
        )
        == 0
    )
    assert "resolved_revision: null" in capsys.readouterr().out
    assert (
        main(
            [
                "catalog",
                "update",
                "lifecycle-helper",
                "--ref",
                "main",
            ]
        )
        == 0
    )
    assert new_revision in capsys.readouterr().out
    assert Catalog.load(catalog.path).skill("lifecycle-helper").pin == new_revision

    assert main(["catalog", "remove", "lifecycle-helper", "--plan"]) == 0
    removal_plan = capsys.readouterr().out
    assert "profile:global" in removal_plan
    assert main(["catalog", "remove", "lifecycle-helper"]) == 0
    capsys.readouterr()
    assert "lifecycle-helper" not in Catalog.load(catalog.path).skills


def test_adopt_verifies_an_existing_install_and_setup_reports_no_source(
    catalog: Catalog,
    isolated_home: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "adopt-source"
    revision, _digest = _git_skill(source, "adopted-helper")
    installed = isolated_home / ".agents" / "skills" / "adopted-helper"
    installed.parent.mkdir(parents=True)
    shutil.copytree(source, installed, ignore=shutil.ignore_patterns(".git"))
    anonymous = isolated_home / ".agents" / "skills" / "anonymous"
    anonymous.mkdir()
    (anonymous / "SKILL.md").write_text("# Anonymous\n", encoding="utf-8")
    (isolated_home / ".agents" / ".skill-lock.json").write_text(
        json.dumps(
            {
                "skills": {
                    "adopted-helper": {
                        "source": source_selector(str(source), revision, "."),
                        "sourceUrl": str(source),
                        "skillPath": "SKILL.md",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    assert main(["setup", "inspect"]) == 0
    inspected = capsys.readouterr().out
    assert "anonymous,global,untracked,no_source" in inspected
    assert "use gh-axi" in inspected
    assert main(["catalog", "adopt", str(anonymous)]) == 3
    assert "source_lineage_missing" in capsys.readouterr().err
    assert main(["catalog", "adopt", str(tmp_path / "missing")]) == 2
    assert "installed_skill_not_found" in capsys.readouterr().err
    command = ["catalog", "adopt", str(installed)]
    assert (
        main(
            [
                *command,
                "--description",
                "Imported custom helper.",
                "--category",
                "Custom",
                "--no-global",
                "--plan",
            ]
        )
        == 0
    )
    plan = capsys.readouterr().out
    assert "mode: plan" in plan
    assert "--no-global" in plan
    (installed / "SKILL.md").write_text("local mismatch\n", encoding="utf-8")
    assert main(command) == 3
    assert "source_lineage_mismatch" in capsys.readouterr().err
    shutil.rmtree(installed)
    shutil.copytree(source, installed, ignore=shutil.ignore_patterns(".git"))
    assert main(command) == 0
    adopted = capsys.readouterr().out
    assert f"resolved_revision: {revision}" in adopted
    loaded = Catalog.load(catalog.path)
    assert loaded.skill("adopted-helper").content_sha256 == hash_tree(installed)
    assert "adopted-helper" in loaded.global_profile.skills


def test_skill_source_checkout_and_no_replace_contract(
    catalog: Catalog,
    isolated_home: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["skills", "source", "project-helper"]) == 0
    source_output = capsys.readouterr().out
    assert "source_url:" in source_output
    assert "musterctl catalog update project-helper --plan" in source_output
    destination = tmp_path / "editable"
    command = [
        "skills",
        "checkout",
        "project-helper",
        "--destination",
        str(destination),
    ]
    assert main([*command, "--plan"]) == 0
    assert not destination.exists()
    capsys.readouterr()
    assert main(command) == 0
    checkout = capsys.readouterr().out
    assert "mutations: 1" in checkout
    assert (destination / "SKILL.md").is_file()
    assert main(command) == 3
    assert "error: destination_exists" in capsys.readouterr().err


def test_global_sync_drift_protection_and_explicit_prune(
    catalog: Catalog,
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fake_install(
        command: tuple[str, ...],
        cwd: Path | None = None,
        home: Path | None = None,
    ) -> None:
        assert cwd is None
        assert home == isolated_home
        name = command[command.index("--skill") + 1]
        target = isolated_home / ".agents" / "skills" / name
        if target.exists():
            shutil.rmtree(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(
            Path(catalog.skill(name).source_url),
            target,
            ignore=shutil.ignore_patterns(".git"),
        )

    monkeypatch.setattr(
        "musterctl.state.SkillsManager.run_install", staticmethod(fake_install)
    )
    assert main(["skills", "sync", "--dry-run"]) == 0
    assert "mutations: 0" in capsys.readouterr().out
    assert main(["skills", "sync"]) == 0
    synced = capsys.readouterr().out
    assert "status: current" in synced

    drifted = isolated_home / ".agents" / "skills" / "musterctl" / "SKILL.md"
    drifted.write_text("local change\n", encoding="utf-8")
    assert main(["skills", "sync", "--dry-run"]) == 0
    plan = capsys.readouterr().out
    assert "blocked_local_changes" in plan
    assert "musterctl skills source musterctl" in plan
    assert main(["skills", "sync"]) == 3
    assert "error: local_skill_changes" in capsys.readouterr().err
    assert main(["skills", "sync", "--replace-drift"]) == 0
    capsys.readouterr()

    unmanaged = isolated_home / ".agents" / "skills" / "old-helper"
    unmanaged.mkdir()
    (unmanaged / "SKILL.md").write_text("# Old\n", encoding="utf-8")
    assert main(["skills", "prune", "--plan"]) == 0
    prune_plan = capsys.readouterr().out
    assert "old-helper" in prune_plan
    assert unmanaged.is_dir()
    assert main(["skills", "prune", "old-helper"]) == 0
    assert "mutations: 1" in capsys.readouterr().out
    assert not unmanaged.exists()
