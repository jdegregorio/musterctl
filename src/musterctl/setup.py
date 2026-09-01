"""Bootstrap an external catalog from existing Skills CLI installations."""

from __future__ import annotations

import json
import os
import re
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path

from musterctl.errors import EXIT_CONFLICT, EXIT_ENVIRONMENT, MusterctlError
from musterctl.hashing import hash_tree
from musterctl.resources import config_catalog_path, runtime_home

_DESCRIPTION = re.compile(r"(?m)^description:\s*[\"']?([^\n\"']+)")


@dataclass(frozen=True, slots=True)
class InstalledSkill:
    name: str
    path: Path | None
    lineage: str
    source: str | None
    source_url: str | None
    source_path: str | None
    source_skill: str
    installer_hash: str | None
    content_sha256: str | None
    description: str
    scope: str = "global"
    project: Path | None = None
    source_pin: str | None = None
    source_ref: str = "HEAD"


def _read_skills_lock(home: Path) -> dict[str, object]:
    path = home / ".agents" / ".skill-lock.json"
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MusterctlError(
            "skills_lock_invalid",
            f"The Skills CLI lock is unreadable: {exc}",
            EXIT_ENVIRONMENT,
            {"path": path},
            ("repair the Skills CLI lock before importing it",),
        ) from exc
    skills = raw.get("skills") if isinstance(raw, dict) else None
    if skills is None:
        return {}
    if not isinstance(skills, dict):
        raise MusterctlError(
            "skills_lock_invalid",
            "The Skills CLI lock has no valid skills mapping.",
            EXIT_ENVIRONMENT,
            {"path": path},
        )
    return skills


def _global_roots(home: Path) -> tuple[Path, ...]:
    return (
        home / ".agents" / "skills",
        home / ".codex" / "skills",
        home / ".claude" / "skills",
    )


def _installed_paths(home: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    identities: set[Path] = set()
    for root in _global_roots(home):
        if not root.is_dir():
            continue
        for candidate in sorted(root.iterdir()):
            if candidate.name.startswith("."):
                continue
            skill_file = candidate / "SKILL.md"
            if not candidate.is_dir() or not skill_file.is_file():
                continue
            identity = candidate.resolve()
            if identity in identities:
                continue
            identities.add(identity)
            result.setdefault(candidate.name, candidate)
    return result


def _description(path: Path | None, name: str) -> str:
    if path is None:
        return f"Imported {name} skill"
    try:
        match = _DESCRIPTION.search((path / "SKILL.md").read_text(encoding="utf-8"))
    except OSError:
        match = None
    return match.group(1).strip() if match else f"Imported {name} skill"


def inspect_installed_skills(home: Path | None = None) -> list[InstalledSkill]:
    selected_home = home or runtime_home()
    installed = _installed_paths(selected_home)
    lock = _read_skills_lock(selected_home)
    result: list[InstalledSkill] = []
    tracked: set[str] = set()
    for name, raw_entry in sorted(lock.items()):
        if not isinstance(name, str) or not isinstance(raw_entry, dict):
            continue
        tracked.add(name)
        path = installed.get(name)
        raw_skill_path = raw_entry.get("skillPath")
        source_path = (
            Path(raw_skill_path).parent.as_posix()
            if isinstance(raw_skill_path, str)
            else None
        )
        result.append(
            InstalledSkill(
                name=name,
                path=path,
                lineage="tracked",
                source=(str(raw_entry["source"]) if raw_entry.get("source") else None),
                source_url=(
                    str(raw_entry["sourceUrl"]) if raw_entry.get("sourceUrl") else None
                ),
                source_path=source_path,
                source_skill=name,
                installer_hash=(
                    str(raw_entry["skillFolderHash"])
                    if raw_entry.get("skillFolderHash")
                    else None
                ),
                content_sha256=hash_tree(path.resolve()) if path else None,
                description=_description(path, name),
            )
        )
    result.extend(
        InstalledSkill(
            name=name,
            path=path,
            lineage="untracked",
            source=None,
            source_url=None,
            source_path=None,
            source_skill=name,
            installer_hash=None,
            content_sha256=hash_tree(path.resolve()),
            description=_description(path, name),
        )
        for name, path in sorted(installed.items())
        if name not in tracked
    )
    return result


def select_installed_skills(
    candidates: list[InstalledSkill],
    includes: list[str],
    all_tracked: bool,
    include_paths: list[Path] | None = None,
) -> list[InstalledSkill]:
    by_name: dict[str, list[InstalledSkill]] = {}
    by_path: dict[Path, InstalledSkill] = {}
    for candidate in candidates:
        by_name.setdefault(candidate.name, []).append(candidate)
        if candidate.path is not None:
            by_path[candidate.path.resolve()] = candidate
    selected: list[InstalledSkill] = [
        candidate
        for candidate in candidates
        if all_tracked and candidate.lineage == "tracked" and candidate.path is not None
    ]
    unknown = [name for name in includes if name not in by_name]
    if unknown:
        raise MusterctlError(
            "unknown_installed_skill",
            "One or more requested installed skills were not found.",
            fields={"skills": ",".join(unknown)},
            next_actions=("musterctl setup inspect",),
        )
    ambiguous = [name for name in includes if len(by_name[name]) > 1]
    if ambiguous:
        raise MusterctlError(
            "installed_skill_ambiguous",
            "A selected name has multiple installed variants.",
            EXIT_CONFLICT,
            {"skills": ",".join(ambiguous)},
            ("select the exact installation with --include-path",),
        )
    selected.extend(by_name[name][0] for name in includes)
    for raw_path in include_paths or []:
        path = raw_path.expanduser().resolve()
        try:
            selected.append(by_path[path])
        except KeyError as exc:
            raise MusterctlError(
                "unknown_installed_path",
                "A requested installed skill path was not found.",
                fields={"path": path},
                next_actions=("musterctl setup inspect",),
            ) from exc
    selected = list(dict.fromkeys(selected))
    conflicting_names = [
        name
        for name in {candidate.name for candidate in selected}
        if len(
            {
                candidate.content_sha256
                for candidate in selected
                if candidate.name == name
            }
        )
        > 1
    ]
    if conflicting_names:
        raise MusterctlError(
            "catalog_name_conflict",
            "The selected installations use the same name for different content.",
            EXIT_CONFLICT,
            {"skills": ",".join(sorted(conflicting_names))},
            ("keep one variant or rename and source them independently",),
        )
    deduplicated: dict[str, InstalledSkill] = {}
    for candidate in selected:
        current = deduplicated.get(candidate.name)
        if current is None or (
            current.scope != "global" and candidate.scope == "global"
        ):
            deduplicated[candidate.name] = candidate
    selected = list(deduplicated.values())
    unusable = [
        item.name
        for item in selected
        if item.lineage != "tracked"
        or item.path is None
        or item.source is None
        or item.source_url is None
        or item.source_path is None
        or item.content_sha256 is None
    ]
    if unusable:
        raise MusterctlError(
            "source_lineage_missing",
            "Only installed skills with Skills CLI source lineage can be imported.",
            EXIT_CONFLICT,
            {"skills": ",".join(unusable)},
            (
                "keep no-source skills unmanaged for now",
                "use gh-axi to create a dedicated source repository, then add it",
            ),
        )
    return selected


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _toml_array(values: list[str]) -> str:
    return "[" + ", ".join(_toml_string(value) for value in values) + "]"


def render_initial_catalog(skills: list[InstalledSkill]) -> str:
    global_names = [skill.name for skill in skills if skill.scope == "global"]
    lines = [
        "version = 1",
        "",
        "[profiles.global]",
        'agents = ["codex", "claude-code"]',
        f"skills = {_toml_array(global_names)}",
    ]
    for skill in skills:
        assert skill.source is not None
        assert skill.source_url is not None
        assert skill.source_path is not None
        assert skill.content_sha256 is not None
        lines.extend(
            (
                "",
                f"[skills.{_toml_string(skill.name)}]",
                f"description = {_toml_string(skill.description)}",
                'category = "Imported"',
                'ownership = "imported"',
                (
                    'update_policy = "pinned"'
                    if skill.source_pin
                    else 'update_policy = "latest"'
                ),
                f"source = {_toml_string(skill.source)}",
                f"source_url = {_toml_string(skill.source_url)}",
                f"source_path = {_toml_string(skill.source_path)}",
                f"source_skill = {_toml_string(skill.source_skill)}",
                f"source_ref = {_toml_string(skill.source_ref)}",
                *(
                    (f"pin = {_toml_string(skill.source_pin)}",)
                    if skill.source_pin
                    else ()
                ),
                f"content_sha256 = {_toml_string(skill.content_sha256)}",
                f"scope = {_toml_array([skill.scope])}",
            )
        )
    lines.extend(("", "[template_layers]", "", "[templates]", ""))
    rendered = "\n".join(lines)
    tomllib.loads(rendered)
    return rendered


def inspect_device_skills(
    *,
    catalog: object | None = None,
    search_roots: tuple[Path, ...] = (),
    projects: tuple[Path, ...] = (),
    home: Path | None = None,
) -> list[InstalledSkill]:
    """Return setup candidates from global and project inventory."""

    from musterctl.catalog import Catalog
    from musterctl.inventory import inventory

    selected_catalog = catalog if isinstance(catalog, Catalog) else None
    installations = inventory(
        selected_catalog,
        search_roots=search_roots,
        projects=projects,
        home=home,
    )
    candidates = [
        InstalledSkill(
            name=installation.name,
            path=installation.paths[0] if installation.paths else None,
            lineage=installation.lineage,
            source=installation.source,
            source_url=installation.source_url,
            source_path=installation.source_path,
            source_skill=installation.source_skill,
            installer_hash=None,
            content_sha256=installation.content_sha256,
            description=_description(
                installation.paths[0] if installation.paths else None,
                installation.name,
            ),
            scope=installation.scope,
            project=installation.project,
            source_pin=installation.source_pin,
            source_ref=installation.source_ref,
        )
        for installation in installations
    ]
    return candidates


def write_initial_catalog(
    content: str,
    output: Path | None = None,
) -> Path:
    destination = (output or config_catalog_path()).expanduser().resolve()
    if destination.exists() or destination.is_symlink():
        raise MusterctlError(
            "catalog_exists",
            "The catalog destination already exists and will not be overwritten.",
            EXIT_CONFLICT,
            {"path": destination},
            ("review or remove the existing catalog explicitly",),
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_temporary = tempfile.mkstemp(
        prefix=f".{destination.name}.", dir=destination.parent
    )
    temporary = Path(raw_temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, destination)
        except FileExistsError as exc:
            raise MusterctlError(
                "catalog_exists",
                "The catalog destination appeared and was not overwritten.",
                EXIT_CONFLICT,
                {"path": destination},
            ) from exc
    finally:
        temporary.unlink(missing_ok=True)
    return destination
