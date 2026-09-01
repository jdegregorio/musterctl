# musterctl

`musterctl` is a small, noninteractive control plane for an agent development
environment. It reads your external catalog, reports skill state, reconciles a
global profile through the Skills CLI, and creates projects from pinned Git
template sources.

The package intentionally contains no catalog, Agent Skill, or project-template
source. Those belong to their owners' repositories; your catalog records which
sources and revisions make up your environment.

## Install and get started

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then choose
either a persistent command or an ephemeral invocation:

```bash
# Normal workstation installation; `musterctl` is added to PATH.
uv tool install musterctl
musterctl --version

# Or run without a persistent installation.
uvx musterctl --version
```

For a managed developer environment, declare and pin the package there instead
of running `uv tool install` manually. This repository also exposes a Nix flake,
so Home Manager can install a pinned Git revision while managing the catalog at
`~/.config/musterctl/catalog.toml`.

On first use, inspect skills previously installed by
[`npx skills`](https://www.skills.sh/docs/cli):

```bash
musterctl setup inspect
musterctl setup init --all-tracked --plan
musterctl setup init --all-tracked
```

`inspect` is read-only and reports which installations still have source
lineage in `~/.agents/.skill-lock.json`. The plan shows what would enter the
catalog. Apply creates the external catalog without changing any installed
skill, and refuses to overwrite an existing catalog. Import individual entries
with repeatable `--include <skill>` flags, or create an empty starter catalog
with `musterctl setup init`.

Once a catalog exists:

```bash
musterctl
musterctl skills status
musterctl skills sync --dry-run
musterctl templates list
musterctl init example --template python-cli --plan
```

The bare command shows ambient state and likely next actions. `--plan` and
`--dry-run` perform validation without mutation; rerun the same complete request
without the preview flag to apply it. Use `musterctl <command> --help` for the
live interface.

## Catalog model

A catalog is local policy, normally versioned with the developer environment.
Each skill entry records the Skills CLI source selector, source repository/path,
ownership, update policy, optional immutable commit, and expected content hash.
Template entries compose independently versioned Git layers. `musterctl` never
stores or silently substitutes their source.

Third-party skills must be pinned to a full commit and digest. A generated
project also records exact installed content in `skills-lock.json`. Unmanaged
global skills are reported and left untouched.

## Development

Clone only when contributing:

```bash
git clone https://github.com/jdegregorio/musterctl.git
cd musterctl
uv sync --locked
uv run musterctl setup init --output /tmp/musterctl-catalog.toml --plan
./scripts/check
```

`uv sync --locked` creates the checkout's `.venv` from `uv.lock`; it is a
development setup command, not an end-user installation step. `./scripts/check`
checks the lock, formatting, lint, types, generated docs, repository boundaries,
tests and branch coverage, and a built-wheel smoke journey on Linux and macOS in
CI.

Repository contents are deliberately narrow:

- `src/musterctl/`: dependency-free runtime and CLI
- `docs/`: architecture, requirements traceability, and generated commands
- `tests/`: unit, integration, packaging, and end-to-end contracts
- `flake.nix`: pinned-consumer-friendly Nix package interface

Standalone `musterctl` Agent Skill guidance is generated for its own repository
with `musterctl-build --skill-output SKILL.md`; it is not bundled here.
