---
name: musterctl
description: >-
  Operate a catalog-backed agent development environment: inspect approved
  skill lineage, reconcile global Agent Skills, and initialize agent-ready
  projects. Use for environment or bootstrap work; defer ordinary project
  implementation to that project's own workflow.
user-invocable: false
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

## Policies

- The local catalog is versioned workstation policy, not package state.
- The Python package contains no catalog, Agent Skill payload, or project-template source; this skill is versioned beside the CLI source.
- Pinned skills use explicit source revisions and content digests.
- Project skills are copied into the repository and recorded in skills-lock.json.
- Global skills must not be duplicated into projects.
- Use --plan or --dry-run before meaningful mutations.
- Complete mutation requests never prompt for confirmation.

Treat stable error categories, exit codes, explicit empty collections, and
`next` actions as recovery guidance. Do not add an interactive confirmation step
to a complete request.

Product: Agent-native control plane for external skill catalogs.
