"""Shared product and command metadata used by the CLI and generated guidance."""

from __future__ import annotations

from dataclasses import dataclass

PRODUCT_DESCRIPTION = "Agent-native control plane for external skill catalogs."

POLICIES = (
    "The local catalog is versioned workstation policy, not package state.",
    "The Python package contains no catalog, Agent Skill payload, or "
    "project-template source; this skill is versioned beside the CLI source.",
    "Pinned skills use explicit source revisions and content digests.",
    "Project skills are copied into the repository and recorded in skills-lock.json.",
    "Global skills must not be duplicated into projects.",
    "Use --plan or --dry-run before meaningful mutations.",
    "Complete mutation requests never prompt for confirmation.",
)


@dataclass(frozen=True, slots=True)
class CommandSpec:
    path: tuple[str, ...]
    purpose: str
    mutates: bool
    safety: str
    examples: tuple[str, ...]

    @property
    def display_path(self) -> str:
        return "musterctl" + (" " + " ".join(self.path) if self.path else "")


COMMANDS = (
    CommandSpec(
        (),
        "Show ambient global or project state and likely next actions.",
        False,
        "read-only",
        ("musterctl",),
    ),
    CommandSpec(
        ("status",),
        "Report aggregated catalog, global skill, and project skill health.",
        False,
        "read-only",
        ("musterctl status",),
    ),
    CommandSpec(
        ("catalog", "search"),
        "Search curated skills by name, category, ownership, or description.",
        False,
        "read-only",
        ("musterctl catalog search deployment",),
    ),
    CommandSpec(
        ("catalog", "show"),
        "Inspect one skill's source, ownership, update policy, and scopes.",
        False,
        "read-only",
        ("musterctl catalog show gh-axi",),
    ),
    CommandSpec(
        ("templates", "list"),
        "List available project templates.",
        False,
        "read-only",
        ("musterctl templates list",),
    ),
    CommandSpec(
        ("templates", "show"),
        "Inspect template layers, recommendations, and next actions.",
        False,
        "read-only",
        ("musterctl templates show python-cli",),
    ),
    CommandSpec(
        ("skills", "available"),
        "Expose global exclusions, template recommendations, and usable "
        "project skills.",
        False,
        "read-only",
        ("musterctl skills available --template python-cli",),
    ),
    CommandSpec(
        ("skills", "status"),
        "Inspect installed global and current-project skill state.",
        False,
        "read-only",
        ("musterctl skills status",),
    ),
    CommandSpec(
        ("skills", "sync"),
        "Plan or reconcile the global profile through the noninteractive Skills CLI.",
        True,
        "use --dry-run first; unmanaged skills are never removed",
        ("musterctl skills sync --dry-run", "musterctl skills sync"),
    ),
    CommandSpec(
        ("skills", "diff"),
        "Compare an installed skill with its exact configured source.",
        False,
        "read-only",
        ("musterctl skills diff musterctl",),
    ),
    CommandSpec(
        ("setup", "inspect"),
        "Inspect existing global skills and their Skills CLI source lineage.",
        False,
        "read-only; works before a catalog exists",
        ("musterctl setup inspect",),
    ),
    CommandSpec(
        ("setup", "init"),
        "Plan or create an external catalog from selected tracked installs.",
        True,
        "use --plan first; existing catalogs are never overwritten",
        (
            "musterctl setup init --plan",
            "musterctl setup init --all-tracked --plan",
        ),
    ),
    CommandSpec(
        ("init",),
        "Plan or transactionally create an agent-ready project.",
        True,
        "use --plan first; existing destinations are never overwritten",
        (
            "musterctl init example --template python-cli --plan",
            "musterctl init example --template python-cli",
        ),
    ),
)


def command_spec(*path: str) -> CommandSpec:
    for spec in COMMANDS:
        if spec.path == path:
            return spec
    raise KeyError(path)
