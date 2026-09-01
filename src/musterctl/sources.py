"""Materialize exact Git-backed catalog sources into isolated directories."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from musterctl.errors import EXIT_CONFLICT, EXIT_ENVIRONMENT, MusterctlError
from musterctl.hashing import hash_tree


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    revision: str
    content_sha256: str


@dataclass(frozen=True, slots=True)
class SourceCheckout:
    root: Path
    selected: Path
    revision: str
    content_sha256: str


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
def resolved_source(
    source_url: str,
    revision: str,
    source_path: str,
    expected_hash: str | None,
) -> Iterator[SourceCheckout]:
    """Yield a verified checkout and selected directory for one Git revision."""

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
        symlinks = [
            path.relative_to(selected).as_posix()
            for path in selected.rglob("*")
            if path.is_symlink()
        ]
        if symlinks:
            raise MusterctlError(
                "source_symlink_unsupported",
                "Catalog sources may not contain symbolic links.",
                EXIT_ENVIRONMENT,
                {"paths": ",".join(symlinks)},
                ("replace source symlinks with ordinary files or directories",),
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
        yield SourceCheckout(checkout, selected, resolved, actual_hash)


@contextmanager
def materialized_source(
    source_url: str,
    revision: str,
    source_path: str,
    expected_hash: str | None,
) -> Iterator[Path]:
    """Yield a verified directory from one exact source revision."""

    with resolved_source(source_url, revision, source_path, expected_hash) as resolved:
        yield resolved.selected


def inspect_source(source_url: str, revision: str, source_path: str) -> SourceSnapshot:
    """Resolve a source ref and return its immutable revision and content hash."""

    with resolved_source(source_url, revision, source_path, None) as resolved:
        if not (resolved.selected / "SKILL.md").is_file():
            raise MusterctlError(
                "source_skill_missing",
                "The selected source directory does not contain SKILL.md.",
                EXIT_ENVIRONMENT,
                {"source_path": source_path, "revision": resolved.revision},
            )
        return SourceSnapshot(resolved.revision, resolved.content_sha256)


def source_selector(source_url: str, revision: str, source_path: str) -> str:
    """Render deterministic human-facing lineage for a pinned source directory."""

    normalized = source_url.removesuffix(".git")
    if normalized.startswith("https://github.com/"):
        path = source_path.strip("/")
        suffix = f"/{path}" if path and path != "." else ""
        return f"{normalized}/tree/{revision}{suffix}"
    suffix = "" if source_path in {"", "."} else f"#{source_path}"
    return f"{source_url}@{revision}{suffix}"


def checkout_source(
    source_url: str,
    source_ref: str,
    source_path: str,
    destination: Path,
    expected_hash: str | None = None,
) -> SourceCheckout:
    """Clone an editable source checkout without replacing an existing path."""

    selected_destination = destination.expanduser().resolve()
    if selected_destination.exists() or selected_destination.is_symlink():
        raise MusterctlError(
            "destination_exists",
            "The source checkout destination already exists and was not overwritten.",
            EXIT_CONFLICT,
            fields={"path": selected_destination},
            next_actions=("choose another destination",),
        )
    if not selected_destination.parent.is_dir():
        raise MusterctlError(
            "parent_missing",
            "The source checkout parent directory does not exist.",
            EXIT_CONFLICT,
            fields={"path": selected_destination.parent},
            next_actions=("create or choose an existing parent directory",),
        )
    temporary = Path(
        tempfile.mkdtemp(
            prefix=f".{selected_destination.name}.musterctl-",
            dir=selected_destination.parent,
        )
    )
    try:
        shutil.rmtree(temporary)
        _run_git(("clone", "--quiet", source_url, str(temporary)), Path.cwd())
        if source_ref != "HEAD":
            _run_git(("checkout", "--quiet", source_ref), temporary)
        revision = _run_git(("rev-parse", "HEAD"), temporary)
        selected = (temporary / source_path).resolve()
        try:
            selected.relative_to(temporary.resolve())
        except ValueError as exc:
            raise MusterctlError(
                "source_path_invalid",
                "The configured source path escapes its repository.",
                fields={"source_path": source_path},
            ) from exc
        if not selected.is_dir() or not (selected / "SKILL.md").is_file():
            raise MusterctlError(
                "source_path_missing",
                "The checkout does not contain the configured Agent Skill.",
                fields={"source_path": source_path, "revision": revision},
            )
        digest = hash_tree(selected)
        if expected_hash is not None and digest != expected_hash:
            raise MusterctlError(
                "source_checkout_advanced",
                "The editable source ref differs from the configured catalog snapshot.",
                EXIT_ENVIRONMENT,
                {
                    "expected": expected_hash,
                    "actual": digest,
                    "revision": revision,
                },
                (
                    "run musterctl catalog check-updates",
                    "update the catalog before editing this newer source",
                ),
            )
        try:
            temporary.rename(selected_destination)
        except FileExistsError as exc:
            raise MusterctlError(
                "destination_exists",
                "The source checkout destination appeared and was not overwritten.",
                EXIT_CONFLICT,
                fields={"path": selected_destination},
            ) from exc
        return SourceCheckout(
            selected_destination,
            selected_destination / source_path,
            revision,
            digest,
        )
    finally:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)


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
