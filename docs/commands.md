# Command reference

Generated from the same metadata that powers CLI help and the colocated musterctl skill guidance. The running `musterctl <command> --help` interface is authoritative.

| Command | Purpose | Mutation | Safety |
| --- | --- | --- | --- |
| `musterctl` | Show ambient global or project state and likely next actions. | no | read-only |
| `musterctl status` | Report aggregated catalog, global skill, and project skill health. | no | read-only |
| `musterctl catalog search` | Search curated skills by name, category, ownership, or description. | no | read-only |
| `musterctl catalog show` | Inspect one skill's source, ownership, update policy, and scopes. | no | read-only |
| `musterctl catalog add` | Plan or add one verified Git-backed skill to the external catalog. | yes | use --plan first; apply resolves the ref and writes one catalog file |
| `musterctl catalog adopt` | Plan or adopt a discovered installation with verifiable source lineage. | yes | no-source and source-mismatched installs are blocked |
| `musterctl catalog remove` | Plan or remove catalog policy while preserving every installed copy. | yes | installed global and project content is never removed |
| `musterctl catalog configure` | Plan or change one skill's allowed scopes and global-profile membership. | yes | configuration changes do not immediately alter installations |
| `musterctl catalog check-updates` | Resolve source refs and report catalog snapshots that can advance. | no | read-only network operation |
| `musterctl catalog update` | Plan or advance one catalog pin and digest from its verified source ref. | yes | does not rewrite installed global or project copies |
| `musterctl templates list` | List available project templates. | no | read-only |
| `musterctl templates show` | Inspect template layers, recommendations, and next actions. | no | read-only |
| `musterctl skills available` | Expose global exclusions, template recommendations, and usable project skills. | no | read-only |
| `musterctl skills status` | Inspect installed global and current-project skill state. | no | read-only |
| `musterctl skills sync` | Plan or reconcile the global profile through the noninteractive Skills CLI. | yes | use --dry-run first; unmanaged skills are never removed |
| `musterctl skills diff` | Compare an installed skill with its exact configured source. | no | read-only |
| `musterctl skills source` | Show exact source lineage and the source-first improvement workflow. | no | read-only |
| `musterctl skills checkout` | Plan or create an editable checkout of a skill's configured source. | yes | never replaces a path and rejects source refs ahead of catalog content |
| `musterctl skills prune` | Plan or remove explicitly selected unmanaged global skill copies. | yes | managed global and all project skills are protected |
| `musterctl projects status` | Discover managed project skills and compare copies, locks, and catalog. | no | read-only; defaults to configured roots or ~/Repos |
| `musterctl projects sync` | Plan or transactionally advance managed skill copies across projects. | yes | never removes skills; local changes block apply by default |
| `musterctl setup inspect` | Discover global and project installs, lineage, hashes, and conflicts. | no | read-only; works before a catalog exists |
| `musterctl setup init` | Plan or create an external catalog from selected source-tracked installs. | yes | use --plan first; existing catalogs are never overwritten |
| `musterctl init` | Plan or transactionally create an agent-ready project. | yes | use --plan first; existing destinations are never overwritten |

## Examples

- `musterctl`
- `musterctl status`
- `musterctl catalog search deployment`
- `musterctl catalog show gh-axi`
- `musterctl catalog add helper --source owner/helper --plan`
- `musterctl catalog adopt ~/.agents/skills/helper --plan`
- `musterctl catalog remove helper --plan`
- `musterctl catalog configure helper --no-global --scope project --plan`
- `musterctl catalog check-updates`
- `musterctl catalog update helper --plan`
- `musterctl templates list`
- `musterctl templates show python-cli`
- `musterctl skills available --template python-cli`
- `musterctl skills status`
- `musterctl skills sync --dry-run`
- `musterctl skills sync`
- `musterctl skills diff musterctl`
- `musterctl skills source musterctl`
- `musterctl skills checkout musterctl --plan`
- `musterctl skills prune --plan`
- `musterctl projects status`
- `musterctl projects sync --plan`
- `musterctl setup inspect`
- `musterctl setup init --plan`
- `musterctl setup init --all-tracked --plan`
- `musterctl init example --template python-cli --plan`
- `musterctl init example --template python-cli`
