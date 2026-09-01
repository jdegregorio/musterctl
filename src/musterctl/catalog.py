"""Validated external catalog model and discovery operations."""

from __future__ import annotations

import difflib
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from musterctl.errors import EXIT_ENVIRONMENT, MusterctlError
from musterctl.resources import catalog_path

_SHA = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True, slots=True)
class SkillSpec:
    name: str
    description: str
    category: str
    ownership: str
    update_policy: str
    source: str
    source_url: str
    source_path: str
    source_skill: str
    source_ref: str
    scopes: tuple[str, ...]
    pin: str | None = None
    license: str | None = None
    content_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class TemplateLayerSpec:
    name: str
    source_url: str
    revision: str
    source_path: str
    content_sha256: str


@dataclass(frozen=True, slots=True)
class TemplateSpec:
    name: str
    category: str
    description: str
    layers: tuple[str, ...]
    required_skills: tuple[str, ...]
    recommended_skills: tuple[str, ...]
    optional_categories: tuple[str, ...]
    skill_manifest: str | None


@dataclass(frozen=True, slots=True)
class ProfileSpec:
    name: str
    agents: tuple[str, ...]
    skills: tuple[str, ...]


class Catalog:
    def __init__(
        self,
        path: Path,
        version: int,
        repository: dict[str, str],
        skills: dict[str, SkillSpec],
        template_layers: dict[str, TemplateLayerSpec],
        templates: dict[str, TemplateSpec],
        profiles: dict[str, ProfileSpec],
    ) -> None:
        self.path = path
        self.version = version
        self.repository = repository
        self.skills = skills
        self.template_layers = template_layers
        self.templates = templates
        self.profiles = profiles

    @classmethod
    def load(cls, path: Path | None = None) -> Catalog:
        selected_path = catalog_path(path)
        try:
            raw = tomllib.loads(selected_path.read_text(encoding="utf-8"))
            return cls.from_mapping(selected_path, raw)
        except MusterctlError:
            raise
        except (
            OSError,
            KeyError,
            TypeError,
            ValueError,
            tomllib.TOMLDecodeError,
        ) as exc:
            raise MusterctlError(
                "catalog_invalid",
                f"The catalog is unreadable or invalid: {exc}",
                EXIT_ENVIRONMENT,
                {"path": selected_path},
                ("repair the configured catalog and rerun musterctl",),
            ) from exc

    @classmethod
    def from_mapping(cls, path: Path, raw: dict[str, Any]) -> Catalog:
        """Validate a parsed catalog mapping without requiring a temporary file."""

        catalog = cls._from_mapping(path, raw)
        catalog.validate()
        return catalog

    @classmethod
    def _from_mapping(cls, path: Path, raw: dict[str, Any]) -> Catalog:
        raw_skills = raw.get("skills", {})
        raw_layers = raw.get("template_layers", {})
        raw_templates = raw.get("templates", {})
        raw_profiles = raw.get("profiles", {})
        skills = {
            name: SkillSpec(
                name=name,
                description=str(value["description"]),
                category=str(value["category"]),
                ownership=str(value["ownership"]),
                update_policy=str(value["update_policy"]),
                source=str(value["source"]),
                source_url=str(value.get("source_url", value["source"])),
                source_path=str(value.get("source_path", ".")),
                source_skill=str(value.get("source_skill", name)),
                source_ref=str(value.get("source_ref", "HEAD")),
                scopes=tuple(str(scope) for scope in value["scope"]),
                pin=str(value["pin"]) if "pin" in value else None,
                license=str(value["license"]) if "license" in value else None,
                content_sha256=(
                    str(value["content_sha256"]) if "content_sha256" in value else None
                ),
            )
            for name, value in raw_skills.items()
        }
        template_layers = {
            name: TemplateLayerSpec(
                name=name,
                source_url=str(value["source_url"]),
                revision=str(value["revision"]),
                source_path=str(value.get("source_path", ".")),
                content_sha256=str(value["content_sha256"]),
            )
            for name, value in raw_layers.items()
        }
        templates = {
            name: TemplateSpec(
                name=name,
                category=str(value["category"]),
                description=str(value["description"]),
                layers=tuple(str(layer) for layer in value.get("layers", ())),
                required_skills=tuple(
                    str(skill) for skill in value.get("required_skills", ())
                ),
                recommended_skills=tuple(
                    str(skill) for skill in value.get("recommended_skills", ())
                ),
                optional_categories=tuple(
                    str(category) for category in value.get("optional_categories", ())
                ),
                skill_manifest=(
                    str(value["skill_manifest"]) if "skill_manifest" in value else None
                ),
            )
            for name, value in raw_templates.items()
        }
        profiles = {
            name: ProfileSpec(
                name=name,
                agents=tuple(str(agent) for agent in value["agents"]),
                skills=tuple(str(skill) for skill in value["skills"]),
            )
            for name, value in raw_profiles.items()
        }
        repository = raw.get("repository", {})
        return cls(
            path,
            int(raw["version"]),
            {str(key): str(value) for key, value in repository.items()},
            skills,
            template_layers,
            templates,
            profiles,
        )

    def validate(self) -> None:
        problems: list[str] = []
        if self.version != 1:
            problems.append(f"unsupported catalog version {self.version}")
        for skill in self.skills.values():
            if not _NAME.fullmatch(skill.name) or skill.name in {".", ".."}:
                problems.append(f"{skill.name}: invalid skill name")
            if skill.ownership not in {
                "first-party",
                "third-party",
                "personal",
                "imported",
            }:
                problems.append(f"{skill.name}: invalid ownership")
            if skill.update_policy not in {"latest", "pinned"}:
                problems.append(f"{skill.name}: invalid update policy")
            if not set(skill.scopes) <= {"global", "project"} or not skill.scopes:
                problems.append(f"{skill.name}: invalid scope")
            if (
                not skill.source
                or not skill.source_url
                or not skill.source_path
                or not skill.source_ref
            ):
                problems.append(f"{skill.name}: incomplete source lineage")
            source_path = Path(skill.source_path)
            if source_path.is_absolute() or ".." in source_path.parts:
                problems.append(f"{skill.name}: invalid source path")
            if not skill.content_sha256:
                problems.append(f"{skill.name}: source needs a content digest")
            elif not _SHA256.fullmatch(skill.content_sha256):
                problems.append(f"{skill.name}: invalid content digest")
            if skill.update_policy == "pinned":
                if not skill.pin or not _SHA.fullmatch(skill.pin):
                    problems.append(
                        f"{skill.name}: pinned source needs a full commit SHA"
                    )
                elif skill.pin not in skill.source:
                    problems.append(
                        f"{skill.name}: installer source must include its pin"
                    )
            if skill.ownership == "third-party" and skill.update_policy != "pinned":
                problems.append(f"{skill.name}: third-party source must be pinned")
        for layer in self.template_layers.values():
            if not _SHA.fullmatch(layer.revision):
                problems.append(f"template layer {layer.name}: revision must be a SHA")
            if not _SHA256.fullmatch(layer.content_sha256):
                problems.append(f"template layer {layer.name}: invalid content digest")
            if not layer.source_url or not layer.source_path:
                problems.append(f"template layer {layer.name}: incomplete source")
            source_path = Path(layer.source_path)
            if source_path.is_absolute() or ".." in source_path.parts:
                problems.append(f"template layer {layer.name}: invalid source path")
        if "global" not in self.profiles:
            problems.append("catalog has no global profile")
        for profile in self.profiles.values():
            for name in profile.skills:
                if name not in self.skills:
                    problems.append(f"profile {profile.name}: unknown skill {name}")
                elif "global" not in self.skills[name].scopes:
                    problems.append(f"profile {profile.name}: {name} is not global")
        for template in self.templates.values():
            problems.extend(
                f"template {template.name}: unknown layer {layer}"
                for layer in template.layers
                if layer not in self.template_layers
            )
            for name in (*template.required_skills, *template.recommended_skills):
                if name not in self.skills:
                    problems.append(f"template {template.name}: unknown skill {name}")
                elif "global" in self.profiles and name in self.global_profile.skills:
                    problems.append(
                        f"template {template.name}: global skill {name} "
                        "cannot be project-provided"
                    )
                elif "project" not in self.skills[name].scopes:
                    problems.append(
                        f"template {template.name}: skill {name} is not project-scoped"
                    )
            if template.skill_manifest:
                manifest = Path(template.skill_manifest)
                if manifest.is_absolute() or ".." in manifest.parts:
                    problems.append(
                        f"template {template.name}: invalid skill manifest path"
                    )
        if problems:
            raise MusterctlError(
                "catalog_invalid",
                "; ".join(problems),
                EXIT_ENVIRONMENT,
                {"path": self.path},
                ("repair the configured catalog",),
            )

    @property
    def global_profile(self) -> ProfileSpec:
        try:
            return self.profiles["global"]
        except KeyError as exc:
            raise MusterctlError(
                "catalog_invalid",
                "The catalog has no global profile.",
                EXIT_ENVIRONMENT,
            ) from exc

    def skill(self, name: str) -> SkillSpec:
        try:
            return self.skills[name]
        except KeyError as exc:
            matches = difflib.get_close_matches(name, self.skills, n=3, cutoff=0.35)
            raise MusterctlError(
                "unknown_skill",
                f"{name} is not in the configured catalog.",
                fields={"skill": name, "available_matches": ",".join(matches)},
                next_actions=("musterctl catalog search <query>",),
            ) from exc

    def template(self, name: str) -> TemplateSpec:
        try:
            return self.templates[name]
        except KeyError as exc:
            matches = difflib.get_close_matches(name, self.templates, n=3, cutoff=0.35)
            raise MusterctlError(
                "unknown_template",
                f"{name} is not an available project template.",
                fields={"template": name, "available_matches": ",".join(matches)},
                next_actions=("musterctl templates list",),
            ) from exc

    def template_layer(self, name: str) -> TemplateLayerSpec:
        return self.template_layers[name]

    def search(self, query: str) -> list[SkillSpec]:
        terms = query.casefold().split()
        return [
            skill
            for skill in sorted(self.skills.values(), key=lambda item: item.name)
            if all(
                term
                in " ".join(
                    (
                        skill.name,
                        skill.description,
                        skill.category,
                        skill.ownership,
                        skill.update_policy,
                    )
                ).casefold()
                for term in terms
            )
        ]
