---
name: musterctl
description: >-
  Operate a source-backed Agent Skill environment: discover installed skills,
  maintain catalog policy, reconcile global and project copies, improve skills
  at source, and initialize agent-ready projects. Use for skill lifecycle,
  environment, or project-bootstrap work.
metadata:
  short-description: Operate the curated agent environment
---

# musterctl

Use the installed `musterctl` command as the factual control plane. Its external
catalog is the authoritative policy for the current workstation.

Start with:

```bash
musterctl
```

Follow contextual `next` actions. For exact syntax, use the live interface:

```bash
musterctl <command> --help
```

## Route the request

- Existing-machine inventory or migration: `musterctl setup inspect`.
- Catalog additions, adoption, scope, removal, or upstream updates:
  `musterctl catalog --help`.
- Global state and intentional cleanup: `musterctl skills status`,
  `musterctl skills sync --dry-run`, and `musterctl skills prune --plan`.
- Cross-project state or rollout: `musterctl projects status` and
  `musterctl projects sync --plan`.
- New project: inspect `templates` and `skills available`, then use
  `musterctl init ... --plan`.

When asked to improve a skill, treat an installed global or project copy as a
deployment, not its source. Start with `musterctl skills diff <name>` and
`musterctl skills source <name>`. Checkout or open the source repository, make
and test the change there, commit and push it, advance the catalog with
`musterctl catalog update <name> --plan`, then separately reconcile global and
project copies. Never overwrite detected installed-copy changes unless the user
explicitly chooses the corresponding `--replace-drift` path.

## Policies

- The local catalog is versioned workstation policy, not package state.
- The Python package contains no catalog, Agent Skill payload, or project-template source; this skill is versioned beside the CLI source.
- Pinned skills use explicit source revisions and content digests.
- Project skills are copied into the repository and recorded in skills-lock.json.
- Global skills must not be duplicated into projects.
- Installed-copy edits are drift: move intentional changes to source first.
- Catalog updates never silently rewrite global or project installations.
- Project reconciliation never removes a project skill.
- Use --plan or --dry-run before meaningful mutations.
- Complete mutation requests never prompt for confirmation.

Treat stable error categories, exit codes, explicit empty collections, and
`next` actions as recovery guidance. Do not add an interactive confirmation step
to a complete request.

Product: Agent-native control plane for source-backed skill catalogs and projects.
