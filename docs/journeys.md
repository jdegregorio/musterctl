# End-to-end lifecycle journeys

This is the product-level routing map. Live syntax remains authoritative through
`musterctl <command> --help`; requirement IDs and safety details live in
`requirements.md` and `architecture.md`.

| User outcome | Inspect | Plan | Apply | Verified end state |
| --- | --- | --- | --- | --- |
| Understand an existing machine | `setup inspect` | — | — | Global/project installs show lineage, hashes, catalog comparison, and name conflicts. |
| Bootstrap catalog policy | `setup inspect` | `setup init --include-path … --plan` | Replay without `--plan` | Version-controlled catalog exists; installed copies are unchanged. |
| Add a known Git-backed skill | `catalog search/show` | `catalog add … --plan` | Replay emitted command | Source ref is resolved to a commit/digest; catalog entry is valid. |
| Adopt an existing install | `setup inspect` | `catalog adopt <path> --plan` | Replay emitted command | Installed hash matches source; catalog records lineage without reinstalling. |
| Resolve an anonymous install | `setup inspect` (`no_source`) | Agent plans a dedicated repository through `gh-axi` | Create/push source, then `catalog add` | Skill becomes durable source before entering catalog policy. |
| Choose global skills | `catalog show`, `skills status` | `catalog configure … --plan` | Replay; then `skills sync --dry-run`/apply | Catalog profile and installed global copies agree. |
| Tidy old global copies | `setup inspect` | `skills prune --plan` | Explicit names or `--all-unmanaged` | Selected unmanaged global/adaptor paths are gone; projects are untouched. |
| Improve a skill | `skills diff`, `skills source` | `skills checkout … --plan` | Edit/test/commit/push source; `catalog update` | Catalog points to reviewed immutable source, not an installed-copy edit. |
| Roll out an improved skill | `skills status`, `projects status` | `skills sync --dry-run`, `projects sync --plan` | Apply each separately | Global profile and managed project locks/copies advance; local drift blocks by default. |
| Start a project | `templates list/show`, `skills available` | `init … --plan` | Replay emitted command | Pinned template, required/selected skills, adapters, lock, Git repo, and checks are present. |
| Retire catalog policy | `catalog show`, `projects status` | `catalog remove … --plan` | Replay emitted command | Policy references are removed; installed project/global copies remain for deliberate handling. |

## Durable ownership rules

- Catalog: version-controlled workstation policy, external to the package.
- Skill source: the skill owner's Git repository; installed copies are
  deployments.
- Template source: an independent Git repository; its skill manifest contains
  names, not skill payloads.
- Project: owns materialized project skills and `skills-lock.json`, but updates
  still flow from catalog source.
- Machine state: the global lock records what musterctl installed; it is not
  desired-state policy and is never committed.

## Deliberate boundaries

`musterctl` does not create a repository for anonymous content, choose a source
owner, commit or push source changes, edit a generated Home Manager/Nix target,
activate the workstation environment, remove project skills, or infer that local
drift should be discarded. Those decisions require the agent, Git tooling, and
explicit user intent.
