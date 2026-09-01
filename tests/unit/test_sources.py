from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from musterctl.errors import MusterctlError
from musterctl.hashing import hash_tree
from musterctl.sources import copy_source, materialized_source


def _repo(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "source"
    (repo / "nested").mkdir(parents=True)
    (repo / "nested" / "value.txt").write_text("value\n", encoding="utf-8")
    subprocess.run(("git", "init", "--quiet", "-b", "main"), cwd=repo, check=True)
    subprocess.run(("git", "add", "."), cwd=repo, check=True)
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
            "fixture",
        ),
        cwd=repo,
        check=True,
    )
    revision = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return repo, revision, hash_tree(repo / "nested")


def test_materialize_and_copy_exact_source(tmp_path: Path) -> None:
    repo, revision, digest = _repo(tmp_path)
    with materialized_source(str(repo), revision, "nested", digest) as selected:
        assert (selected / "value.txt").read_text(encoding="utf-8") == "value\n"
    destination = tmp_path / "output"
    copy_source(str(repo), revision, "nested", digest, destination)
    assert (destination / "value.txt").is_file()
    assert not (destination / ".git").exists()


def test_source_rejects_digest_path_and_revision_errors(tmp_path: Path) -> None:
    repo, revision, _digest = _repo(tmp_path)
    with (
        pytest.raises(MusterctlError) as digest_error,
        materialized_source(str(repo), revision, "nested", "0" * 64),
    ):
        pass
    assert digest_error.value.code == "source_digest_mismatch"
    with (
        pytest.raises(MusterctlError) as path_error,
        materialized_source(str(repo), revision, "missing", None),
    ):
        pass
    assert path_error.value.code == "source_path_missing"
    with (
        pytest.raises(MusterctlError) as revision_error,
        materialized_source(str(repo), "not-a-revision", ".", None),
    ):
        pass
    assert revision_error.value.code == "source_fetch_failed"


def test_source_reports_missing_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, revision, _digest = _repo(tmp_path)

    def unavailable(*_args: object, **_kwargs: object) -> None:
        raise OSError("missing")

    monkeypatch.setattr("musterctl.sources.subprocess.run", unavailable)
    with (
        pytest.raises(MusterctlError) as error,
        materialized_source(str(repo), revision, ".", None),
    ):
        pass
    assert error.value.code == "git_unavailable"


def test_source_rejects_symlinks(tmp_path: Path) -> None:
    repo, _revision, _digest = _repo(tmp_path)
    (repo / "nested" / "alias").symlink_to("value.txt")
    subprocess.run(("git", "add", "."), cwd=repo, check=True)
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
            "add symlink",
        ),
        cwd=repo,
        check=True,
    )
    revision = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    with (
        pytest.raises(MusterctlError) as error,
        materialized_source(str(repo), revision, "nested", None),
    ):
        pass
    assert error.value.code == "source_symlink_unsupported"
