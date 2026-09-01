"""Command handlers that translate domain state into compact documents."""

from __future__ import annotations

import shlex
from collections import defaultdict
from pathlib import Path

from musterctl.catalog import Catalog
from musterctl.catalog_store import CatalogStore
from musterctl.errors import EXIT_CONFLICT, MusterctlError
from musterctl.inventory import (
    SkillInstallation,
    default_project_roots,
    discover_projects,
    global_installations,
    inventory,
    project_installations,
)
from musterctl.output import Document
from musterctl.project import ProjectInitializer, ProjectPlan
from musterctl.project_sync import ProjectSkillsManager
from musterctl.resources import config_catalog_path, runtime_home
from musterctl.setup import (
    inspect_device_skills,
    render_initial_catalog,
    select_installed_skills,
    write_initial_catalog,
)
from musterctl.sources import (
    SourceSnapshot,
    checkout_source,
    inspect_source,
    source_selector,
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
            "source_skill": skill.source_skill,
            "source_ref": skill.source_ref,
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


def _catalog_change_document(
    *,
    operation: str,
    skill: str,
    catalog_path: Path,
    plan_only: bool,
    details: dict[str, object] | None = None,
    actions: tuple[str, ...] = (),
) -> Document:
    document = Document()
    document.fields(
        {
            "mode": "plan" if plan_only else "apply",
            "operation": operation,
            "skill": skill,
            "catalog": catalog_path,
            **(details or {}),
        }
    )
    document.items("actions", actions)
    document.scalar("mutations", 0 if plan_only else 1)
    return document


def catalog_add(
    catalog: Catalog,
    *,
    name: str,
    source_url: str,
    source_path: str,
    source_skill: str | None,
    source_ref: str,
    description: str | None,
    category: str,
    ownership: str,
    update_policy: str | None,
    scopes: tuple[str, ...],
    global_profile: bool,
    license_name: str | None,
    plan_only: bool,
) -> Document:
    selected_policy = update_policy or (
        "pinned" if ownership == "third-party" else "latest"
    )
    selected_scopes = tuple(dict.fromkeys(scopes or ("project",)))
    if global_profile and "global" not in selected_scopes:
        selected_scopes = (*selected_scopes, "global")
    selected_description = description or f"Operate the {name} Agent Skill."
    store = CatalogStore(catalog)
    snapshot = (
        inspect_source(source_url, source_ref, source_path) if not plan_only else None
    )
    validation_snapshot = snapshot or SourceSnapshot("0" * 40, "0" * 64)
    store.add_skill(
        name=name,
        description=selected_description,
        category=category,
        ownership=ownership,
        update_policy=selected_policy,
        source_url=source_url,
        source_path=source_path,
        source_skill=source_skill or name,
        source_ref=source_ref,
        snapshot=validation_snapshot,
        scopes=selected_scopes,
        global_profile=global_profile,
        license_name=license_name,
    )
    store.rendered()
    if not plan_only:
        store.write()
    document = _catalog_change_document(
        operation="add",
        skill=name,
        catalog_path=catalog.path,
        plan_only=plan_only,
        details={
            "source_url": source_url,
            "source_path": source_path,
            "source_ref": source_ref,
            "resolved_revision": snapshot.revision if snapshot else None,
            "content_sha256": snapshot.content_sha256 if snapshot else None,
            "update_policy": selected_policy,
            "global": global_profile,
        },
        actions=(
            "resolve source ref to an immutable Git commit",
            "verify the selected directory contains SKILL.md",
            "record source digest and policy in the external catalog",
        ),
    )
    document.items("scopes", selected_scopes)
    replay = [
        "musterctl",
        "catalog",
        "add",
        name,
        "--source",
        source_url,
        "--path",
        source_path,
        "--ref",
        source_ref,
        "--category",
        category,
        "--ownership",
        ownership,
        "--policy",
        selected_policy,
    ]
    if source_skill is not None:
        replay.extend(("--source-skill", source_skill))
    if description is not None:
        replay.extend(("--description", description))
    for scope in selected_scopes:
        replay.extend(("--scope", scope))
    if global_profile:
        replay.append("--global")
    if license_name is not None:
        replay.extend(("--license", license_name))
    document.items(
        "next",
        (
            shlex.join(replay)
            if plan_only
            else f"musterctl catalog show {shlex.quote(name)}",
        ),
    )
    return document


def catalog_remove(catalog: Catalog, name: str, plan_only: bool) -> Document:
    store = CatalogStore(catalog)
    references = store.remove_skill(name)
    store.rendered()
    if not plan_only:
        store.write()
    document = _catalog_change_document(
        operation="remove",
        skill=name,
        catalog_path=catalog.path,
        plan_only=plan_only,
        actions=(
            "remove the catalog entry",
            "remove global profile and template references",
            "leave every installed global and project copy unchanged",
        ),
    )
    document.items("references_removed", references)
    document.items(
        "next",
        (
            f"musterctl catalog remove {shlex.quote(name)}"
            if plan_only
            else "musterctl setup inspect",
        ),
    )
    return document


def catalog_configure(
    catalog: Catalog,
    name: str,
    scopes: tuple[str, ...] | None,
    global_profile: bool | None,
    plan_only: bool,
) -> Document:
    if scopes is None and global_profile is None:
        raise MusterctlError(
            "configuration_change_missing",
            "Choose at least one scope or global-profile change.",
            next_actions=(f"musterctl catalog show {name}",),
        )
    store = CatalogStore(catalog)
    store.configure_skill(
        name,
        scopes=tuple(dict.fromkeys(scopes)) if scopes is not None else None,
        global_profile=global_profile,
    )
    updated = store.validate().skill(name)
    store.rendered()
    if not plan_only:
        store.write()
    document = _catalog_change_document(
        operation="configure",
        skill=name,
        catalog_path=catalog.path,
        plan_only=plan_only,
        details={"global": name in store.validate().global_profile.skills},
        actions=("update catalog scope and profile policy",),
    )
    document.items("scopes", updated.scopes)
    replay = ["musterctl", "catalog", "configure", name]
    if scopes is not None:
        for scope in scopes:
            replay.extend(("--scope", scope))
    if global_profile is True:
        replay.append("--global")
    elif global_profile is False:
        replay.append("--no-global")
    document.items(
        "next",
        (shlex.join(replay),)
        if plan_only
        else (
            "musterctl skills sync --dry-run"
            if name in store.validate().global_profile.skills
            else "musterctl skills prune --plan",
        ),
    )
    return document


def catalog_check_updates(catalog: Catalog, names: tuple[str, ...]) -> Document:
    selected = tuple(dict.fromkeys(names)) or tuple(sorted(catalog.skills))
    snapshots = []
    for name in selected:
        skill = catalog.skill(name)
        snapshot = inspect_source(skill.source_url, skill.source_ref, skill.source_path)
        snapshots.append((skill, snapshot))
    document = Document()
    document.records(
        "updates",
        (
            {
                "skill": skill.name,
                "status": (
                    "current"
                    if snapshot.revision == skill.pin
                    and snapshot.content_sha256 == skill.content_sha256
                    else "available"
                ),
                "configured_revision": skill.pin,
                "source_revision": snapshot.revision,
                "configured_sha256": skill.content_sha256,
                "source_sha256": snapshot.content_sha256,
            }
            for skill, snapshot in snapshots
        ),
        (
            "skill",
            "status",
            "configured_revision",
            "source_revision",
            "configured_sha256",
            "source_sha256",
        ),
    )
    available = [
        skill.name
        for skill, snapshot in snapshots
        if snapshot.revision != skill.pin
        or snapshot.content_sha256 != skill.content_sha256
    ]
    document.items(
        "next",
        tuple(f"musterctl catalog update {name} --plan" for name in available)
        or ("musterctl setup inspect",),
    )
    return document


def catalog_update(
    catalog: Catalog,
    name: str,
    source_ref: str | None,
    plan_only: bool,
) -> Document:
    skill = catalog.skill(name)
    selected_ref = source_ref or skill.source_ref
    snapshot = (
        inspect_source(skill.source_url, selected_ref, skill.source_path)
        if not plan_only
        else None
    )
    store = CatalogStore(catalog)
    if snapshot is not None:
        store.update_skill(name, snapshot, source_ref=source_ref)
        store.write()
    document = _catalog_change_document(
        operation="update",
        skill=name,
        catalog_path=catalog.path,
        plan_only=plan_only,
        details={
            "source_ref": selected_ref,
            "configured_revision": skill.pin,
            "resolved_revision": snapshot.revision if snapshot else None,
            "content_sha256": snapshot.content_sha256 if snapshot else None,
        },
        actions=(
            "resolve and verify the configured source ref",
            "advance the catalog pin and content digest together",
            "leave installed global and project copies unchanged",
        ),
    )
    document.items(
        "next",
        (
            shlex.join(
                [
                    "musterctl",
                    "catalog",
                    "update",
                    name,
                    *(("--ref", source_ref) if source_ref is not None else ()),
                ]
            )
            if plan_only
            else "musterctl skills sync --dry-run",
            "musterctl projects sync --plan",
        ),
    )
    return document


def _installation_at_path(catalog: Catalog, path: Path) -> SkillInstallation:
    target = path.expanduser().resolve()
    candidates = global_installations(catalog)
    harness = target.parent.parent.name if len(target.parents) >= 2 else ""
    if target.parent.name == "skills" and harness in {".agents", ".claude", ".codex"}:
        project = target.parent.parent.parent
        if project != runtime_home():
            candidates.extend(project_installations(catalog, (project,)))
    matches = [
        installation
        for installation in candidates
        if any(candidate.resolve() == target for candidate in installation.paths)
    ]
    if not matches:
        raise MusterctlError(
            "installed_skill_not_found",
            "The path is not a discovered global or project skill installation.",
            fields={"path": target},
            next_actions=("musterctl setup inspect",),
        )
    return matches[0]


def catalog_adopt(
    catalog: Catalog,
    path: Path,
    *,
    description: str | None,
    category: str,
    global_profile: bool | None,
    plan_only: bool,
) -> Document:
    installation = _installation_at_path(catalog, path)
    if (
        installation.lineage != "tracked"
        or installation.source_url is None
        or installation.source_path is None
        or installation.content_sha256 is None
    ):
        raise MusterctlError(
            "source_lineage_missing",
            "The installed skill has no reusable source lineage and was not adopted.",
            EXIT_CONFLICT,
            {"skill": installation.name, "path": path},
            (
                "keep the installation unmanaged for now",
                "use gh-axi to create a dedicated source repository, then add it",
            ),
        )
    selected_global = (
        installation.scope == "global" if global_profile is None else global_profile
    )
    selected_ref = installation.source_pin or installation.source_ref
    snapshot = (
        inspect_source(
            installation.source_url,
            selected_ref,
            installation.source_path,
        )
        if not plan_only
        else None
    )
    if snapshot and snapshot.content_sha256 != installation.content_sha256:
        raise MusterctlError(
            "source_lineage_mismatch",
            "The installed content differs from the recorded source and was not "
            "adopted.",
            EXIT_CONFLICT,
            {
                "skill": installation.name,
                "installed_sha256": installation.content_sha256,
                "source_sha256": snapshot.content_sha256,
            },
            (f"musterctl skills diff {installation.name}",),
        )
    store = CatalogStore(catalog)
    selected_snapshot = snapshot or SourceSnapshot("0" * 40, "0" * 64)
    selected_scopes: tuple[str, ...] = (installation.scope,)
    if selected_global and "global" not in selected_scopes:
        selected_scopes = (*selected_scopes, "global")
    store.add_skill(
        name=installation.name,
        description=description or f"Operate the {installation.name} Agent Skill.",
        category=category,
        ownership="imported",
        update_policy="pinned" if installation.source_pin else "latest",
        source_url=installation.source_url,
        source_path=installation.source_path,
        source_skill=installation.source_skill,
        source_ref=installation.source_ref,
        snapshot=selected_snapshot,
        scopes=selected_scopes,
        global_profile=selected_global,
        license_name=None,
    )
    store.rendered()
    if not plan_only:
        store.write()
    document = _catalog_change_document(
        operation="adopt",
        skill=installation.name,
        catalog_path=catalog.path,
        plan_only=plan_only,
        details={
            "path": path.expanduser().resolve(),
            "source_url": installation.source_url,
            "source_path": installation.source_path,
            "source_ref": installation.source_ref,
            "resolved_revision": snapshot.revision if snapshot else None,
            "global": selected_global,
        },
        actions=(
            "verify installed content against its recorded source",
            "add the verified source snapshot to the external catalog",
            "leave installed content unchanged",
        ),
    )
    document.items("scopes", selected_scopes)
    replay = ["musterctl", "catalog", "adopt", str(path)]
    if description is not None:
        replay.extend(("--description", description))
    if category != "Imported":
        replay.extend(("--category", category))
    if global_profile is True:
        replay.append("--global")
    elif global_profile is False:
        replay.append("--no-global")
    document.items(
        "next",
        (
            shlex.join(replay)
            if plan_only
            else f"musterctl catalog show {installation.name}",
        ),
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
    document.items("required_skills", template.required_skills)
    document.items("recommended_skills", template.recommended_skills)
    document.items("optional_categories", template.optional_categories)
    document.scalar("skill_manifest", template.skill_manifest)
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
    required_names = set(template.required_skills if template else ())
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
        "required",
        (
            {
                "name": catalog.skills[name].name,
                "category": catalog.skills[name].category,
                "reason": "template requirement",
            }
            for name in sorted(required_names)
        ),
        ("name", "category", "reason"),
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
            and skill.name not in required_names
            and skill.name not in recommended_names
            and "project" in skill.scopes
        ),
        ("name", "category", "policy"),
    )
    document.items("next", ("musterctl init <name> --template <template> --plan",))
    return document


def skills_status(catalog: Catalog) -> Document:
    return status(catalog)


def setup_inspect(
    catalog: Catalog | None = None,
    search_roots: tuple[Path, ...] = (),
    projects: tuple[Path, ...] = (),
) -> Document:
    installations = inventory(
        catalog,
        search_roots=search_roots,
        projects=projects,
    )
    document = Document()
    document.records(
        "installed_skills",
        (
            {
                "name": installation.name,
                "scope": installation.scope,
                "lineage": installation.lineage,
                "source_status": (
                    "ready"
                    if installation.lineage == "tracked"
                    and installation.source_url
                    and installation.source_path
                    else "no_source"
                ),
                "catalog_status": installation.catalog_status,
                "source": installation.source,
                "source_path": installation.source_path,
                "content_sha256": installation.content_sha256,
                "instances": len(installation.paths),
                "path": installation.paths[0] if installation.paths else None,
                "project": installation.project,
            }
            for installation in installations
        ),
        (
            "name",
            "scope",
            "lineage",
            "source_status",
            "catalog_status",
            "source",
            "source_path",
            "content_sha256",
            "instances",
            "path",
            "project",
        ),
    )
    variants: dict[str, set[str | None]] = defaultdict(set)
    for installation in installations:
        variants[installation.name].add(installation.content_sha256)
    document.records(
        "name_conflicts",
        (
            {"name": name, "variants": len(hashes)}
            for name, hashes in sorted(variants.items())
            if len(hashes) > 1
        ),
        ("name", "variants"),
    )
    adoptable = [
        item
        for item in installations
        if item.lineage == "tracked"
        and item.source_url
        and item.source_path
        and item.catalog_status == "not_in_catalog"
        and item.paths
    ]
    no_source = [
        item
        for item in installations
        if item.lineage != "tracked" or not item.source_url or not item.source_path
    ]
    next_actions: list[str] = []
    if catalog is None and adoptable:
        next_actions.extend(
            (
                "musterctl setup init --include-path <path> --plan",
                "musterctl setup init --all-tracked --plan",
            )
        )
    elif catalog is not None and adoptable:
        next_actions.append(
            f"musterctl catalog adopt {shlex.quote(str(adoptable[0].paths[0]))} --plan"
        )
    elif catalog is None:
        next_actions.append("musterctl setup init --plan")
    if no_source:
        next_actions.append(
            "use gh-axi to create a dedicated source repo for no_source skills"
        )
    if not next_actions:
        next_actions.append("musterctl catalog check-updates")
    document.items("next", next_actions)
    return document


def setup_init(
    includes: list[str],
    include_paths: list[Path],
    all_tracked: bool,
    output: Path | None,
    plan_only: bool,
    search_roots: tuple[Path, ...] = (),
    projects: tuple[Path, ...] = (),
) -> Document:
    candidates = inspect_device_skills(
        search_roots=search_roots,
        projects=projects,
    )
    selected = select_installed_skills(candidates, includes, all_tracked, include_paths)
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
        for path in include_paths:
            command.extend(("--include-path", str(path)))
        if all_tracked:
            command.append("--all-tracked")
        if output is not None:
            command.extend(("--output", str(output)))
        for root in search_roots:
            command.extend(("--search-root", str(root)))
        for project in projects:
            command.extend(("--project", str(project)))
        document.items("next", (shlex.join(command),))
        return document
    written = write_initial_catalog(content, output)
    document.scalar("mutations", 1)
    document.scalar("catalog", written)
    document.items("next", (f"musterctl --catalog {shlex.quote(str(written))} status",))
    return document


def skills_sync(
    catalog: Catalog, dry_run: bool, replace_drift: bool = False
) -> Document:
    manager = SkillsManager(catalog)
    actions = manager.plan(replace_drift=replace_drift)
    document = Document()
    document.scalar("mode", "plan" if dry_run else "apply")
    document.records(
        "actions",
        (
            {
                "skill": action.skill.name,
                "operation": action.operation,
                "policy": action.skill.update_policy,
                "source_revision": action.skill.pin or "HEAD",
                "command": shlex.join(action.command),
                "reason": action.reason,
            }
            for action in actions
        ),
        (
            "skill",
            "operation",
            "policy",
            "source_revision",
            "command",
            "reason",
        ),
    )
    if dry_run:
        document.scalar("mutations", 0)
        blocked = [
            action.skill.name
            for action in actions
            if action.operation == "blocked_local_changes"
        ]
        if blocked:
            document.items(
                "next",
                (
                    f"musterctl skills diff {blocked[0]}",
                    f"musterctl skills source {blocked[0]}",
                    "musterctl skills sync --replace-drift",
                ),
            )
        elif actions:
            document.items(
                "next",
                (
                    "musterctl skills sync --replace-drift"
                    if replace_drift
                    else "musterctl skills sync",
                ),
            )
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
            f"musterctl skills source {name}",
            f"musterctl skills checkout {name} --plan",
            f"restore .agents/skills/{name} from version control or its lock source",
            "musterctl projects sync --plan",
        )
    elif "global" in skill.scopes:
        recovery_actions = (
            f"musterctl skills source {name}",
            "musterctl skills sync --dry-run",
        )
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


def skills_source(catalog: Catalog, name: str) -> Document:
    skill = catalog.skill(name)
    document = Document()
    document.fields(
        {
            "skill": skill.name,
            "source_url": skill.source_url,
            "source_path": skill.source_path,
            "source_ref": skill.source_ref,
            "configured_revision": skill.pin,
            "content_sha256": skill.content_sha256,
            "selector": source_selector(
                skill.source_url, skill.pin or skill.source_ref, skill.source_path
            ),
        }
    )
    document.items(
        "workflow",
        (
            f"musterctl skills checkout {shlex.quote(name)} --plan",
            "edit, test, commit, and push the source repository",
            f"musterctl catalog update {shlex.quote(name)} --plan",
            "musterctl skills sync --dry-run",
            "musterctl projects sync --plan",
        ),
    )
    return document


def skills_checkout(
    catalog: Catalog,
    name: str,
    destination: Path | None,
    plan_only: bool,
) -> Document:
    skill = catalog.skill(name)
    selected_destination = (
        destination.expanduser().resolve()
        if destination is not None
        else (Path.cwd() / f"{name}-source").resolve()
    )
    document = Document()
    document.fields(
        {
            "mode": "plan" if plan_only else "apply",
            "skill": name,
            "repository": selected_destination,
            "source_path": skill.source_path,
            "source_ref": skill.source_ref,
            "configured_revision": skill.pin,
        }
    )
    document.items(
        "actions",
        (
            "clone the source repository without replacing an existing path",
            "check out the configured editable ref",
            "verify source content still matches the catalog snapshot",
        ),
    )
    if plan_only:
        document.scalar("mutations", 0)
        command = ["musterctl", "skills", "checkout", name]
        if destination is not None:
            command.extend(("--destination", str(destination)))
        document.items("next", (shlex.join(command),))
        return document
    checkout = checkout_source(
        skill.source_url,
        skill.source_ref,
        skill.source_path,
        selected_destination,
        skill.content_sha256,
    )
    document.fields(
        {
            "revision": checkout.revision,
            "content_sha256": checkout.content_sha256,
            "skill_directory": checkout.selected,
        }
    )
    document.scalar("mutations", 1)
    document.items(
        "next",
        (
            f"cd {shlex.quote(str(checkout.root))}",
            "edit, test, commit, and push the source repository",
            f"musterctl catalog update {shlex.quote(name)} --plan",
        ),
    )
    return document


def skills_prune(
    catalog: Catalog,
    names: tuple[str, ...],
    all_unmanaged: bool,
    plan_only: bool,
) -> Document:
    if not plan_only and not names and not all_unmanaged:
        raise MusterctlError(
            "prune_selection_required",
            "Applying global cleanup requires skill names or --all-unmanaged.",
            EXIT_CONFLICT,
            next_actions=("musterctl skills prune --plan",),
        )
    manager = SkillsManager(catalog)
    actions = manager.plan_prune(names, all_unmanaged=all_unmanaged)
    document = Document()
    document.scalar("mode", "plan" if plan_only else "apply")
    document.records(
        "actions",
        (
            {
                "skill": action.name,
                "operation": "remove_unmanaged_global_copy",
                "paths": ";".join(str(path) for path in action.paths),
            }
            for action in actions
        ),
        ("skill", "operation", "paths"),
    )
    document.items(
        "safety",
        (
            "catalog-managed global skills are blocked",
            "only canonical global names and their adapters are removed",
            "project skills are never removed",
        ),
    )
    if plan_only:
        document.scalar("mutations", 0)
        command = ["musterctl", "skills", "prune"]
        if all_unmanaged or not names:
            command.append("--all-unmanaged")
        else:
            command.extend(names)
        document.items("next", (shlex.join(command),))
        return document
    manager.apply_prune(actions)
    document.scalar("mutations", sum(len(action.paths) for action in actions))
    document.items("next", ("musterctl setup inspect",))
    return document


def _selected_projects(
    search_roots: tuple[Path, ...], projects: tuple[Path, ...]
) -> tuple[Path, ...]:
    roots = search_roots or (() if projects else default_project_roots())
    selected = set(discover_projects(roots)) if roots else set()
    for raw_project in projects:
        project = raw_project.expanduser().resolve()
        if not project.is_dir():
            raise MusterctlError(
                "project_missing",
                "A requested project directory does not exist.",
                fields={"path": project},
            )
        selected.add(project)
    return tuple(sorted(selected))


def projects_status(
    catalog: Catalog,
    search_roots: tuple[Path, ...],
    projects: tuple[Path, ...],
) -> Document:
    selected = _selected_projects(search_roots, projects)
    installations = project_installations(catalog, selected)
    document = Document()
    document.fields(
        {
            "projects_scanned": len(selected),
            "skills_found": len(installations),
        }
    )
    document.records(
        "project_skills",
        (
            {
                "project": installation.project,
                "skill": installation.name,
                "lineage": installation.lineage,
                "status": installation.catalog_status,
                "instances": len(installation.paths),
                "installed_sha256": installation.content_sha256,
                "locked_sha256": installation.locked_sha256,
                "source_pin": installation.source_pin,
            }
            for installation in installations
        ),
        (
            "project",
            "skill",
            "lineage",
            "status",
            "instances",
            "installed_sha256",
            "locked_sha256",
            "source_pin",
        ),
    )
    attention = [
        installation
        for installation in installations
        if installation.catalog_status not in {"current", "catalog_match_untracked"}
    ]
    document.items(
        "next",
        ("musterctl projects sync --plan",)
        if attention
        else ("musterctl catalog check-updates",),
    )
    return document


def projects_sync(
    catalog: Catalog,
    names: tuple[str, ...],
    search_roots: tuple[Path, ...],
    projects: tuple[Path, ...],
    plan_only: bool,
    replace_drift: bool,
) -> Document:
    selected = _selected_projects(search_roots, projects)
    manager = ProjectSkillsManager(catalog, selected)
    actions = manager.plan(names=names, replace_drift=replace_drift)
    document = Document()
    document.fields(
        {
            "mode": "plan" if plan_only else "apply",
            "projects_scanned": len(selected),
        }
    )
    document.records(
        "actions",
        (
            {
                "project": action.project,
                "skill": action.name,
                "operation": action.operation,
                "path": action.path,
                "reason": action.reason,
            }
            for action in actions
        ),
        ("project", "skill", "operation", "path", "reason"),
    )
    document.items(
        "safety",
        (
            "project skills are never removed",
            "local changes block the whole apply unless --replace-drift is explicit",
            "each project is rolled back if its scripts/check fails",
        ),
    )
    if plan_only:
        document.scalar("mutations", 0)
        command = ["musterctl", "projects", "sync", *names]
        for root in search_roots:
            command.extend(("--search-root", str(root)))
        for project in projects:
            command.extend(("--project", str(project)))
        if replace_drift:
            command.append("--replace-drift")
        local_changes = [
            action.name
            for action in actions
            if action.operation == "blocked_local_changes"
        ]
        other_blocks = [
            action.name
            for action in actions
            if action.operation.startswith("blocked_")
            and action.operation != "blocked_local_changes"
        ]
        if local_changes:
            document.items(
                "next",
                (
                    f"musterctl skills diff {local_changes[0]}",
                    f"musterctl skills source {local_changes[0]}",
                    f"{shlex.join(command)} --replace-drift",
                ),
            )
        elif other_blocks:
            document.items("next", (f"musterctl catalog show {other_blocks[0]}",))
        else:
            document.items("next", (shlex.join(command),))
        return document
    manager.apply(actions)
    document.scalar("mutations", len(actions))
    document.items("next", ("musterctl projects status",))
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
