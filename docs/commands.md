# Command reference

Generated from the same metadata that powers CLI help and standalone musterctl skill guidance. The running `musterctl <command> --help` interface is authoritative.

| Command | Purpose | Mutation | Safety |
| --- | --- | --- | --- |
| `musterctl` | Show ambient global or project state and likely next actions. | no | read-only |
| `musterctl status` | Report aggregated catalog, global skill, and project skill health. | no | read-only |
| `musterctl catalog search` | Search curated skills by name, category, ownership, or description. | no | read-only |
| `musterctl catalog show` | Inspect one skill's source, ownership, update policy, and scopes. | no | read-only |
| `musterctl templates list` | List available project templates. | no | read-only |
| `musterctl templates show` | Inspect template layers, recommendations, and next actions. | no | read-only |
| `musterctl skills available` | Expose global exclusions, template recommendations, and usable project skills. | no | read-only |
| `musterctl skills status` | Inspect installed global and current-project skill state. | no | read-only |
| `musterctl skills sync` | Plan or reconcile the global profile through the noninteractive Skills CLI. | yes | use --dry-run first; unmanaged skills are never removed |
| `musterctl skills diff` | Compare an installed skill with its exact configured source. | no | read-only |
| `musterctl setup inspect` | Inspect existing global skills and their Skills CLI source lineage. | no | read-only; works before a catalog exists |
| `musterctl setup init` | Plan or create an external catalog from selected tracked installs. | yes | use --plan first; existing catalogs are never overwritten |
| `musterctl init` | Plan or transactionally create an agent-ready project. | yes | use --plan first; existing destinations are never overwritten |

## Examples

- `musterctl`
- `musterctl status`
- `musterctl catalog search deployment`
- `musterctl catalog show gh-axi`
- `musterctl templates list`
- `musterctl templates show python-cli`
- `musterctl skills available --template python-cli`
- `musterctl skills status`
- `musterctl skills sync --dry-run`
- `musterctl skills sync`
- `musterctl skills diff musterctl`
- `musterctl setup inspect`
- `musterctl setup init --plan`
- `musterctl setup init --all-tracked --plan`
- `musterctl init example --template python-cli --plan`
- `musterctl init example --template python-cli`
