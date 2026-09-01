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
    catalog_search,
    catalog_show,
    dashboard,
    initialize_project,
    setup_init,
    setup_inspect,
    skills_available,
    skills_diff,
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
    sync_parser.set_defaults(
        handler=lambda args, catalog: skills_sync(catalog, args.dry_run)
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
    skills_parser.set_defaults(help_parser=skills_parser)

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
    setup_inspect_parser.set_defaults(setup_handler=lambda _args: setup_inspect())
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
    setup_init_parser.set_defaults(
        setup_handler=lambda args: setup_init(
            args.include, args.all_tracked, args.output, args.plan
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
