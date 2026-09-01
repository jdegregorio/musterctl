"""Materialize exact Git-backed catalog sources into isolated directories."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from musterctl.errors import EXIT_ENVIRONMENT, MusterctlError
from musterctl.hashing import hash_tree


def _run_git(arguments: tuple[str, ...], cwd: Path) -> str:
    try:
        result = subprocess.run(
            ("git", *arguments),
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
        )
    except OSError as exc:
        raise MusterctlError(
            "git_unavailable",
            f"Git could not be started: {exc}",
            EXIT_ENVIRONMENT,
            next_actions=("install Git and rerun the command",),
        ) from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise MusterctlError(
            "source_fetch_failed",
            detail or f"Git exited with status {result.returncode}.",
            EXIT_ENVIRONMENT,
            {"exit_code": result.returncode},
            ("verify source access and the configured revision",),
        )
    return result.stdout.strip()


@contextmanager
def materialized_source(
    source_url: str,
    revision: str,
    source_path: str,
    expected_hash: str | None,
) -> Iterator[Path]:
    """Yield a verified directory from one exact source revision."""

    with tempfile.TemporaryDirectory(prefix="musterctl-source-") as raw_temp:
        checkout = Path(raw_temp) / "checkout"
        checkout.mkdir()
        _run_git(("init", "--quiet"), checkout)
        _run_git(
            (
                "-c",
                "protocol.file.allow=always",
                "fetch",
                "--quiet",
                "--depth",
                "1",
                source_url,
                revision,
            ),
            checkout,
        )
        _run_git(("checkout", "--quiet", "--detach", "FETCH_HEAD"), checkout)
        resolved = _run_git(("rev-parse", "HEAD"), checkout)
        if len(revision) == 40 and resolved != revision:
            raise MusterctlError(
                "source_revision_mismatch",
                "The fetched source did not resolve to the configured revision.",
                EXIT_ENVIRONMENT,
                {"expected": revision, "actual": resolved},
            )
        selected = (checkout / source_path).resolve()
        try:
            selected.relative_to(checkout.resolve())
        except ValueError as exc:
            raise MusterctlError(
                "source_path_invalid",
                "The configured source path escapes its repository.",
                EXIT_ENVIRONMENT,
                {"source_path": source_path},
            ) from exc
        if not selected.is_dir():
            raise MusterctlError(
                "source_path_missing",
                "The configured source path does not exist at the revision.",
                EXIT_ENVIRONMENT,
                {"source_path": source_path, "revision": resolved},
            )
        actual_hash = hash_tree(selected)
        if expected_hash and actual_hash != expected_hash:
            raise MusterctlError(
                "source_digest_mismatch",
                "Fetched source content does not match the configured digest.",
                EXIT_ENVIRONMENT,
                {"expected": expected_hash, "actual": actual_hash},
                ("review and update the catalog source pin and digest together",),
            )
        yield selected


def copy_source(
    source_url: str,
    revision: str,
    source_path: str,
    expected_hash: str,
    destination: Path,
) -> None:
    with materialized_source(
        source_url, revision, source_path, expected_hash
    ) as selected:
        shutil.copytree(
            selected,
            destination,
            dirs_exist_ok=True,
            copy_function=shutil.copy2,
            ignore=shutil.ignore_patterns(".git"),
        )
