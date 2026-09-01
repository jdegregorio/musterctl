"""Shared product and command metadata used by the CLI and generated guidance."""

from __future__ import annotations

from dataclasses import dataclass

PRODUCT_DESCRIPTION = (
    "Agent-native control plane for source-backed skill catalogs and projects."
)

POLICIES = (
    "The local catalog is versioned workstation policy, not package state.",
    "The Python package contains no catalog, Agent Skill payload, or "
    "project-template source; this skill is versioned beside the CLI source.",
    "Pinned skills use explicit source revisions and content digests.",
    "Project skills are copied into the repository and recorded in skills-lock.json.",
    "Global skills must not be duplicated into projects.",
    "Installed-copy edits are drift: move intentional changes to source first.",
    "Catalog updates never silently rewrite global or project installations.",
    "Project reconciliation never removes a project skill.",
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
        ("catalog", "add"),
        "Plan or add one verified Git-backed skill to the external catalog.",
        True,
        "use --plan first; apply resolves the ref and writes one catalog file",
        ("musterctl catalog add helper --source owner/helper --plan",),
    ),
    CommandSpec(
        ("catalog", "adopt"),
        "Plan or adopt a discovered installation with verifiable source lineage.",
        True,
        "no-source and source-mismatched installs are blocked",
        ("musterctl catalog adopt ~/.agents/skills/helper --plan",),
    ),
    CommandSpec(
        ("catalog", "remove"),
        "Plan or remove catalog policy while preserving every installed copy.",
        True,
        "installed global and project content is never removed",
        ("musterctl catalog remove helper --plan",),
    ),
    CommandSpec(
        ("catalog", "configure"),
        "Plan or change one skill's allowed scopes and global-profile membership.",
        True,
        "configuration changes do not immediately alter installations",
        ("musterctl catalog configure helper --no-global --scope project --plan",),
    ),
    CommandSpec(
        ("catalog", "check-updates"),
        "Resolve source refs and report catalog snapshots that can advance.",
        False,
        "read-only network operation",
        ("musterctl catalog check-updates",),
    ),
    CommandSpec(
        ("catalog", "update"),
        "Plan or advance one catalog pin and digest from its verified source ref.",
        True,
        "does not rewrite installed global or project copies",
        ("musterctl catalog update helper --plan",),
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
        ("skills", "source"),
        "Show exact source lineage and the source-first improvement workflow.",
        False,
        "read-only",
        ("musterctl skills source musterctl",),
    ),
    CommandSpec(
        ("skills", "checkout"),
        "Plan or create an editable checkout of a skill's configured source.",
        True,
        "never replaces a path and rejects source refs ahead of catalog content",
        ("musterctl skills checkout musterctl --plan",),
    ),
    CommandSpec(
        ("skills", "prune"),
        "Plan or remove explicitly selected unmanaged global skill copies.",
        True,
        "managed global and all project skills are protected",
        ("musterctl skills prune --plan",),
    ),
    CommandSpec(
        ("projects", "status"),
        "Discover managed project skills and compare copies, locks, and catalog.",
        False,
        "read-only; defaults to configured roots or ~/Repos",
        ("musterctl projects status",),
    ),
    CommandSpec(
        ("projects", "sync"),
        "Plan or transactionally advance managed skill copies across projects.",
        True,
        "never removes skills; local changes block apply by default",
        ("musterctl projects sync --plan",),
    ),
    CommandSpec(
        ("setup", "inspect"),
        "Discover global and project installs, lineage, hashes, and conflicts.",
        False,
        "read-only; works before a catalog exists",
        ("musterctl setup inspect",),
    ),
    CommandSpec(
        ("setup", "init"),
        "Plan or create an external catalog from selected source-tracked installs.",
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
