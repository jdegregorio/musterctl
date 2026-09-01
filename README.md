# musterctl

`musterctl` is a noninteractive control plane for an Agent Skill environment.
It solves a common failure mode in agent-first development: skills become
anonymous copies scattered across global agent directories and repositories,
then drift apart with no reliable path back to source.

The tool keeps a small external catalog of source-backed skills and project
templates, compares that policy with the machine, and exposes deterministic
inspect → plan → apply → verify workflows for agents. It can:

- discover global and project skills, including duplicate names and local drift;
- adopt source-tracked installs or add a new Git-backed skill to the catalog;
- maintain an intentional global profile without silently deleting anything;
- route skill improvements back to source, then roll them out across projects;
- create self-contained projects from pinned templates and skill requirements.

The Python package owns behavior only. It includes no personal catalog,
independent skill payload, or project-template source. The generated
`musterctl` discovery skill is colocated in this repository because it is part
of the tool's interface, but it is not bundled in the wheel.

## Install and get started

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then add
the command to your workstation:

```bash
uv tool install musterctl
musterctl --version
```

`uv tool upgrade musterctl` upgrades that installation. For an ephemeral run,
use `uvx musterctl ...` instead. A Nix flake is also provided for declarative,
pinned installations.

On a machine that already has skills, start with a read-only inventory:

```bash
musterctl setup inspect
```

The scan covers canonical global roots and skill-bearing projects under
`~/Repos` by default. Narrow it with repeatable `--project` or `--search-root`
flags. It reports source lineage, content hashes, catalog status, and same-name
content conflicts. A `no_source` item is deliberately not importable; keep it
unmanaged until its source is placed in a dedicated repository (for example,
by asking an agent to use `gh-axi`).

To create a first catalog, select exact tracked installs and preview the result:

```bash
musterctl setup init --include-path ~/.agents/skills/example --plan
musterctl setup init --include-path ~/.agents/skills/example
```

Use `--all-tracked` only when every unambiguous, source-tracked install should
enter the starter catalog. Setup never changes installed content and refuses to
overwrite an existing catalog.

The catalog is meant to be version controlled—often in a developer-environment
repository. Point `MUSTERCTL_CATALOG` or global `--catalog` at that authoritative
working-tree file when using catalog mutation commands. A Home Manager-generated
target can remain the read-only runtime copy; do not edit a Nix store target.

## Everyday lifecycle

The compact [end-to-end journey map](docs/journeys.md) shows each starting state,
plan, apply, and verified outcome.

### Add or adopt a skill

Add a newly discovered Git source by resolving its current ref to an immutable
commit and digest:

```bash
musterctl catalog add discord-tools \
  --source https://github.com/example/discord-tools.git \
  --path skills/discord-tools \
  --scope project \
  --plan
```

Rerun the emitted command to apply. For an existing install with Skills CLI or
project-lock lineage, use its exact path:

```bash
musterctl catalog adopt ~/.agents/skills/discord-tools --plan
```

Name collisions and source/content mismatches block adoption. Search, inspect,
and maintain policy with:

```bash
musterctl catalog search discord
musterctl catalog show discord-tools
musterctl catalog configure discord-tools --global --scope global --scope project --plan
musterctl catalog remove discord-tools --plan
```

Catalog removal removes policy references only. Installed copies remain until a
separate, explicit cleanup.

### Reconcile or tidy global skills

```bash
musterctl skills status
musterctl skills sync --dry-run
musterctl skills sync
musterctl skills prune --plan
```

Sync manages only the catalog's global profile. A machine-local lock distinguishes
an ordinary catalog update from an installed-copy edit; the latter blocks sync
until it is moved to source or the user explicitly chooses `--replace-drift`.
Prune selects unmanaged canonical global skills and their adapters, never
catalog-managed skills or project content. Applying prune requires names or
`--all-unmanaged`.

### Improve a skill at source

Installed copies are deployments. The durable improvement loop is:

```bash
musterctl skills diff discord-tools
musterctl skills source discord-tools
musterctl skills checkout discord-tools --plan
# edit, test, commit, and push the source checkout
musterctl catalog update discord-tools --plan
musterctl catalog update discord-tools
musterctl skills sync --dry-run
musterctl projects sync --plan
```

`catalog check-updates` compares every configured source ref with its catalog
snapshot. Catalog updates advance the immutable pin and digest together but do
not silently touch installed copies. Global and project rollout remain separate,
reviewable actions.

### Create and maintain projects

```bash
musterctl templates list
musterctl templates show python-cli
musterctl skills available --template python-cli
musterctl init example --template python-cli --defaults --plan
musterctl init example --template python-cli --defaults
```

A template can carry `.musterctl/project.toml`:

```toml
[skills]
required = ["discord-tools"]
recommended = ["raspberry-pi-deployments"]
```

The catalog snapshots those names so planning performs no fetch. Apply verifies
the manifest in the pinned template source, installs required skills plus any
explicit/default selections, and records full source lineage in
`skills-lock.json`.

Later, compare and advance every managed project copy:

```bash
musterctl projects status
musterctl projects sync --plan
musterctl projects sync
```

Project sync never removes a skill. Local changes block the whole apply by
default; each changed project is staged, its adapters and lock are updated, and
its `scripts/check` must pass or that project is rolled back.

## Catalog and safety model

Every skill records a Git repository/path, editable source ref, resolved commit,
content digest, ownership, allowed scopes, and update policy. Third-party skills
must be pinned. Template layers are also immutable Git snapshots. Global skills
cannot be duplicated into projects.

Planning paths perform no Git fetch, installer call, or filesystem mutation.
Read operations return compact deterministic text with explicit empty
collections and recovery actions. Mutation requests never prompt, never replace
an unrelated destination, and surface stable error categories and exit codes.

## Development

Clone only when contributing:

```bash
git clone https://github.com/jdegregorio/musterctl.git
cd musterctl
uv sync --locked
./scripts/check
```

`uv sync --locked` creates this checkout's development environment from
`uv.lock`; it is not an end-user installation command. `./scripts/check` covers
formatting, lint, types, generated guidance, repository boundaries, unit and
integration journeys, branch coverage, and a built-wheel smoke test in CI.
