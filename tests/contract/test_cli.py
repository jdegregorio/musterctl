from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from musterctl.catalog import Catalog
from musterctl.cli import main


@pytest.mark.parametrize(
    "arguments",
    [
        ["--help"],
        ["status", "--help"],
        ["catalog", "--help"],
        ["catalog", "search", "--help"],
        ["catalog", "show", "--help"],
        ["catalog", "add", "--help"],
        ["catalog", "adopt", "--help"],
        ["catalog", "remove", "--help"],
        ["catalog", "configure", "--help"],
        ["catalog", "check-updates", "--help"],
        ["catalog", "update", "--help"],
        ["templates", "--help"],
        ["templates", "list", "--help"],
        ["templates", "show", "--help"],
        ["skills", "--help"],
        ["skills", "available", "--help"],
        ["skills", "status", "--help"],
        ["skills", "sync", "--help"],
        ["skills", "diff", "--help"],
        ["skills", "source", "--help"],
        ["skills", "checkout", "--help"],
        ["skills", "prune", "--help"],
        ["projects", "--help"],
        ["projects", "status", "--help"],
        ["projects", "sync", "--help"],
        ["setup", "--help"],
        ["setup", "inspect", "--help"],
        ["setup", "init", "--help"],
        ["init", "--help"],
    ],
)
def test_help_exists_at_every_level(
    arguments: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(arguments) == 0
    assert "usage:" in capsys.readouterr().out


@pytest.mark.parametrize(
    "group", [["catalog"], ["templates"], ["skills"], ["projects"], ["setup"]]
)
def test_command_groups_without_subcommand_show_help(
    group: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(group) == 0
    captured = capsys.readouterr()
    assert "usage:" in captured.out
    assert captured.err == ""


def test_version_is_available(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == "0.2.0"


def test_unknown_flags_and_values_are_structured(
    isolated_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["status", "--wat"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error: invalid_arguments" in captured.err
    assert "usage:" in captured.err
    assert main(["templates", "show", "pythn"]) == 2
    assert "error: unknown_template" in capsys.readouterr().err


def test_dashboard_and_read_operations_have_agent_native_shape(
    isolated_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    assert main([]) == 0
    dashboard = capsys.readouterr().out
    assert "context: global" in dashboard
    assert "next[2]:" in dashboard
    assert main(["catalog", "search", "no-such-capability"]) == 0
    search = capsys.readouterr().out
    assert "skills[0]{name,category,ownership,policy,description}:" in search
    assert main(["skills", "available", "--template", "python-cli"]) == 0
    available = capsys.readouterr().out
    assert "global[3]{name,status,reason}:" in available
    assert "available[0]{name,category,policy}:" in available


def test_init_plan_has_no_mutation_and_replay_command(
    isolated_home: Path,
    project_catalog: Catalog,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert (
        main(
            [
                "--catalog",
                str(project_catalog.path),
                "init",
                "planned",
                "--template",
                "python-cli",
                "--skill",
                "project-helper",
                "--plan",
                "--parent",
                str(tmp_path),
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "mutations: 0" in output
    assert "install 1 project skills" in output
    assert "--plan" not in output
    assert not (tmp_path / "planned").exists()


def test_init_global_duplicate_and_destination_conflict_have_conflict_exit(
    isolated_home: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert (
        main(
            [
                "init",
                "bad",
                "--template",
                "base",
                "--skill",
                "musterctl",
                "--plan",
                "--parent",
                str(tmp_path),
            ]
        )
        == 3
    )
    assert "error: skill_already_global" in capsys.readouterr().err
    (tmp_path / "exists").mkdir()
    assert (
        main(
            [
                "init",
                "exists",
                "--template",
                "base",
                "--plan",
                "--parent",
                str(tmp_path),
            ]
        )
        == 3
    )
    assert "error: destination_exists" in capsys.readouterr().err


def test_sync_dry_run_does_not_invoke_subprocess(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("dry-run invoked subprocess")

    monkeypatch.setattr("musterctl.state.subprocess.run", forbidden)
    assert main(["skills", "sync", "--dry-run"]) == 0
    output = capsys.readouterr().out
    assert "mode: plan" in output
    assert "mutations: 0" in output
    assert "--global" in output


def test_catalog_add_plan_does_not_fetch_or_write(
    catalog: Catalog,
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    original = catalog.path.read_bytes()

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("plan fetched a source")

    monkeypatch.setattr("musterctl.handlers.inspect_source", forbidden)
    assert (
        main(
            [
                "catalog",
                "add",
                "planned-helper",
                "--source",
                "https://example.invalid/helper.git",
                "--plan",
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "mode: plan" in output
    assert "mutations: 0" in output
    assert "--plan" not in output.split("next[1]:", 1)[1]
    assert catalog.path.read_bytes() == original


def test_prune_requires_explicit_selection_when_applying(
    isolated_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["skills", "prune"]) == 3
    assert "error: prune_selection_required" in capsys.readouterr().err


def test_noninteractive_subprocess_runs_with_closed_stdin(
    catalog: Catalog, isolated_home: Path, tmp_path: Path
) -> None:
    root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(root / "src")
    environment["MUSTERCTL_HOME"] = str(isolated_home)
    environment["MUSTERCTL_CATALOG"] = str(catalog.path)
    result = subprocess.run(
        [sys.executable, "-m", "musterctl", "templates", "list"],
        cwd=tmp_path,
        env=environment,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0
    assert "templates[2]" in result.stdout
    assert result.stderr == ""
