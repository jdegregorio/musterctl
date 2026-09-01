"""Transactional project planning and materialization."""

from __future__ import annotations

import ctypes
import errno
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from musterctl.catalog import Catalog, SkillSpec, TemplateSpec
from musterctl.errors import EXIT_CONFLICT, EXIT_ENVIRONMENT, MusterctlError
from musterctl.hashing import hash_tree
from musterctl.sources import copy_source
from musterctl.state import SkillsManager

_PROJECT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_AT_FDCWD = -100
_RENAME_NOREPLACE = 1
_RENAME_EXCL = 4


def _publish_noreplace(source: Path, destination: Path) -> None:
    """Atomically rename source while refusing to replace any destination."""
    if os.name == "nt":  # pragma: no cover - exercised on Windows
        source.rename(destination)
        return

    libc = ctypes.CDLL(None, use_errno=True)
    source_bytes = os.fsencode(source)
    destination_bytes = os.fsencode(destination)
    if sys.platform.startswith("linux"):  # pragma: no cover - exercised in Linux CI
        try:
            rename = libc.renameat2
        except AttributeError as exc:  # pragma: no cover - obsolete libc
            raise OSError(
                errno.ENOTSUP,
                "The platform does not expose atomic no-replace rename.",
                destination,
            ) from exc
        rename.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        rename.restype = ctypes.c_int
        result = rename(
            _AT_FDCWD,
            source_bytes,
            _AT_FDCWD,
            destination_bytes,
            _RENAME_NOREPLACE,
        )
    elif sys.platform == "darwin":  # pragma: no cover - exercised in macOS CI
        rename = libc.renamex_np
        rename.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint)
        rename.restype = ctypes.c_int
        result = rename(source_bytes, destination_bytes, _RENAME_EXCL)
    else:  # pragma: no cover - supported runtime platforms are tested in CI
        raise OSError(
            errno.ENOTSUP,
            "The platform does not support atomic no-replace publication.",
            destination,
        )
    if result != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number), destination)


@dataclass(frozen=True, slots=True)
class ProjectPlan:
    name: str
    module_name: str
    destination: Path
    template: TemplateSpec
    skills: tuple[SkillSpec, ...]
    actions: tuple[str, ...]


class ProjectInitializer:
    def __init__(self, catalog: Catalog) -> None:
        self.catalog = catalog

    def plan(
        self,
        name: str,
        template_name: str,
        requested_skills: list[str],
        use_defaults: bool,
        parent: Path,
    ) -> ProjectPlan:
        if not _PROJECT_NAME.fullmatch(name) or name in {".", ".."}:
            raise MusterctlError(
                "invalid_project_name",
                "Project names must be one safe path component.",
                fields={"project": name},
                next_actions=(
                    "choose a name using letters, digits, dots, dashes, or underscores",
                ),
            )
        resolved_parent = parent.expanduser().resolve()
        if not resolved_parent.is_dir():
            raise MusterctlError(
                "parent_missing",
                "The parent directory does not exist.",
                EXIT_CONFLICT,
                {"path": resolved_parent},
                ("create or choose an existing parent directory",),
            )
        destination = resolved_parent / name
        if destination.exists() or destination.is_symlink():
            raise MusterctlError(
                "destination_exists",
                "The project destination already exists and will not be overwritten.",
                EXIT_CONFLICT,
                {"path": destination},
                ("choose another project name", "inspect the existing destination"),
            )
        template = self.catalog.template(template_name)
        names: list[str] = []
        if use_defaults:
            names.extend(template.recommended_skills)
        names.extend(requested_skills)
        names = list(dict.fromkeys(names))
        selected: list[SkillSpec] = []
        for skill_name in names:
            skill = self.catalog.skill(skill_name)
            if skill_name in self.catalog.global_profile.skills:
                raise MusterctlError(
                    "skill_already_global",
                    f"{skill_name} is provided by the global profile and must "
                    "not be duplicated.",
                    EXIT_CONFLICT,
                    {"skill": skill_name},
                    (f"omit --skill {skill_name}",),
                )
            if "project" not in skill.scopes:
                raise MusterctlError(
                    "skill_not_project_installable",
                    f"{skill_name} is not approved for project installation.",
                    EXIT_CONFLICT,
                    {"skill": skill_name},
                    ("musterctl skills available",),
                )
            selected.append(skill)
        actions = [
            "create project directory",
            f"materialize {template.name} template",
            "initialize git repository",
        ]
        if selected:
            actions.extend(
                (
                    f"install {len(selected)} project skills",
                    "create Claude skill adapters",
                )
            )
        actions.extend(("write skills-lock.json", "validate agent environment"))
        module_name = re.sub(r"[^A-Za-z0-9_]", "_", name.replace("-", "_"))
        if module_name[0].isdigit():
            module_name = f"project_{module_name}"
        return ProjectPlan(
            name,
            module_name.lower(),
            destination,
            template,
            tuple(selected),
            tuple(actions),
        )

    def apply(self, plan: ProjectPlan) -> None:
        temporary = Path(
            tempfile.mkdtemp(
                prefix=f".{plan.name}.musterctl-", dir=plan.destination.parent
            )
        )
        try:
            for layer in plan.template.layers:
                configured = self.catalog.template_layer(layer)
                copy_source(
                    configured.source_url,
                    configured.revision,
                    configured.source_path,
                    configured.content_sha256,
                    temporary,
                )
            tokens = {
                "{{PROJECT_NAME}}": plan.name,
                "{{PROJECT_MODULE}}": plan.module_name,
                "__PROJECT_MODULE__": plan.module_name,
            }
            self._replace_tokens(temporary, tokens)
            self._install_skills(temporary, plan)
            self._write_lock(temporary, plan)
            self._run(
                ("git", "init", "--quiet", "-b", "main"),
                temporary,
                "git_initialization_failed",
            )
            check = temporary / "scripts" / "check"
            self._run((str(check),), temporary, "project_validation_failed")
            shutil.rmtree(temporary / ".cache", ignore_errors=True)
            if plan.destination.exists() or plan.destination.is_symlink():
                raise MusterctlError(
                    "destination_exists",
                    "The destination appeared during initialization and was "
                    "not overwritten.",
                    EXIT_CONFLICT,
                    {"path": plan.destination},
                )
            try:
                _publish_noreplace(temporary, plan.destination)
            except FileExistsError as exc:
                raise MusterctlError(
                    "destination_exists",
                    "The destination appeared during initialization and was "
                    "not overwritten.",
                    EXIT_CONFLICT,
                    {"path": plan.destination},
                ) from exc
        except OSError as exc:
            raise MusterctlError(
                "project_initialization_failed",
                f"Project initialization failed: {exc}",
                EXIT_ENVIRONMENT,
                {"path": plan.destination},
            ) from exc
        finally:
            shutil.rmtree(temporary, ignore_errors=True)

    @staticmethod
    def _replace_tokens(root: Path, tokens: dict[str, str]) -> None:
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            content = path.read_bytes()
            if b"\0" in content:
                continue
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError:
                continue
            rendered = text
            for token, value in tokens.items():
                rendered = rendered.replace(token, value)
            if rendered != text:
                path.write_text(rendered, encoding="utf-8")
        for path in sorted(
            root.rglob("*"), key=lambda item: len(item.parts), reverse=True
        ):
            rendered_name = path.name
            for token, value in tokens.items():
                rendered_name = rendered_name.replace(token, value)
            if rendered_name != path.name:
                path.rename(path.with_name(rendered_name))

    def _install_skills(self, root: Path, plan: ProjectPlan) -> None:
        manager = SkillsManager(self.catalog)
        for skill in plan.skills:
            manager.install_verified(skill, global_scope=False, cwd=root)
            installed = root / ".agents" / "skills" / skill.name
            if not installed.is_dir() or not (installed / "SKILL.md").is_file():
                raise MusterctlError(
                    "project_skill_missing",
                    "The Skills CLI completed without materializing the project skill.",
                    EXIT_ENVIRONMENT,
                    {"skill": skill.name, "path": installed},
                )
            actual_hash = hash_tree(installed)
            if skill.content_sha256 and actual_hash != skill.content_sha256:
                raise MusterctlError(
                    "project_skill_digest_mismatch",
                    "The installed project skill does not match the catalog digest.",
                    EXIT_ENVIRONMENT,
                    {
                        "skill": skill.name,
                        "expected": skill.content_sha256,
                        "actual": actual_hash,
                    },
                )

    def _write_lock(self, root: Path, plan: ProjectPlan) -> None:
        entries = {
            skill.name: {
                "content_sha256": hash_tree(root / ".agents" / "skills" / skill.name),
                "ownership": skill.ownership,
                "path": f".agents/skills/{skill.name}",
                "source": skill.source,
                "source_pin": skill.pin,
                "source_skill": skill.source_skill,
                "update_policy": skill.update_policy,
            }
            for skill in plan.skills
        }
        lock = {
            "catalog_version": self.catalog.version,
            "skills": entries,
            "template": plan.template.name,
            "version": 1,
        }
        (root / "skills-lock.json").write_text(
            json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    @staticmethod
    def _run(command: tuple[str, ...], cwd: Path, error_code: str) -> None:
        environment = os.environ.copy()
        environment["NO_COLOR"] = "1"
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
                error_code,
                f"Could not run {command[0]}: {exc}",
                EXIT_ENVIRONMENT,
            ) from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise MusterctlError(
                error_code,
                detail or f"{command[0]} exited with status {result.returncode}.",
                EXIT_ENVIRONMENT,
                {"exit_code": result.returncode},
            )
