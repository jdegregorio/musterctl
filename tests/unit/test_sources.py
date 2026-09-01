from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from musterctl.errors import MusterctlError
from musterctl.hashing import hash_tree
from musterctl.sources import (
    checkout_source,
    copy_source,
    inspect_source,
    materialized_source,
    source_selector,
)


def _repo(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "source"
    (repo / "nested").mkdir(parents=True)
    (repo / "nested" / "SKILL.md").write_text("# Helper\n", encoding="utf-8")
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


def test_inspect_and_checkout_editable_source(tmp_path: Path) -> None:
    repo, revision, digest = _repo(tmp_path)
    assert inspect_source(str(repo), "main", "nested").content_sha256 == digest
    destination = tmp_path / "checkout"
    checked_out = checkout_source(str(repo), "main", "nested", destination, digest)
    assert checked_out.revision == revision
    assert checked_out.selected == destination / "nested"
    assert (checked_out.selected / "SKILL.md").is_file()
    assert (
        source_selector(
            "https://github.com/example/helper.git", revision, "skills/helper"
        )
        == f"https://github.com/example/helper/tree/{revision}/skills/helper"
    )


def test_checkout_conflicts_and_validation_are_transactional(tmp_path: Path) -> None:
    repo, _revision, digest = _repo(tmp_path)
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(MusterctlError) as conflict:
        checkout_source(str(repo), "main", "nested", existing, digest)
    assert conflict.value.code == "destination_exists"
    with pytest.raises(MusterctlError) as parent:
        checkout_source(
            str(repo), "main", "nested", tmp_path / "missing" / "checkout", digest
        )
    assert parent.value.code == "parent_missing"
    advanced = tmp_path / "advanced"
    with pytest.raises(MusterctlError) as changed:
        checkout_source(str(repo), "main", "nested", advanced, "f" * 64)
    assert changed.value.code == "source_checkout_advanced"
    assert not advanced.exists()
    escaped = tmp_path / "escaped"
    with pytest.raises(MusterctlError) as invalid_path:
        checkout_source(str(repo), "main", "../", escaped)
    assert invalid_path.value.code == "source_path_invalid"
    assert not escaped.exists()


def test_inspect_requires_a_skill_document(tmp_path: Path) -> None:
    repo, _revision, _digest = _repo(tmp_path)
    with pytest.raises(MusterctlError) as error:
        inspect_source(str(repo), "main", ".")
    assert error.value.code == "source_skill_missing"
