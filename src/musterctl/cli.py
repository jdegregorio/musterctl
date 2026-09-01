"""Noninteractive agent-first command-line interface."""

from __future__ import annotations

import argparse
import os
import sys
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import NoReturn

from musterctl import __version__
from musterctl.catalog import Catalog
from musterctl.errors import EXIT_INTERNAL, MusterctlError
from musterctl.handlers import (
    catalog_add,
    catalog_adopt,
    catalog_check_updates,
    catalog_configure,
    catalog_remove,
    catalog_search,
    catalog_show,
    catalog_update,
    dashboard,
    initialize_project,
    projects_status,
    projects_sync,
    setup_init,
    setup_inspect,
    skills_available,
    skills_checkout,
    skills_diff,
    skills_prune,
    skills_source,
    skills_status,
    skills_sync,
    status,
    templates_list,
    templates_show,
)
from musterctl.metadata import PRODUCT_DESCRIPTION, command_spec
from musterctl.output import Document, error_document

Handler = Callable[[argparse.Namespace, Catalog], Document]
SetupHandler = Callable[[argparse.Namespace], Document]


class StructuredParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise MusterctlError(
            "invalid_arguments",
            message,
            fields={"usage": self.format_usage().strip()},
            next_actions=(f"{self.prog} --help",),
        )


def _description(*path: str) -> str:
    return command_spec(*path).purpose


def _optional_catalog(path: Path | None) -> Catalog | None:
    try:
        return Catalog.load(path)
    except MusterctlError as error:
        if error.code == "catalog_missing":
            return None
        raise


def build_parser() -> StructuredParser:
    parser = StructuredParser(
        prog="musterctl",
        description=PRODUCT_DESCRIPTION,
        allow_abbrev=False,
    )
    parser.add_argument("-V", "--version", action="version", version=__version__)
    parser.add_argument(
        "--catalog",
        type=Path,
        help="external catalog TOML (default: MUSTERCTL_CATALOG or XDG config)",
    )
    commands = parser.add_subparsers(dest="command", parser_class=StructuredParser)

    status_parser = commands.add_parser(
        "status", description=_description("status"), help=_description("status")
    )
    status_parser.set_defaults(handler=lambda _args, catalog: status(catalog))

    catalog_parser = commands.add_parser(
        "catalog", description="Discover curated Agent Skills.", help="discover skills"
    )
    catalog_commands = catalog_parser.add_subparsers(
        dest="catalog_command", parser_class=StructuredParser
    )
    search_parser = catalog_commands.add_parser(
        "search",
        description=_description("catalog", "search"),
        help=_description("catalog", "search"),
    )
    search_parser.add_argument(
        "query", help="one or more case-insensitive search terms"
    )
    search_parser.set_defaults(
        handler=lambda args, catalog: catalog_search(catalog, args.query)
    )
    show_parser = catalog_commands.add_parser(
        "show",
        description=_description("catalog", "show"),
        help=_description("catalog", "show"),
    )
    show_parser.add_argument("skill", help="exact curated skill name")
    show_parser.set_defaults(
        handler=lambda args, catalog: catalog_show(catalog, args.skill)
    )
    add_parser = catalog_commands.add_parser(
        "add",
        description=_description("catalog", "add"),
        help=_description("catalog", "add"),
    )
    add_parser.add_argument("name", help="catalog name for the Agent Skill")
    add_parser.add_argument(
        "--source", dest="source_url", required=True, help="Git repository URL"
    )
    add_parser.add_argument(
        "--path", dest="source_path", default=".", help="skill directory in source"
    )
    add_parser.add_argument("--source-skill", help="upstream skill name if it differs")
    add_parser.add_argument(
        "--ref", dest="source_ref", default="HEAD", help="editable Git ref to track"
    )
    add_parser.add_argument("--description", help="one-line catalog description")
    add_parser.add_argument(
        "--category", default="Uncategorized", help="discovery category"
    )
    add_parser.add_argument(
        "--ownership",
        choices=("first-party", "third-party", "personal", "imported"),
        default="personal",
        help="source ownership class",
    )
    add_parser.add_argument(
        "--policy",
        dest="update_policy",
        choices=("latest", "pinned"),
        help="update policy (defaults to pinned for third-party, latest otherwise)",
    )
    add_parser.add_argument(
        "--scope",
        action="append",
        choices=("global", "project"),
        default=[],
        help="allowed installation scope; repeat as needed (default: project)",
    )
    add_parser.add_argument(
        "--global",
        dest="global_profile",
        action="store_true",
        help="include this skill in the active global profile",
    )
    add_parser.add_argument("--license", dest="license_name")
    add_parser.add_argument(
        "--plan", action="store_true", help="validate without fetching or writing"
    )
    add_parser.set_defaults(
        handler=lambda args, catalog: catalog_add(
            catalog,
            name=args.name,
            source_url=args.source_url,
            source_path=args.source_path,
            source_skill=args.source_skill,
            source_ref=args.source_ref,
            description=args.description,
            category=args.category,
            ownership=args.ownership,
            update_policy=args.update_policy,
            scopes=tuple(args.scope),
            global_profile=args.global_profile,
            license_name=args.license_name,
            plan_only=args.plan,
        )
    )
    adopt_parser = catalog_commands.add_parser(
        "adopt",
        description=_description("catalog", "adopt"),
        help=_description("catalog", "adopt"),
    )
    adopt_parser.add_argument("path", type=Path, help="installed skill directory")
    adopt_parser.add_argument("--description", help="one-line catalog description")
    adopt_parser.add_argument(
        "--category", default="Imported", help="discovery category"
    )
    adopt_parser.add_argument(
        "--global",
        dest="global_profile",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="override whether the adopted skill enters the global profile",
    )
    adopt_parser.add_argument(
        "--plan", action="store_true", help="validate without fetching or writing"
    )
    adopt_parser.set_defaults(
        handler=lambda args, catalog: catalog_adopt(
            catalog,
            args.path,
            description=args.description,
            category=args.category,
            global_profile=args.global_profile,
            plan_only=args.plan,
        )
    )
    remove_parser = catalog_commands.add_parser(
        "remove",
        description=_description("catalog", "remove"),
        help=_description("catalog", "remove"),
    )
    remove_parser.add_argument("skill", help="exact catalog skill name")
    remove_parser.add_argument(
        "--plan", action="store_true", help="show catalog changes without writing"
    )
    remove_parser.set_defaults(
        handler=lambda args, catalog: catalog_remove(catalog, args.skill, args.plan)
    )
    configure_parser = catalog_commands.add_parser(
        "configure",
        description=_description("catalog", "configure"),
        help=_description("catalog", "configure"),
    )
    configure_parser.add_argument("skill", help="exact catalog skill name")
    configure_parser.add_argument(
        "--scope",
        action="append",
        choices=("global", "project"),
        default=None,
        help="replace allowed scopes; repeat as needed",
    )
    configure_parser.add_argument(
        "--global",
        dest="global_profile",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="include or exclude the skill from the global profile",
    )
    configure_parser.add_argument(
        "--plan", action="store_true", help="show catalog changes without writing"
    )
    configure_parser.set_defaults(
        handler=lambda args, catalog: catalog_configure(
            catalog,
            args.skill,
            tuple(args.scope) if args.scope is not None else None,
            args.global_profile,
            args.plan,
        )
    )
    updates_parser = catalog_commands.add_parser(
        "check-updates",
        description=_description("catalog", "check-updates"),
        help=_description("catalog", "check-updates"),
    )
    updates_parser.add_argument(
        "skill", nargs="*", help="optional exact skill names (default: all)"
    )
    updates_parser.set_defaults(
        handler=lambda args, catalog: catalog_check_updates(catalog, tuple(args.skill))
    )
    update_parser = catalog_commands.add_parser(
        "update",
        description=_description("catalog", "update"),
        help=_description("catalog", "update"),
    )
    update_parser.add_argument("skill", help="exact catalog skill name")
    update_parser.add_argument(
        "--ref", dest="source_ref", help="replace the editable Git ref"
    )
    update_parser.add_argument(
        "--plan", action="store_true", help="show source intent without fetching"
    )
    update_parser.set_defaults(
        handler=lambda args, catalog: catalog_update(
            catalog, args.skill, args.source_ref, args.plan
        )
    )
    catalog_parser.set_defaults(help_parser=catalog_parser)

    templates_parser = commands.add_parser(
        "templates",
        description="Discover project templates.",
        help="discover templates",
    )
    template_commands = templates_parser.add_subparsers(
        dest="templates_command", parser_class=StructuredParser
    )
    list_parser = template_commands.add_parser(
        "list",
        description=_description("templates", "list"),
        help=_description("templates", "list"),
    )
    list_parser.set_defaults(handler=lambda _args, catalog: templates_list(catalog))
    template_show_parser = template_commands.add_parser(
        "show",
        description=_description("templates", "show"),
        help=_description("templates", "show"),
    )
    template_show_parser.add_argument("name", help="exact template name")
    template_show_parser.set_defaults(
        handler=lambda args, catalog: templates_show(catalog, args.name)
    )
    templates_parser.set_defaults(help_parser=templates_parser)

    skills_parser = commands.add_parser(
        "skills", description="Inspect or reconcile Agent Skills.", help="manage skills"
    )
    skill_commands = skills_parser.add_subparsers(
        dest="skills_command", parser_class=StructuredParser
    )
    available_parser = skill_commands.add_parser(
        "available",
        description=_description("skills", "available"),
        help=_description("skills", "available"),
    )
    available_parser.add_argument(
        "--template", help="include one template's recommendations"
    )
    available_parser.set_defaults(
        handler=lambda args, catalog: skills_available(catalog, args.template)
    )
    skill_status_parser = skill_commands.add_parser(
        "status",
        description=_description("skills", "status"),
        help=_description("skills", "status"),
    )
    skill_status_parser.set_defaults(
        handler=lambda _args, catalog: skills_status(catalog)
    )
    sync_parser = skill_commands.add_parser(
        "sync",
        description=_description("skills", "sync"),
        help=_description("skills", "sync"),
    )
    sync_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="show the exact reconciliation without mutation",
    )
    sync_parser.add_argument(
        "--replace-drift",
        action="store_true",
        help="discard installed global changes after explicit review",
    )
    sync_parser.set_defaults(
        handler=lambda args, catalog: skills_sync(
            catalog, args.dry_run, args.replace_drift
        )
    )
    diff_parser = skill_commands.add_parser(
        "diff",
        description=_description("skills", "diff"),
        help=_description("skills", "diff"),
    )
    diff_parser.add_argument("skill", help="exact curated skill name")
    diff_parser.set_defaults(
        handler=lambda args, catalog: skills_diff(catalog, args.skill)
    )
    source_parser = skill_commands.add_parser(
        "source",
        description=_description("skills", "source"),
        help=_description("skills", "source"),
    )
    source_parser.add_argument("skill", help="exact catalog skill name")
    source_parser.set_defaults(
        handler=lambda args, catalog: skills_source(catalog, args.skill)
    )
    checkout_parser = skill_commands.add_parser(
        "checkout",
        description=_description("skills", "checkout"),
        help=_description("skills", "checkout"),
    )
    checkout_parser.add_argument("skill", help="exact catalog skill name")
    checkout_parser.add_argument(
        "--destination", type=Path, help="new repository checkout path"
    )
    checkout_parser.add_argument(
        "--plan", action="store_true", help="validate without cloning"
    )
    checkout_parser.set_defaults(
        handler=lambda args, catalog: skills_checkout(
            catalog, args.skill, args.destination, args.plan
        )
    )
    prune_parser = skill_commands.add_parser(
        "prune",
        description=_description("skills", "prune"),
        help=_description("skills", "prune"),
    )
    prune_parser.add_argument(
        "skill", nargs="*", help="unmanaged canonical global skill names"
    )
    prune_parser.add_argument(
        "--all-unmanaged",
        action="store_true",
        help="select every unmanaged canonical global skill",
    )
    prune_parser.add_argument(
        "--plan", action="store_true", help="show cleanup without deleting"
    )
    prune_parser.set_defaults(
        handler=lambda args, catalog: skills_prune(
            catalog, tuple(args.skill), args.all_unmanaged, args.plan
        )
    )
    skills_parser.set_defaults(help_parser=skills_parser)

    projects_parser = commands.add_parser(
        "projects",
        description="Inspect or reconcile managed skills across projects.",
        help="manage skills across projects",
    )
    project_commands = projects_parser.add_subparsers(
        dest="projects_command", parser_class=StructuredParser
    )
    projects_status_parser = project_commands.add_parser(
        "status",
        description=_description("projects", "status"),
        help=_description("projects", "status"),
    )
    projects_status_parser.add_argument(
        "--search-root",
        action="append",
        type=Path,
        default=[],
        help="root to scan recursively; repeat as needed (default: ~/Repos)",
    )
    projects_status_parser.add_argument(
        "--project",
        action="append",
        type=Path,
        default=[],
        help="specific project to include; repeat as needed",
    )
    projects_status_parser.set_defaults(
        handler=lambda args, catalog: projects_status(
            catalog, tuple(args.search_root), tuple(args.project)
        )
    )
    projects_sync_parser = project_commands.add_parser(
        "sync",
        description=_description("projects", "sync"),
        help=_description("projects", "sync"),
    )
    projects_sync_parser.add_argument(
        "skill", nargs="*", help="optional managed skill names (default: all)"
    )
    projects_sync_parser.add_argument(
        "--search-root",
        action="append",
        type=Path,
        default=[],
        help="root to scan recursively; repeat as needed (default: ~/Repos)",
    )
    projects_sync_parser.add_argument(
        "--project",
        action="append",
        type=Path,
        default=[],
        help="specific project to include; repeat as needed",
    )
    projects_sync_parser.add_argument(
        "--replace-drift",
        action="store_true",
        help="discard local installed-copy changes after explicit review",
    )
    projects_sync_parser.add_argument(
        "--plan", action="store_true", help="show actions without mutation"
    )
    projects_sync_parser.set_defaults(
        handler=lambda args, catalog: projects_sync(
            catalog,
            tuple(args.skill),
            tuple(args.search_root),
            tuple(args.project),
            args.plan,
            args.replace_drift,
        )
    )
    projects_parser.set_defaults(help_parser=projects_parser)

    setup_parser = commands.add_parser(
        "setup",
        description="Inspect existing skills or bootstrap an external catalog.",
        help="bootstrap external configuration",
    )
    setup_commands = setup_parser.add_subparsers(
        dest="setup_command", parser_class=StructuredParser
    )
    setup_inspect_parser = setup_commands.add_parser(
        "inspect",
        description=_description("setup", "inspect"),
        help=_description("setup", "inspect"),
    )
    setup_inspect_parser.add_argument(
        "--search-root",
        action="append",
        type=Path,
        default=[],
        help="root to scan recursively for projects; repeat as needed",
    )
    setup_inspect_parser.add_argument(
        "--project",
        action="append",
        type=Path,
        default=[],
        help="specific project to inspect; repeat as needed",
    )
    setup_inspect_parser.set_defaults(
        setup_handler=lambda args: setup_inspect(
            _optional_catalog(args.catalog),
            tuple(args.search_root),
            tuple(args.project),
        )
    )
    setup_init_parser = setup_commands.add_parser(
        "init",
        description=_description("setup", "init"),
        help=_description("setup", "init"),
    )
    setup_init_parser.add_argument(
        "--include",
        action="append",
        default=[],
        help="tracked installed skill to import; repeat as needed",
    )
    setup_init_parser.add_argument(
        "--include-path",
        action="append",
        type=Path,
        default=[],
        help="exact tracked installation to import; repeat as needed",
    )
    setup_init_parser.add_argument(
        "--all-tracked",
        action="store_true",
        help="import every installed skill with Skills CLI lineage",
    )
    setup_init_parser.add_argument(
        "--output",
        type=Path,
        help="catalog destination (default: XDG config path)",
    )
    setup_init_parser.add_argument(
        "--plan", action="store_true", help="show actions without writing a catalog"
    )
    setup_init_parser.add_argument(
        "--search-root",
        action="append",
        type=Path,
        default=[],
        help="root to scan recursively for projects; repeat as needed",
    )
    setup_init_parser.add_argument(
        "--project",
        action="append",
        type=Path,
        default=[],
        help="specific project to inspect; repeat as needed",
    )
    setup_init_parser.set_defaults(
        setup_handler=lambda args: setup_init(
            args.include,
            args.include_path,
            args.all_tracked,
            args.output,
            args.plan,
            tuple(args.search_root),
            tuple(args.project),
        )
    )
    setup_parser.set_defaults(help_parser=setup_parser)

    init_parser = commands.add_parser(
        "init", description=_description("init"), help=_description("init")
    )
    init_parser.add_argument("project", help="new project name (one path component)")
    init_parser.add_argument("--template", required=True, help="exact template name")
    init_parser.add_argument(
        "--skill", action="append", default=[], help="project skill; repeat as needed"
    )
    init_parser.add_argument(
        "--defaults",
        action="store_true",
        help="include visible template recommendations",
    )
    init_parser.add_argument(
        "--parent", type=Path, default=Path(), help="existing parent directory"
    )
    init_parser.add_argument(
        "--plan", action="store_true", help="validate and show actions without mutation"
    )
    init_parser.set_defaults(
        handler=lambda args, catalog: initialize_project(
            catalog,
            args.project,
            args.template,
            args.skill,
            args.defaults,
            args.parent,
            args.plan,
        )
    )
    return parser


def run(argv: list[str] | None = None) -> Document:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    help_parser = getattr(arguments, "help_parser", None)
    setup_handler: SetupHandler | None = getattr(arguments, "setup_handler", None)
    handler: Handler | None = getattr(arguments, "handler", None)
    if setup_handler is not None:
        return setup_handler(arguments)
    if handler is None and help_parser is not None:
        help_parser.print_help()
        return Document()
    catalog = Catalog.load(arguments.catalog)
    if handler is None:
        return dashboard(catalog)
    return handler(arguments, catalog)


def main(argv: list[str] | None = None) -> int:
    try:
        document = run(argv)
        rendered = document.render()
        if rendered:
            sys.stdout.write(rendered)
        return 0
    except MusterctlError as error:
        sys.stderr.write(error_document(error).render())
        return error.exit_code
    except BrokenPipeError:
        return 0
    except KeyboardInterrupt:
        return 130
    except SystemExit as error:
        return int(error.code or 0)
    except Exception as error:  # pragma: no cover - defensive CLI boundary
        if os.environ.get("MUSTERCTL_DEBUG"):
            traceback.print_exc()
        internal = MusterctlError(
            "internal_error",
            f"musterctl encountered an unexpected {type(error).__name__}.",
            EXIT_INTERNAL,
            next_actions=("rerun with MUSTERCTL_DEBUG=1 and report the traceback",),
        )
        sys.stderr.write(error_document(internal).render())
        return internal.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
