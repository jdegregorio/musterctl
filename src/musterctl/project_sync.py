"""Plan and transactionally advance managed skill copies across projects."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from musterctl.catalog import Catalog, SkillSpec
from musterctl.errors import EXIT_CONFLICT, EXIT_ENVIRONMENT, MusterctlError
from musterctl.hashing import hash_tree
from musterctl.inventory import SkillInstallation, project_installations
from musterctl.sources import copy_source

_AGENT_SKILL_ROOTS = {
    "claude-code": ".claude/skills",
    "codex": ".codex/skills",
}


@dataclass(frozen=True, slots=True)
class ProjectSyncAction:
    project: Path
    skill: SkillSpec | None
    name: str
    operation: str
    path: Path
    reason: str


def _lock_entry(
    skill: SkillSpec, path: str, adapters: tuple[str, ...]
) -> dict[str, object]:
    return {
        "adapters": list(adapters),
        "content_sha256": skill.content_sha256,
        "ownership": skill.ownership,
        "path": path,
        "source": skill.source,
        "source_pin": skill.pin,
        "source_url": skill.source_url,
        "source_path": skill.source_path,
        "source_ref": skill.source_ref,
        "source_skill": skill.source_skill,
        "update_policy": skill.update_policy,
    }


class ProjectSkillsManager:
    def __init__(self, catalog: Catalog, projects: tuple[Path, ...]) -> None:
        self.catalog = catalog
        self.projects = projects

    def installations(self) -> list[SkillInstallation]:
        return project_installations(self.catalog, self.projects)

    def plan(
        self,
        *,
        names: tuple[str, ...] = (),
        replace_drift: bool = False,
    ) -> list[ProjectSyncAction]:
        selected = set(names)
        observed: set[str] = set()
        actions: list[ProjectSyncAction] = []
        for installation in self.installations():
            if selected and installation.name not in selected:
                continue
            observed.add(installation.name)
            project = installation.project
            if project is None:  # Project inventory guarantees this invariant.
                continue
            path = project / ".agents" / "skills" / installation.name
            if installation.lineage != "tracked":
                continue
            skill = self.catalog.skills.get(installation.name)
            if skill is None:
                actions.append(
                    ProjectSyncAction(
                        project,
                        None,
                        installation.name,
                        "blocked_not_in_catalog",
                        path,
                        "the managed project copy is no longer in the catalog",
                    )
                )
                continue
            if installation.name in self.catalog.global_profile.skills:
                actions.append(
                    ProjectSyncAction(
                        project,
                        skill,
                        installation.name,
                        "blocked_now_global",
                        path,
                        "the catalog now provides this skill globally",
                    )
                )
                continue
            if "project" not in skill.scopes:
                actions.append(
                    ProjectSyncAction(
                        project,
                        skill,
                        installation.name,
                        "blocked_scope",
                        path,
                        "the catalog no longer allows project installation",
                    )
                )
                continue
            if installation.catalog_status == "local_changes" and not replace_drift:
                actions.append(
                    ProjectSyncAction(
                        project,
                        skill,
                        installation.name,
                        "blocked_local_changes",
                        path,
                        "project content differs from its lock; move the change to "
                        "source before replacement",
                    )
                )
                continue
            if installation.catalog_status == "current":
                continue
            if installation.catalog_status == "catalog_match_untracked":
                continue
            if (
                installation.content_sha256 == skill.content_sha256
                and installation.catalog_status
                not in {"adapter_missing", "adapter_update"}
            ):
                operation = "refresh_lock"
                reason = "installed content matches the catalog but lineage is stale"
            elif installation.content_sha256 is None:
                operation = "install"
                reason = "managed project skill is missing"
            else:
                operation = "replace"
                reason = "catalog has a different verified source revision"
            actions.append(
                ProjectSyncAction(
                    project,
                    skill,
                    installation.name,
                    operation,
                    path,
                    reason,
                )
            )
        missing = sorted(selected - observed)
        if missing:
            raise MusterctlError(
                "project_skill_not_found",
                "A requested skill is not managed by any selected project.",
                fields={"skills": ",".join(missing)},
                next_actions=("musterctl projects status",),
            )
        return actions

    def apply(self, actions: list[ProjectSyncAction]) -> None:
        blocked = [
            action for action in actions if action.operation.startswith("blocked_")
        ]
        if blocked:
            first = blocked[0]
            raise MusterctlError(
                first.operation,
                "Project skill reconciliation is blocked; no project was changed.",
                EXIT_CONFLICT,
                {
                    "project": first.project,
                    "skill": first.name,
                    "reason": first.reason,
                },
                (
                    f"cd {first.project} && musterctl skills diff {first.name}",
                    f"musterctl skills source {first.name}",
                    "use --replace-drift only to discard installed changes",
                ),
            )
        grouped: dict[Path, list[ProjectSyncAction]] = defaultdict(list)
        for action in actions:
            grouped[action.project].append(action)
        for project, project_actions in sorted(grouped.items()):
            self._apply_project(project, project_actions)

    def _apply_project(self, project: Path, actions: list[ProjectSyncAction]) -> None:
        lock_path = project / "skills-lock.json"
        try:
            original_lock = lock_path.read_bytes()
            lock = json.loads(original_lock)
        except (OSError, json.JSONDecodeError) as exc:
            raise MusterctlError(
                "project_lock_invalid",
                f"The project skill lock cannot be updated: {exc}",
                EXIT_ENVIRONMENT,
                {"path": lock_path},
            ) from exc
        if not isinstance(lock, dict) or not isinstance(lock.get("skills"), dict):
            raise MusterctlError(
                "project_lock_invalid",
                "The project skill lock does not contain a skills object.",
                EXIT_ENVIRONMENT,
                {"path": lock_path},
            )
        raw_skills = lock["skills"]
        assert isinstance(raw_skills, dict)
        transaction = Path(
            tempfile.mkdtemp(prefix=".musterctl-project-sync-", dir=project)
        )
        staged = transaction / "staged"
        backups = transaction / "backups"
        staged.mkdir()
        backups.mkdir()
        replaced: list[tuple[Path, Path | None]] = []
        try:
            for action in actions:
                skill = action.skill
                assert skill is not None
                if action.operation != "refresh_lock":
                    destination = staged / action.name
                    copy_source(
                        skill.source_url,
                        skill.pin or "HEAD",
                        skill.source_path,
                        skill.content_sha256 or "",
                        destination,
                    )
                    if hash_tree(destination) != skill.content_sha256:
                        raise MusterctlError(
                            "project_skill_digest_mismatch",
                            "A staged project skill does not match the catalog.",
                            EXIT_ENVIRONMENT,
                            {"project": project, "skill": action.name},
                        )
            for action in actions:
                skill = action.skill
                assert skill is not None
                adapter_relatives = self._adapter_relatives(action.name)
                if action.operation != "refresh_lock":
                    targets = (
                        action.path,
                        *(project / relative for relative in adapter_relatives),
                    )
                    for index, target in enumerate(targets):
                        target.parent.mkdir(parents=True, exist_ok=True)
                        backup: Path | None = None
                        if target.exists() or target.is_symlink():
                            backup = backups / f"{action.name}-{index}"
                            target.rename(backup)
                        replaced.append((target, backup))
                        shutil.copytree(staged / action.name, target)
                raw_skills[action.name] = _lock_entry(
                    skill,
                    f".agents/skills/{action.name}",
                    adapter_relatives,
                )
            rendered = json.dumps(lock, indent=2, sort_keys=True) + "\n"
            self._write_lock(lock_path, rendered.encode())
            self._run_project_check(project)
        except BaseException:
            for target, backup in reversed(replaced):
                if target.exists() or target.is_symlink():
                    if target.is_symlink() or target.is_file():
                        target.unlink()
                    else:
                        shutil.rmtree(target)
                if backup is not None and (backup.exists() or backup.is_symlink()):
                    backup.rename(target)
            self._write_lock(lock_path, original_lock)
            raise
        finally:
            shutil.rmtree(transaction, ignore_errors=True)

    def _adapter_relatives(self, name: str) -> tuple[str, ...]:
        return tuple(
            f"{_AGENT_SKILL_ROOTS[agent]}/{name}"
            for agent in self.catalog.global_profile.agents
            if agent in _AGENT_SKILL_ROOTS
        )

    @staticmethod
    def _write_lock(path: Path, content: bytes) -> None:
        descriptor, raw_path = tempfile.mkstemp(
            prefix=f".{path.name}.", dir=path.parent
        )
        temporary = Path(raw_path)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _run_project_check(project: Path) -> None:
        check = project / "scripts" / "check"
        if not check.is_file():
            return
        try:
            result = subprocess.run(
                (str(check),),
                cwd=project,
                check=False,
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                env={**os.environ, "NO_COLOR": "1"},
            )
        except OSError as exc:
            raise MusterctlError(
                "project_validation_failed",
                f"The project validation command could not run: {exc}",
                EXIT_ENVIRONMENT,
                {"project": project},
            ) from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise MusterctlError(
                "project_validation_failed",
                detail or "The project validation command failed.",
                EXIT_ENVIRONMENT,
                {"project": project, "exit_code": result.returncode},
            )
