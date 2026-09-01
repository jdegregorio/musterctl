"""Inspect global and project skill state without mutation."""

from __future__ import annotations

import difflib
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from musterctl.catalog import Catalog, SkillSpec
from musterctl.errors import EXIT_ENVIRONMENT, MusterctlError
from musterctl.hashing import hash_tree
from musterctl.resources import runtime_home
from musterctl.sources import materialized_source


@dataclass(frozen=True, slots=True)
class SkillState:
    name: str
    scope: str
    status: str
    policy: str
    expected_hash: str
    actual_hash: str | None
    paths: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class SyncAction:
    skill: SkillSpec
    operation: str
    command: tuple[str, ...]


def find_project_root(start: Path | None = None) -> Path | None:
    current = (start or Path.cwd()).resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / "skills-lock.json").is_file() or (candidate / ".git").exists():
            return candidate
    return None


def _global_roots(home: Path) -> tuple[Path, ...]:
    return (
        home / ".agents" / "skills",
        home / ".codex" / "skills",
        home / ".claude" / "skills",
    )


def _global_candidates(home: Path, name: str) -> tuple[Path, ...]:
    return tuple(root / name for root in _global_roots(home))


def _existing_unique(paths: tuple[Path, ...]) -> tuple[Path, ...]:
    unique: list[Path] = []
    resolved: set[Path] = set()
    for path in paths:
        if not path.is_dir() or not (path / "SKILL.md").is_file():
            continue
        identity = path.resolve()
        if identity not in resolved:
            resolved.add(identity)
            unique.append(path)
    return tuple(unique)


def global_skill_state(skill: SkillSpec, home: Path) -> SkillState:
    expected = skill.content_sha256 or ""
    paths = _existing_unique(_global_candidates(home, skill.name))
    if not paths:
        return SkillState(
            skill.name, "global", "missing", skill.update_policy, expected, None, ()
        )
    hashes = tuple(hash_tree(path.resolve()) for path in paths)
    if not expected:
        status = "unverified"
    else:
        status = "current" if all(value == expected for value in hashes) else "drift"
    return SkillState(
        skill.name,
        "global",
        status,
        skill.update_policy,
        expected,
        hashes[0],
        paths,
    )


def global_skill_states(catalog: Catalog, home: Path | None = None) -> list[SkillState]:
    selected_home = home or runtime_home()
    states = [
        global_skill_state(catalog.skills[name], selected_home)
        for name in catalog.global_profile.skills
    ]
    managed_names = set(catalog.global_profile.skills)
    unmanaged_names = sorted(
        {
            path.name
            for root in _global_roots(selected_home)
            if root.is_dir()
            for path in root.iterdir()
            if path.name not in managed_names
            and not path.name.startswith(".")
            and path.is_dir()
            and (path / "SKILL.md").is_file()
        }
    )
    for name in unmanaged_names:
        paths = _existing_unique(_global_candidates(selected_home, name))
        if paths:
            states.append(
                SkillState(
                    name,
                    "global",
                    "unmanaged",
                    "unknown",
                    "",
                    hash_tree(paths[0].resolve()),
                    paths,
                )
            )
    return states


def _read_lock(project: Path) -> dict[str, object] | None:
    path = project / "skills-lock.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MusterctlError(
            "project_lock_invalid",
            f"The project skill lock is unreadable: {exc}",
            EXIT_ENVIRONMENT,
            {"path": path},
            ("repair or regenerate skills-lock.json",),
        ) from exc
    if not isinstance(data, dict) or not isinstance(data.get("skills"), dict):
        raise MusterctlError(
            "project_lock_invalid",
            "The project skill lock does not contain a skills object.",
            EXIT_ENVIRONMENT,
            {"path": path},
            ("repair or regenerate skills-lock.json",),
        )
    return data


def project_skill_states(catalog: Catalog, project: Path) -> list[SkillState]:
    lock = _read_lock(project)
    canonical = project / ".agents" / "skills"
    if lock is None:
        if not canonical.is_dir():
            return []
        return [
            SkillState(
                path.name,
                "project",
                "unmanaged",
                "unknown",
                "",
                hash_tree(path),
                (path,),
            )
            for path in sorted(canonical.iterdir())
            if path.is_dir() and (path / "SKILL.md").is_file()
        ]
    locked = lock["skills"]
    assert isinstance(locked, dict)
    states: list[SkillState] = []
    for name, raw_entry in sorted(locked.items()):
        if not isinstance(name, str) or not isinstance(raw_entry, dict):
            raise MusterctlError(
                "project_lock_invalid",
                "A project skill lock entry is malformed.",
                EXIT_ENVIRONMENT,
                {"path": project / "skills-lock.json"},
            )
        expected = raw_entry.get("content_sha256")
        policy = raw_entry.get("update_policy")
        if not isinstance(expected, str) or not isinstance(policy, str):
            raise MusterctlError(
                "project_lock_invalid",
                f"The lock entry for {name} lacks hash or policy metadata.",
                EXIT_ENVIRONMENT,
                {"path": project / "skills-lock.json"},
            )
        path = canonical / name
        if not path.is_dir() or not (path / "SKILL.md").is_file():
            states.append(
                SkillState(name, "project", "missing", policy, expected, None, ())
            )
            continue
        actual = hash_tree(path)
        status = "current" if actual == expected else "drift"
        configured = catalog.skills.get(name)
        if (
            status == "current"
            and policy == "latest"
            and configured is not None
            and configured.content_sha256
            and configured.content_sha256 != expected
        ):
            status = "update"
        states.append(
            SkillState(name, "project", status, policy, expected, actual, (path,))
        )
    if canonical.is_dir():
        states.extend(
            SkillState(
                path.name,
                "project",
                "unmanaged",
                "unknown",
                "",
                hash_tree(path.resolve()),
                (path,),
            )
            for path in sorted(canonical.iterdir())
            if path.name not in locked
            and path.is_dir()
            and (path / "SKILL.md").is_file()
        )
    return states


class SkillsManager:
    def __init__(self, catalog: Catalog, home: Path | None = None) -> None:
        self.catalog = catalog
        self.home = home or runtime_home()

    def statuses(self) -> list[SkillState]:
        return global_skill_states(self.catalog, self.home)

    def install_command(
        self,
        skill: SkillSpec,
        *,
        global_scope: bool = True,
    ) -> tuple[str, ...]:
        command = [
            "npx",
            "-y",
            "skills",
            "add",
            skill.source,
            "--skill",
            skill.source_skill,
        ]
        if global_scope:
            command.append("--global")
        command.extend(("--copy", "--yes"))
        for agent in self.catalog.global_profile.agents:
            command.extend(("--agent", agent))
        return tuple(command)

    def plan(self) -> list[SyncAction]:
        actions: list[SyncAction] = []
        for state in self.statuses():
            if state.status in {"current", "unmanaged"}:
                continue
            skill = self.catalog.skills[state.name]
            operation = "install" if state.status == "missing" else "repair"
            actions.append(SyncAction(skill, operation, self.install_command(skill)))
        return actions

    @staticmethod
    def run_install(
        command: tuple[str, ...],
        cwd: Path | None = None,
        home: Path | None = None,
    ) -> None:
        environment = os.environ.copy()
        environment["DO_NOT_TRACK"] = "1"
        environment["NO_COLOR"] = "1"
        if home is not None:
            environment["HOME"] = str(home)
        try:
            result = subprocess.run(
                command,
                cwd=cwd,
                check=False,
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                env=environment,
            )
        except OSError as exc:
            raise MusterctlError(
                "skills_cli_unavailable",
                f"The Skills CLI could not be started: {exc}",
                EXIT_ENVIRONMENT,
                next_actions=("ensure Node.js and npx are available",),
            ) from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise MusterctlError(
                "skill_sync_failed",
                detail or "The Skills CLI returned a nonzero exit status.",
                EXIT_ENVIRONMENT,
                {"exit_code": result.returncode},
                ("resolve the reported installer error",),
            )

    def apply(self, actions: list[SyncAction]) -> None:
        selected_home = self.home if os.environ.get("MUSTERCTL_HOME") else None
        for action in actions:
            self.run_install(action.command, home=selected_home)
        remaining = self.plan()
        if remaining:
            raise MusterctlError(
                "skill_sync_incomplete",
                "The installer completed but the global profile still differs "
                "from the catalog.",
                EXIT_ENVIRONMENT,
                {"skills": ",".join(action.skill.name for action in remaining)},
                ("musterctl skills status", "musterctl skills diff <skill>"),
            )


def _diff_directories(expected_root: Path, installed: Path) -> tuple[list[str], bool]:
    expected_files = {
        path.relative_to(expected_root).as_posix(): path
        for path in expected_root.rglob("*")
        if path.is_file()
        and not path.is_symlink()
        and ".git" not in path.relative_to(expected_root).parts
    }
    actual_root = installed.resolve()
    actual_files = {
        path.relative_to(actual_root).as_posix(): path
        for path in actual_root.rglob("*")
        if path.is_file() and not path.is_symlink()
    }
    lines: list[str] = []
    for relative in sorted(set(expected_files) | set(actual_files)):
        expected_path = expected_files.get(relative)
        actual_path = actual_files.get(relative)
        if expected_path is None:
            lines.append(f"only_installed {relative}")
            continue
        if actual_path is None:
            lines.append(f"only_source {relative}")
            continue
        expected_bytes = expected_path.read_bytes()
        actual_bytes = actual_path.read_bytes()
        if expected_bytes == actual_bytes:
            continue
        try:
            expected_text = expected_bytes.decode("utf-8").splitlines()
            actual_text = actual_bytes.decode("utf-8").splitlines()
        except UnicodeDecodeError:
            lines.append(f"binary_diff {relative}")
            continue
        lines.extend(
            difflib.unified_diff(
                expected_text,
                actual_text,
                fromfile=f"source/{relative}",
                tofile=f"installed/{relative}",
                lineterm="",
            )
        )
    truncated = len(lines) > 400
    return lines[:400], truncated


def skill_diff(catalog: Catalog, name: str, installed: Path) -> tuple[list[str], bool]:
    skill = catalog.skill(name)
    with materialized_source(
        skill.source_url,
        skill.pin or "HEAD",
        skill.source_path,
        skill.content_sha256,
    ) as expected:
        return _diff_directories(expected, installed)
