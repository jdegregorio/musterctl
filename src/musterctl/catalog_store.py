"""Deterministic, atomic updates for the external catalog document."""

from __future__ import annotations

import json
import os
import re
import tempfile
import tomllib
from copy import deepcopy
from pathlib import Path
from typing import Any

from musterctl.catalog import Catalog, SkillSpec
from musterctl.errors import EXIT_CONFLICT, EXIT_ENVIRONMENT, MusterctlError
from musterctl.sources import SourceSnapshot, source_selector

_BARE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")


def _key(value: str) -> str:
    return value if _BARE_KEY.fullmatch(value) else json.dumps(value)


def _value(value: object) -> str:
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_value(item) for item in value) + "]"
    raise MusterctlError(
        "catalog_write_unsupported",
        f"The catalog contains an unsupported {type(value).__name__} value.",
        EXIT_ENVIRONMENT,
        next_actions=("edit the unsupported catalog value manually",),
    )


def render_catalog_mapping(raw: dict[str, Any]) -> str:
    """Render the supported catalog schema without a third-party TOML writer."""

    lines: list[str] = []

    def render_table(table: dict[str, Any], path: tuple[str, ...]) -> None:
        scalars = [
            (key, value) for key, value in table.items() if not isinstance(value, dict)
        ]
        children = [
            (key, value) for key, value in table.items() if isinstance(value, dict)
        ]
        if path:
            if lines and lines[-1] != "":
                lines.append("")
            lines.append("[" + ".".join(_key(part) for part in path) + "]")
        for key, value in scalars:
            lines.append(f"{_key(str(key))} = {_value(value)}")
        for key, child in children:
            render_table(child, (*path, str(key)))

    render_table(raw, ())
    rendered = "\n".join(lines).rstrip() + "\n"
    tomllib.loads(rendered)
    return rendered


class CatalogStore:
    """Mutable copy of one validated catalog with compare-and-swap persistence."""

    def __init__(self, catalog: Catalog) -> None:
        self.path = catalog.path
        try:
            self.original = self.path.read_text(encoding="utf-8")
            parsed = tomllib.loads(self.original)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise MusterctlError(
                "catalog_invalid",
                f"The catalog cannot be prepared for editing: {exc}",
                EXIT_ENVIRONMENT,
                {"path": self.path},
            ) from exc
        self.raw: dict[str, Any] = deepcopy(parsed)

    @property
    def skills(self) -> dict[str, dict[str, Any]]:
        value = self.raw.setdefault("skills", {})
        if not isinstance(value, dict):
            raise MusterctlError("catalog_invalid", "The skills table is invalid.")
        return value

    def add_skill(
        self,
        *,
        name: str,
        description: str,
        category: str,
        ownership: str,
        update_policy: str,
        source_url: str,
        source_path: str,
        source_skill: str,
        source_ref: str,
        snapshot: SourceSnapshot,
        scopes: tuple[str, ...],
        global_profile: bool,
        license_name: str | None,
    ) -> None:
        if name in self.skills:
            raise MusterctlError(
                "catalog_skill_exists",
                f"{name} is already in the catalog and was not overwritten.",
                EXIT_CONFLICT,
                {"skill": name},
                (f"musterctl catalog show {name}", f"musterctl catalog update {name}"),
            )
        entry: dict[str, Any] = {
            "description": description,
            "category": category,
            "ownership": ownership,
            "update_policy": update_policy,
            "source": source_selector(source_url, snapshot.revision, source_path),
            "source_url": source_url,
            "source_path": source_path,
            "source_skill": source_skill,
            "source_ref": source_ref,
            "pin": snapshot.revision,
            "content_sha256": snapshot.content_sha256,
            "scope": list(scopes),
        }
        if license_name:
            entry["license"] = license_name
        self.skills[name] = entry
        if global_profile:
            self._set_global(name, True)

    def adopt_skill(
        self,
        skill: SkillSpec,
        *,
        global_profile: bool,
    ) -> None:
        if skill.pin is None or skill.content_sha256 is None:
            raise MusterctlError(
                "source_lineage_incomplete",
                "The installed skill does not have an immutable source pin and digest.",
                EXIT_CONFLICT,
                {"skill": skill.name},
            )
        self.add_skill(
            name=skill.name,
            description=skill.description,
            category=skill.category,
            ownership=skill.ownership,
            update_policy=skill.update_policy,
            source_url=skill.source_url,
            source_path=skill.source_path,
            source_skill=skill.source_skill,
            source_ref=skill.source_ref,
            snapshot=SourceSnapshot(skill.pin, skill.content_sha256),
            scopes=skill.scopes,
            global_profile=global_profile,
            license_name=skill.license,
        )

    def remove_skill(self, name: str) -> tuple[str, ...]:
        if name not in self.skills:
            raise MusterctlError(
                "unknown_skill",
                f"{name} is not in the configured catalog.",
                fields={"skill": name},
            )
        references: list[str] = []
        profiles = self.raw.get("profiles", {})
        if isinstance(profiles, dict):
            for profile_name, profile in profiles.items():
                if not isinstance(profile, dict):
                    continue
                configured = profile.get("skills", [])
                if isinstance(configured, list) and name in configured:
                    profile["skills"] = [item for item in configured if item != name]
                    references.append(f"profile:{profile_name}")
        templates = self.raw.get("templates", {})
        if isinstance(templates, dict):
            for template_name, template in templates.items():
                if not isinstance(template, dict):
                    continue
                for field in ("required_skills", "recommended_skills"):
                    configured = template.get(field, [])
                    if isinstance(configured, list) and name in configured:
                        template[field] = [item for item in configured if item != name]
                        references.append(f"template:{template_name}:{field}")
        del self.skills[name]
        return tuple(references)

    def configure_skill(
        self,
        name: str,
        *,
        scopes: tuple[str, ...] | None,
        global_profile: bool | None,
    ) -> None:
        try:
            entry = self.skills[name]
        except KeyError as exc:
            raise MusterctlError(
                "unknown_skill",
                f"{name} is not in the configured catalog.",
                fields={"skill": name},
            ) from exc
        if scopes is not None:
            entry["scope"] = list(scopes)
        if global_profile is not None:
            if global_profile:
                configured_scopes = entry.setdefault("scope", [])
                if not isinstance(configured_scopes, list):
                    raise MusterctlError(
                        "catalog_invalid", "The skill scope list is invalid."
                    )
                if "global" not in configured_scopes:
                    configured_scopes.append("global")
            self._set_global(name, global_profile)

    def update_skill(
        self,
        name: str,
        snapshot: SourceSnapshot,
        *,
        source_ref: str | None = None,
    ) -> None:
        try:
            entry = self.skills[name]
        except KeyError as exc:
            raise MusterctlError(
                "unknown_skill",
                f"{name} is not in the configured catalog.",
                fields={"skill": name},
            ) from exc
        if source_ref is not None:
            entry["source_ref"] = source_ref
        selected_ref = str(entry.get("source_ref", "HEAD"))
        entry["pin"] = snapshot.revision
        entry["content_sha256"] = snapshot.content_sha256
        entry["source"] = source_selector(
            str(entry["source_url"]), snapshot.revision, str(entry["source_path"])
        )
        entry["source_ref"] = selected_ref

    def _set_global(self, name: str, enabled: bool) -> None:
        profiles = self.raw.setdefault("profiles", {})
        if not isinstance(profiles, dict):
            raise MusterctlError("catalog_invalid", "The profiles table is invalid.")
        profile = profiles.setdefault(
            "global", {"agents": ["codex", "claude-code"], "skills": []}
        )
        if not isinstance(profile, dict):
            raise MusterctlError("catalog_invalid", "The global profile is invalid.")
        configured = profile.setdefault("skills", [])
        if not isinstance(configured, list):
            raise MusterctlError(
                "catalog_invalid", "The global skills list is invalid."
            )
        if enabled and name not in configured:
            configured.append(name)
        if not enabled:
            profile["skills"] = [item for item in configured if item != name]

    def validate(self) -> Catalog:
        return Catalog.from_mapping(self.path, self.raw)

    def rendered(self) -> str:
        self.validate()
        return render_catalog_mapping(self.raw)

    def write(self) -> Path:
        content = self.rendered()
        try:
            current = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            raise MusterctlError(
                "catalog_write_failed",
                f"The catalog cannot be read before writing: {exc}",
                EXIT_ENVIRONMENT,
                {"path": self.path},
            ) from exc
        if current != self.original:
            raise MusterctlError(
                "catalog_changed",
                "The catalog changed while the command was running and was not "
                "overwritten.",
                EXIT_CONFLICT,
                {"path": self.path},
                ("review the concurrent change and rerun the command",),
            )
        descriptor: int | None = None
        temporary: Path | None = None
        try:
            descriptor, raw_path = tempfile.mkstemp(
                prefix=f".{self.path.name}.", dir=self.path.parent
            )
            temporary = Path(raw_path)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                descriptor = None
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.chmod(self.path.stat().st_mode & 0o777)
            temporary.replace(self.path)
            temporary = None
        except OSError as exc:
            raise MusterctlError(
                "catalog_write_failed",
                f"The catalog could not be updated atomically: {exc}",
                EXIT_ENVIRONMENT,
                {"path": self.path},
                (
                    "edit the authoritative catalog source or pass --catalog to it",
                    "do not edit a generated Home Manager target",
                ),
            ) from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return self.path
