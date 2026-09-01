"""Command handlers that translate domain state into compact documents."""

from __future__ import annotations

import shlex
from pathlib import Path

from musterctl.catalog import Catalog
from musterctl.output import Document
from musterctl.project import ProjectInitializer, ProjectPlan
from musterctl.resources import config_catalog_path
from musterctl.setup import (
    inspect_installed_skills,
    render_initial_catalog,
    select_installed_skills,
    write_initial_catalog,
)
from musterctl.state import (
    SkillsManager,
    find_project_root,
    global_skill_states,
    project_skill_states,
    skill_diff,
)


def dashboard(catalog: Catalog, cwd: Path | None = None) -> Document:
    current = (cwd or Path.cwd()).resolve()
    project = find_project_root(current)
    global_states = global_skill_states(catalog)
    attention = sum(
        state.status not in {"current", "unmanaged"} for state in global_states
    )
    document = Document()
    document.scalar("context", "project" if project else "global")
    if project:
        document.scalar("project", project.name)
        document.scalar("path", project)
    document.fields(
        {
            "global_skills_installed": sum(
                state.status != "missing" for state in global_states
            ),
            "global_skills_attention": attention,
            "catalog": "current",
        }
    )
    if project:
        project_states = project_skill_states(catalog, project)
        document.fields(
            {
                "project_skills_installed": sum(
                    state.status != "missing" for state in project_states
                ),
                "project_skills_attention": sum(
                    state.status not in {"current", "unmanaged"}
                    for state in project_states
                ),
            }
        )
        document.items("next", ("musterctl skills status",))
    elif attention:
        document.items(
            "next", ("musterctl skills sync --dry-run", "musterctl templates list")
        )
    else:
        document.items("next", ("musterctl templates list",))
    return document


def status(catalog: Catalog) -> Document:
    global_states = global_skill_states(catalog)
    project = find_project_root()
    project_states = project_skill_states(catalog, project) if project else []
    healthy = all(
        state.status in {"current", "unmanaged"} for state in global_states
    ) and all(state.status in {"current", "unmanaged"} for state in project_states)
    document = Document()
    document.fields(
        {
            "health": "ok" if healthy else "attention",
            "catalog_version": catalog.version,
            "catalog_path": catalog.path,
            "context": "project" if project else "global",
        }
    )
    document.records(
        "global_skills",
        (
            {
                "name": state.name,
                "status": state.status,
                "policy": state.policy,
                "path": state.paths[0] if state.paths else None,
            }
            for state in global_states
        ),
        ("name", "status", "policy", "path"),
    )
    document.records(
        "project_skills",
        (
            {
                "name": state.name,
                "status": state.status,
                "policy": state.policy,
                "path": state.paths[0] if state.paths else None,
            }
            for state in project_states
        ),
        ("name", "status", "policy", "path"),
    )
    next_actions: list[str] = []
    if any(state.status not in {"current", "unmanaged"} for state in global_states):
        next_actions.append("musterctl skills sync --dry-run")
    if any(state.status not in {"current", "unmanaged"} for state in project_states):
        next_actions.append("musterctl skills diff <skill>")
    if not next_actions:
        next_actions.append("musterctl templates list")
    document.items("next", next_actions)
    return document


def catalog_search(catalog: Catalog, query: str) -> Document:
    matches = catalog.search(query)
    document = Document()
    document.scalar("query", query)
    document.records(
        "skills",
        (
            {
                "name": skill.name,
                "category": skill.category,
                "ownership": skill.ownership,
                "policy": skill.update_policy,
                "description": skill.description,
            }
            for skill in matches
        ),
        ("name", "category", "ownership", "policy", "description"),
    )
    if matches:
        document.items("next", ("musterctl catalog show <skill>",))
    else:
        document.items("next", ("musterctl catalog search <broader-query>",))
    return document


def catalog_show(catalog: Catalog, name: str) -> Document:
    skill = catalog.skill(name)
    document = Document()
    document.fields(
        {
            "skill": skill.name,
            "category": skill.category,
            "description": skill.description,
            "ownership": skill.ownership,
            "update_policy": skill.update_policy,
            "source": skill.source,
            "source_url": skill.source_url,
            "source_path": skill.source_path,
            "pin": skill.pin,
            "license": skill.license,
            "content_sha256": skill.content_sha256,
        }
    )
    document.items("scopes", skill.scopes)
    if "global" in skill.scopes:
        document.items("next", ("musterctl skills status",))
    else:
        document.items(
            "next", ("musterctl templates list", "musterctl skills available")
        )
    return document


def templates_list(catalog: Catalog) -> Document:
    document = Document()
    document.records(
        "templates",
        (
            {
                "name": template.name,
                "category": template.category,
                "description": template.description,
            }
            for template in sorted(
                catalog.templates.values(), key=lambda item: item.name
            )
        ),
        ("name", "category", "description"),
    )
    document.items("next", ("musterctl templates show <name>",))
    return document


def templates_show(catalog: Catalog, name: str) -> Document:
    template = catalog.template(name)
    document = Document()
    document.fields(
        {
            "template": template.name,
            "category": template.category,
            "description": template.description,
        }
    )
    document.items("layers", template.layers)
    document.items("recommended_skills", template.recommended_skills)
    document.items("optional_categories", template.optional_categories)
    document.items(
        "next",
        (
            f"musterctl skills available --template {template.name}",
            f"musterctl init <name> --template {template.name} --defaults --plan",
        ),
    )
    return document


def skills_available(catalog: Catalog, template_name: str | None) -> Document:
    template = catalog.template(template_name) if template_name else None
    statuses = {state.name: state.status for state in global_skill_states(catalog)}
    global_names = set(catalog.global_profile.skills)
    recommended_names = set(template.recommended_skills if template else ())
    document = Document()
    if template:
        document.scalar("template", template.name)
    document.records(
        "global",
        (
            {
                "name": name,
                "status": statuses[name],
                "reason": "provided by global profile",
            }
            for name in catalog.global_profile.skills
        ),
        ("name", "status", "reason"),
    )
    document.records(
        "recommended",
        (
            {
                "name": catalog.skills[name].name,
                "category": catalog.skills[name].category,
                "reason": "template recommendation",
            }
            for name in sorted(recommended_names)
        ),
        ("name", "category", "reason"),
    )
    document.records(
        "available",
        (
            {
                "name": skill.name,
                "category": skill.category,
                "policy": skill.update_policy,
            }
            for skill in sorted(catalog.skills.values(), key=lambda item: item.name)
            if skill.name not in global_names
            and skill.name not in recommended_names
            and "project" in skill.scopes
        ),
        ("name", "category", "policy"),
    )
    document.items("next", ("musterctl init <name> --template <template> --plan",))
    return document


def skills_status(catalog: Catalog) -> Document:
    return status(catalog)


def setup_inspect() -> Document:
    candidates = inspect_installed_skills()
    document = Document()
    document.records(
        "installed_skills",
        (
            {
                "name": candidate.name,
                "lineage": candidate.lineage,
                "source": candidate.source,
                "source_path": candidate.source_path,
                "installed": candidate.path is not None,
                "path": candidate.path,
            }
            for candidate in candidates
        ),
        ("name", "lineage", "source", "source_path", "installed", "path"),
    )
    tracked = [item for item in candidates if item.lineage == "tracked"]
    if tracked:
        document.items(
            "next",
            (
                "musterctl setup init --include <skill> --plan",
                "musterctl setup init --all-tracked --plan",
            ),
        )
    else:
        document.items("next", ("musterctl setup init --plan",))
    return document


def setup_init(
    includes: list[str],
    all_tracked: bool,
    output: Path | None,
    plan_only: bool,
) -> Document:
    candidates = inspect_installed_skills()
    selected = select_installed_skills(candidates, includes, all_tracked)
    content = render_initial_catalog(selected)
    destination = output.expanduser() if output is not None else config_catalog_path()
    document = Document()
    document.fields(
        {
            "mode": "plan" if plan_only else "apply",
            "destination": destination.resolve(),
            "selected_skills": len(selected),
        }
    )
    document.items("skills", (candidate.name for candidate in selected))
    document.items(
        "actions",
        (
            "create external catalog",
            "record Skills CLI source lineage",
            "leave installed skill content unchanged",
        ),
    )
    if plan_only:
        document.scalar("mutations", 0)
        command = ["musterctl", "setup", "init"]
        for name in includes:
            command.extend(("--include", name))
        if all_tracked:
            command.append("--all-tracked")
        if output is not None:
            command.extend(("--output", str(output)))
        document.items("next", (shlex.join(command),))
        return document
    written = write_initial_catalog(content, output)
    document.scalar("mutations", 1)
    document.scalar("catalog", written)
    document.items("next", (f"musterctl --catalog {shlex.quote(str(written))} status",))
    return document


def skills_sync(catalog: Catalog, dry_run: bool) -> Document:
    manager = SkillsManager(catalog)
    actions = manager.plan()
    document = Document()
    document.scalar("mode", "plan" if dry_run else "apply")
    document.records(
        "actions",
        (
            {
                "skill": action.skill.name,
                "operation": action.operation,
                "policy": action.skill.update_policy,
                "command": shlex.join(action.command),
            }
            for action in actions
        ),
        ("skill", "operation", "policy", "command"),
    )
    if dry_run:
        document.scalar("mutations", 0)
        if actions:
            document.items("next", ("musterctl skills sync",))
        else:
            document.items("next", ("musterctl skills status",))
        return document
    manager.apply(actions)
    document.scalar("mutations", len(actions))
    document.scalar("status", "current")
    document.items("next", ("musterctl skills status",))
    return document


def skills_diff(catalog: Catalog, name: str) -> Document:
    skill = catalog.skill(name)
    project = find_project_root()
    candidates: list[Path] = []
    project_candidate: Path | None = None
    if project:
        project_candidate = project / ".agents" / "skills" / name
        candidates.append(project_candidate)
    home_states = {state.name: state for state in global_skill_states(catalog)}
    home_state = home_states.get(name)
    if home_state:
        candidates.extend(home_state.paths)
    installed = next(
        (
            path
            for path in candidates
            if path.is_dir() and (path / "SKILL.md").is_file()
        ),
        None,
    )
    installed_scope = (
        "project"
        if installed is not None and installed == project_candidate
        else "global"
    )
    project_recovery = installed_scope == "project" or (
        installed is None
        and project is not None
        and "project" in skill.scopes
        and "global" not in skill.scopes
    )
    recovery_actions: tuple[str, ...]
    if project_recovery:
        recovery_actions = (
            f"restore .agents/skills/{name} from version control or its lock source",
            "musterctl skills status",
        )
    elif "global" in skill.scopes:
        recovery_actions = ("musterctl skills sync --dry-run",)
    else:
        recovery_actions = ("run this command from the project that owns the skill",)
    document = Document()
    document.fields(
        {
            "skill": skill.name,
            "scope": installed_scope if installed is not None else "none",
            "policy": skill.update_policy,
            "installed": installed,
        }
    )
    if installed is None:
        document.scalar("status", "missing")
        document.items("diff", ())
        document.items("next", recovery_actions)
        return document
    lines, truncated = skill_diff(catalog, name, installed)
    document.scalar("status", "current" if not lines else "different")
    document.items("diff", lines)
    document.scalar("truncated", truncated)
    if lines:
        document.items("next", recovery_actions)
    else:
        document.items("next", ("musterctl skills status",))
    return document


def _project_plan_document(
    catalog: Catalog, plan: ProjectPlan, applying: bool, command: str
) -> Document:
    document = Document()
    document.fields(
        {
            "mode": "apply" if applying else "plan",
            "project": plan.name,
            "template": plan.template.name,
            "destination": plan.destination,
        }
    )
    document.items("global_skills", catalog.global_profile.skills)
    document.items("project_skills", (skill.name for skill in plan.skills))
    document.items("actions", plan.actions)
    document.scalar("mutations", len(plan.actions) if applying else 0)
    if applying:
        document.scalar("status", "created")
        document.items(
            "next",
            (f"cd {shlex.quote(str(plan.destination))}", "./scripts/check"),
        )
    else:
        document.items("next", (command,))
    return document


def initialize_project(
    catalog: Catalog,
    name: str,
    template: str,
    requested_skills: list[str],
    use_defaults: bool,
    parent: Path,
    plan_only: bool,
) -> Document:
    initializer = ProjectInitializer(catalog)
    plan = initializer.plan(name, template, requested_skills, use_defaults, parent)
    command_parts = ["musterctl", "init", name, "--template", template]
    if use_defaults:
        command_parts.append("--defaults")
    for skill in requested_skills:
        command_parts.extend(("--skill", skill))
    if parent != Path():
        command_parts.extend(("--parent", str(parent)))
    command = shlex.join(command_parts)
    if plan_only:
        return _project_plan_document(catalog, plan, False, command)
    initializer.apply(plan)
    return _project_plan_document(catalog, plan, True, command)
