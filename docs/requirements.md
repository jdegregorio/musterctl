# Implemented product contract

This document translates the attached *Agent-First Interface Revision* into an
observable implementation and test contract. The attachment says FR-1 through
FR-47 remain in force, but that base document was not included. The concrete
behaviors below therefore cover all available commands, policies, flows, and
FR-48 through FR-63.

Later owner decisions supersede two attachment details: the public tool is named
`musterctl`, and its generated discovery skill is colocated with the tool source.
The Python distribution does not bundle that skill. The catalog remains local
developer-environment policy, while independent skills and templates live in
their own repositories.

## Product outcome

`musterctl` is an agent-primary, noninteractive control plane. A coding agent
interprets natural language and chooses capabilities; the CLI exposes compact
facts, plans exact actions, performs deterministic bounded mutations, and returns
structured state or recoverable errors. There is no wizard, TUI, confirmation
prompt, color-only meaning, animation, or TTY requirement.

## Behavioral requirements

| ID | Requirement | Primary verification |
| --- | --- | --- |
| R-01 | No arguments report ambient global/project state and contextual next actions. | dashboard contract tests |
| R-02 | Every command/group provides live `--help`; unknown syntax fails structurally. | CLI contract tests |
| R-03 | Search/show expose category, ownership, source lineage, scope, policy, and explicit empty results. | catalog tests |
| R-04 | Template list/show expose external layers, recommendations, categories, and next actions. | handler tests |
| R-05 | Discovery separates globally provided, recommended, and available project skills. | handler tests |
| R-06 | A global skill requested for a project fails as `skill_already_global`. | initialization tests |
| R-07 | Third-party sources require full immutable commits embedded in installer selectors plus SHA-256 digests. | catalog validation tests |
| R-08 | The repository contains no catalog, template, or skill source other than its generated `skills/musterctl`; the wheel contains none of those payloads. | boundary and wheel tests |
| R-09 | `init --plan` validates the complete request with zero fetch, installer call, or filesystem mutation. | no-mutation contract tests |
| R-10 | Apply fetches exact template layers, installs selected skills from source through Skills CLI, hashes/locks them, initializes Git, validates, and publishes without a prompt. | project journey tests |
| R-11 | Initialization is transactional; existing/racing destinations are never overwritten and temporary work is cleaned. | failure-path tests |
| R-12 | `--defaults` visibly means exactly the template's `recommended_skills`. | planning tests |
| R-13 | `skills sync --dry-run` emits exact noninteractive Skills CLI commands and invokes nothing. | fake-runner tests |
| R-14 | Apply reconciles only the global profile, verifies it, and never removes unmanaged skills. | isolated-home tests |
| R-15 | Global/project status distinguish current, missing, drifted, unmanaged, unverified, and update state. | state tests |
| R-16 | `skills diff` fetches and verifies the configured source, compares files, and caps output. | source/diff tests |
| R-17 | Success is compact deterministic text with explicit empty collections and likely next actions. | output/shape tests |
| R-18 | Failures have stable categories, exit codes, fields, and recovery actions. | CLI/failure tests |
| R-19 | Command docs and the colocated musterctl skill share metadata with help and are drift-checked. | generation and CI tests |
| R-20 | The wheel runs outside the checkout, bootstraps an empty external catalog, and contains no policy/content payload. | wheel smoke test |
| R-21 | Project materialization validates isolated local Git sources and a generated repository. | project journey tests |
| R-22 | Core behavior works without a TTY and with stdin closed. | subprocess tests |
| R-23 | Public package, uv/uvx, and Nix interfaces do not require a source checkout. | packaging/Nix checks |
| R-24 | `setup inspect` works without a catalog and reconstructs tracked/untracked lineage from existing Skills CLI installs. | setup tests |
| R-25 | `setup init` imports explicit tracked selections or creates an empty catalog, writes atomically, and never overwrites or modifies installed skills. | setup tests |

## Supplied FR-48 through FR-63 mapping

| Supplied requirement | Implementation |
| --- | --- |
| FR-48 Agent-primary user | Compact output, contextual actions, colocated discovery skill |
| FR-49 Noninteractive core | `argparse`, closed stdin, no prompt paths |
| FR-50 Agent-driven template selection | `templates list/show` |
| FR-51 Agent-driven skill selection | `skills available` classes and metadata |
| FR-52 Explicit initialization | required template plus explicit repeated skills/defaults |
| FR-53 Initialization planning | `init --plan` |
| FR-54 Deterministic mutation | verified source transaction or structured failure |
| FR-55 Compact structured output | deterministic TOON-like renderer |
| FR-56 CLI introspection | dashboard, help, catalog, and next actions |
| FR-57 Minimal installed skill | colocated generated guidance installed from the external catalog |
| FR-58 Live documentation authority | CLI help is authoritative in docs and skill |
| FR-59 Generated guidance | `musterctl-build --check` covers docs and the colocated skill |
| FR-60 Bootstrap independence | public wheel plus `setup` before a catalog exists |
| FR-61 No Home Manager skill special case | Home Manager manages package/config; skill sync uses Skills CLI |
| FR-62 Structured recoverability | `MusterctlError`, stable output, exit classes |
| FR-63 Agent-experience tests | contract, source, packaging, and end-to-end journeys |

## Stable exit codes

| Code | Meaning |
| ---: | --- |
| 0 | Success, explicit empty state, or no-op reconciliation |
| 2 | Invalid syntax, unknown catalog value, or invalid request |
| 3 | Safe conflict such as an existing destination or global duplication |
| 4 | Environment, installer, catalog, source, Git, or validation failure |
| 70 | Unexpected internal failure at the CLI boundary |
| 130 | User interruption |

## Explicit scope boundaries

- The CLI does not choose a template or skill on behalf of the agent.
- It does not provide an interactive human wizard.
- It does not remove unrecognized installed skills.
- It does not activate global skills merely because the package is installed or
  tested.
- It owns only its generated discovery skill source; it does not own the catalog,
  independent skill source, or template source, and the wheel bundles none of
  them.
- Setup imports only entries with clear Skills CLI lineage; untracked installs
  remain unmanaged until source metadata is supplied deliberately.
