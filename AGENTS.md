# musterctl project guide

`musterctl` is an agent-native Python CLI for reconciling catalog-backed Agent
Skills and creating projects from external pinned sources.

## Stable commands

- `./scripts/check` runs every required repository check.
- `uv run musterctl` shows the ambient dashboard when a catalog is configured.
- `uv run musterctl setup inspect` works before a catalog exists.
- `uv run musterctl <command> --help` is the live command authority.
- `uv run musterctl-build` regenerates committed command docs and
  `skills/musterctl/SKILL.md`.
- `uv run musterctl-build --skill-output PATH` optionally exports a copy of the
  generated skill guidance.

## Authoritative knowledge

- Product behavior and traceability: `docs/requirements.md`
- System boundaries and safety model: `docs/architecture.md`
- Current command reference: `docs/commands.md` (generated)
- Catalog policy: external configuration supplied with `--catalog`,
  `MUSTERCTL_CATALOG`, or `~/.config/musterctl/catalog.toml`

## Repository rules

- Keep the runtime dependency-free unless a concrete requirement cannot be met
  with the standard library.
- Keep the generated `skills/musterctl` source colocated with the CLI. Never add
  a catalog, another skill, or template source to this repository, and never
  include skill source in the wheel.
- Preserve third-party provenance and require immutable pins plus digests.
- Keep a catalog at five or fewer skills until the owner expands the v1 scope.
- Planning and dry-run paths must not mutate the filesystem, fetch sources, or
  invoke installers.
- Never put credentials, authenticated state, caches, or machine-specific state
  in this repository.
- Do not run global skill synchronization unless the user explicitly requests a
  change to the active environment.

## Definition of done

Add requirement-derived tests, update documentation, run `./scripts/check`, and
inspect the final diff. Template behavior must also be tested with isolated local
Git sources and a generated project transaction.
