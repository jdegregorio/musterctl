"""Discover Agent Skill installations across global roots and Git projects."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from musterctl.catalog import Catalog
from musterctl.errors import EXIT_ENVIRONMENT, MusterctlError
from musterctl.global_lock import read_global_lock
from musterctl.hashing import hash_tree
from musterctl.resources import runtime_home

_SHA = re.compile(r"(?<![0-9a-f])([0-9a-f]{40})(?![0-9a-f])")
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SKIP_DIRECTORIES = {
    ".git",
    ".hg",
    ".mypy_cache",
    ".nox",
    ".pytest_cache",
    ".ruff_cache",
    ".svn",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "target",
}
_AGENT_SKILL_ROOTS = {
    "claude-code": ".claude/skills",
    "codex": ".codex/skills",
}


@dataclass(frozen=True, slots=True)
class SkillInstallation:
    name: str
    scope: str
    paths: tuple[Path, ...]
    project: Path | None
    lineage: str
    source: str | None
    source_url: str | None
    source_path: str | None
    source_skill: str
    source_pin: str | None
    source_ref: str
    content_sha256: str | None
    locked_sha256: str | None
    catalog_status: str


def _read_json_mapping(path: Path, error_code: str) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MusterctlError(
            error_code,
            f"The skill lock is unreadable: {exc}",
            EXIT_ENVIRONMENT,
            {"path": path},
            ("repair the lock before scanning this installation",),
        ) from exc
    if not isinstance(raw, dict):
        raise MusterctlError(
            error_code,
            "The skill lock must contain a JSON object.",
            EXIT_ENVIRONMENT,
            {"path": path},
        )
    return raw


def _pin(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    match = _SHA.search(value)
    return match.group(1) if match else None


def _catalog_status(
    catalog: Catalog | None,
    name: str,
    actual: str | None,
    locked: str | None,
) -> str:
    if actual is None:
        return "missing"
    if catalog is None or name not in catalog.skills:
        if locked and actual != locked:
            return "local_changes"
        return "not_in_catalog"
    expected = catalog.skills[name].content_sha256
    if not expected:
        return "catalog_unverified"
    if actual == expected:
        return "current" if locked else "catalog_match_untracked"
    if locked and actual != locked:
        return "local_changes"
    return "update_available" if locked else "content_conflict"


def _global_roots(home: Path) -> tuple[Path, ...]:
    return (
        home / ".agents" / "skills",
        home / ".codex" / "skills",
        home / ".claude" / "skills",
    )


def global_installations(
    catalog: Catalog | None = None, home: Path | None = None
) -> list[SkillInstallation]:
    selected_home = home or runtime_home()
    lock_raw = _read_json_mapping(
        selected_home / ".agents" / ".skill-lock.json", "skills_lock_invalid"
    )
    lock = lock_raw.get("skills", {})
    if not isinstance(lock, dict):
        raise MusterctlError(
            "skills_lock_invalid",
            "The Skills CLI lock has no valid skills mapping.",
            EXIT_ENVIRONMENT,
            {"path": selected_home / ".agents" / ".skill-lock.json"},
        )
    muster_lock = read_global_lock(selected_home)

    grouped: dict[tuple[str, Path], list[Path]] = {}
    for root in _global_roots(selected_home):
        if not root.is_dir():
            continue
        try:
            root.resolve().relative_to(selected_home.resolve())
        except ValueError as exc:
            raise MusterctlError(
                "global_skill_root_invalid",
                "A global skill root escapes the selected home directory.",
                EXIT_ENVIRONMENT,
                {"path": root},
            ) from exc
        for candidate in sorted(root.iterdir()):
            if candidate.name.startswith("."):
                continue
            if not candidate.is_dir() or not (candidate / "SKILL.md").is_file():
                continue
            identity = candidate.resolve()
            try:
                identity.relative_to(selected_home.resolve())
            except ValueError as exc:
                raise MusterctlError(
                    "global_skill_path_invalid",
                    "A global skill path escapes the selected home directory.",
                    EXIT_ENVIRONMENT,
                    {"path": candidate},
                ) from exc
            grouped.setdefault((candidate.name, identity), []).append(candidate)

    names = {name for name, _identity in grouped}
    names.update(name for name in lock if isinstance(name, str))
    results: list[SkillInstallation] = []
    for name in sorted(names):
        identities = [
            (identity, tuple(paths))
            for (candidate_name, identity), paths in grouped.items()
            if candidate_name == name
        ]
        raw_entry = lock.get(name, {})
        entry = raw_entry if isinstance(raw_entry, dict) else {}
        source = str(entry["source"]) if entry.get("source") else None
        source_url = str(entry["sourceUrl"]) if entry.get("sourceUrl") else None
        raw_skill_path = entry.get("skillPath")
        source_path = (
            Path(raw_skill_path).parent.as_posix()
            if isinstance(raw_skill_path, str)
            else None
        )
        if not identities:
            results.append(
                SkillInstallation(
                    name,
                    "global",
                    (),
                    None,
                    "tracked" if entry else "untracked",
                    source,
                    source_url,
                    source_path,
                    name,
                    _pin(source),
                    "HEAD",
                    None,
                    None,
                    "missing",
                )
            )
            continue
        for identity, paths in sorted(identities, key=lambda item: str(item[0])):
            actual = hash_tree(identity)
            locked_sha = (
                str(muster_lock[name].get("content_sha256"))
                if name in muster_lock and muster_lock[name].get("content_sha256")
                else None
            )
            results.append(
                SkillInstallation(
                    name,
                    "global",
                    paths,
                    None,
                    "tracked" if entry else "untracked",
                    source,
                    source_url,
                    source_path,
                    name,
                    _pin(source),
                    "HEAD",
                    actual,
                    locked_sha,
                    _catalog_status(catalog, name, actual, locked_sha),
                )
            )
    return results


def default_project_roots(home: Path | None = None) -> tuple[Path, ...]:
    configured = os.environ.get("MUSTERCTL_PROJECT_ROOTS")
    if configured:
        return tuple(
            Path(value).expanduser().resolve()
            for value in configured.split(os.pathsep)
            if value
        )
    selected_home = home or runtime_home()
    repos = selected_home / "Repos"
    return (repos,) if repos.is_dir() else ()


def discover_projects(search_roots: tuple[Path, ...]) -> tuple[Path, ...]:
    projects: set[Path] = set()
    for raw_root in search_roots:
        root = raw_root.expanduser().resolve()
        if not root.is_dir():
            raise MusterctlError(
                "search_root_missing",
                "A project search root does not exist.",
                fields={"path": root},
                next_actions=("choose an existing project search root",),
            )
        for directory, names, files in os.walk(root):
            names[:] = [
                name
                for name in names
                if name not in _SKIP_DIRECTORIES
                and (not name.startswith(".") or name == ".agents")
            ]
            current = Path(directory)
            if "skills-lock.json" in files or (
                ".agents" in names and (current / ".agents" / "skills").is_dir()
            ):
                projects.add(current)
                if len(projects) > 1000:
                    raise MusterctlError(
                        "project_scan_too_large",
                        "The scan found more than 1000 projects and stopped.",
                        EXIT_ENVIRONMENT,
                        {"root": root},
                        ("scan a narrower root",),
                    )
            if current.name == ".agents":
                names.clear()
    return tuple(sorted(projects))


def project_installations(
    catalog: Catalog | None,
    projects: tuple[Path, ...],
) -> list[SkillInstallation]:
    results: list[SkillInstallation] = []
    for project in projects:
        lock_path = project / "skills-lock.json"
        lock_raw = _read_json_mapping(lock_path, "project_lock_invalid")
        raw_skills = lock_raw.get("skills", {})
        if raw_skills is None:
            raw_skills = {}
        if not isinstance(raw_skills, dict):
            raise MusterctlError(
                "project_lock_invalid",
                "The project skill lock has no valid skills mapping.",
                EXIT_ENVIRONMENT,
                {"path": lock_path},
            )
        skill_root = project / ".agents" / "skills"
        if skill_root.is_symlink():
            raise MusterctlError(
                "project_lock_invalid",
                "The canonical project skill root may not be a symlink.",
                EXIT_ENVIRONMENT,
                {"path": skill_root},
            )
        installed = (
            {
                path.name: path
                for path in sorted(skill_root.iterdir())
                if not path.is_symlink()
                and path.is_dir()
                and (path / "SKILL.md").is_file()
            }
            if skill_root.is_dir()
            else {}
        )
        for name in raw_skills:
            if (
                not isinstance(name, str)
                or not _NAME.fullmatch(name)
                or name
                in {
                    ".",
                    "..",
                }
            ):
                raise MusterctlError(
                    "project_lock_invalid",
                    "A project skill lock contains an unsafe skill name.",
                    EXIT_ENVIRONMENT,
                    {"path": lock_path, "skill": name},
                )
        names = sorted(set(raw_skills) | set(installed))
        for name in names:
            raw_entry = raw_skills.get(name, {})
            entry = raw_entry if isinstance(raw_entry, dict) else {}
            path = installed.get(name)
            if path is not None:
                try:
                    path.resolve().relative_to(project.resolve())
                except ValueError as exc:
                    raise MusterctlError(
                        "project_lock_invalid",
                        "A canonical project skill escapes the project boundary.",
                        EXIT_ENVIRONMENT,
                        {"path": path},
                    ) from exc
            actual = hash_tree(path.resolve()) if path else None
            locked = (
                str(entry["content_sha256"]) if entry.get("content_sha256") else None
            )
            source = str(entry["source"]) if entry.get("source") else None
            source_url = str(entry["source_url"]) if entry.get("source_url") else None
            source_path = (
                str(entry["source_path"]) if entry.get("source_path") else None
            )
            source_pin = (
                str(entry["source_pin"]) if entry.get("source_pin") else _pin(source)
            )
            adapter_paths: list[Path] = []
            raw_adapters = entry.get("adapters")
            expected_adapters = (
                [relative for relative in raw_adapters if isinstance(relative, str)]
                if isinstance(raw_adapters, list)
                else (
                    [
                        f"{_AGENT_SKILL_ROOTS[agent]}/{name}"
                        for agent in catalog.global_profile.agents
                        if agent in _AGENT_SKILL_ROOTS
                    ]
                    if catalog is not None
                    else []
                )
            )
            missing_adapter = False
            for relative in expected_adapters:
                adapter_relative = Path(relative)
                if (
                    adapter_relative.is_absolute()
                    or ".." in adapter_relative.parts
                    or adapter_relative.name != name
                ):
                    raise MusterctlError(
                        "project_lock_invalid",
                        "A project skill lock contains an unsafe adapter path.",
                        EXIT_ENVIRONMENT,
                        {"path": lock_path, "adapter": relative},
                    )
                candidate = project / relative
                if not candidate.is_dir() or not (candidate / "SKILL.md").is_file():
                    missing_adapter = True
                    continue
                if candidate.is_symlink():
                    if path is not None and candidate.resolve() == path.resolve():
                        continue
                    raise MusterctlError(
                        "project_lock_invalid",
                        "A project skill adapter symlink does not target its canonical "
                        "copy.",
                        EXIT_ENVIRONMENT,
                        {"path": lock_path, "adapter": relative},
                    )
                try:
                    candidate.resolve().relative_to(project.resolve())
                except ValueError as exc:
                    raise MusterctlError(
                        "project_lock_invalid",
                        "A project skill adapter escapes the project boundary.",
                        EXIT_ENVIRONMENT,
                        {"path": lock_path, "adapter": relative},
                    ) from exc
                if path is None or candidate.resolve() != path.resolve():
                    adapter_paths.append(candidate)
            status = _catalog_status(catalog, name, actual, locked)
            adapter_hashes = [hash_tree(adapter.resolve()) for adapter in adapter_paths]
            if actual is None and adapter_hashes:
                if not locked or any(value != locked for value in adapter_hashes):
                    status = "local_changes"
            elif any(value != actual for value in adapter_hashes):
                if (
                    status in {"current", "update_available"}
                    and locked
                    and all(value in {actual, locked} for value in adapter_hashes)
                ):
                    status = "adapter_update"
                else:
                    status = "local_changes"
            elif status in {"current", "update_available"} and missing_adapter:
                status = "adapter_missing"
            if (
                status == "current"
                and catalog is not None
                and name in catalog.skills
                and source_pin != catalog.skills[name].pin
            ):
                status = "lineage_update"
            results.append(
                SkillInstallation(
                    name,
                    "project",
                    (*((path,) if path else ()), *adapter_paths),
                    project,
                    "tracked" if entry else "untracked",
                    source,
                    source_url,
                    source_path,
                    str(entry.get("source_skill", name)),
                    source_pin,
                    str(entry.get("source_ref", "HEAD")),
                    actual,
                    locked,
                    status,
                )
            )
    return results


def inventory(
    catalog: Catalog | None,
    *,
    search_roots: tuple[Path, ...] = (),
    projects: tuple[Path, ...] = (),
    home: Path | None = None,
) -> list[SkillInstallation]:
    selected_roots = search_roots or (() if projects else default_project_roots(home))
    discovered = set(discover_projects(selected_roots)) if selected_roots else set()
    for project in projects:
        resolved = project.expanduser().resolve()
        if not resolved.is_dir():
            raise MusterctlError(
                "project_missing",
                "A requested project directory does not exist.",
                fields={"path": resolved},
            )
        discovered.add(resolved)
    return [
        *global_installations(catalog, home),
        *project_installations(catalog, tuple(sorted(discovered))),
    ]
