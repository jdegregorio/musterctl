"""Generate command docs and musterctl skill guidance from shared metadata."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from musterctl.metadata import COMMANDS, POLICIES, PRODUCT_DESCRIPTION


def render_skill() -> str:
    policies = "\n".join(f"- {policy}" for policy in POLICIES)
    return f"""---
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

{policies}

Treat stable error categories, exit codes, explicit empty collections, and
`next` actions as recovery guidance. Do not add an interactive confirmation step
to a complete request.

Product: {PRODUCT_DESCRIPTION}
"""


def render_commands() -> str:
    lines = [
        "# Command reference",
        "",
        (
            "Generated from the same metadata that powers CLI help and the "
            "colocated musterctl skill guidance. The running "
            "`musterctl <command> --help` "
            "interface is authoritative."
        ),
        "",
        "| Command | Purpose | Mutation | Safety |",
        "| --- | --- | --- | --- |",
    ]
    for command in COMMANDS:
        purpose = command.purpose.replace("|", "\\|")
        safety = command.safety.replace("|", "\\|")
        lines.append(
            f"| `{command.display_path}` | {purpose} | "
            f"{'yes' if command.mutates else 'no'} | {safety} |"
        )
    lines.extend(("", "## Examples", ""))
    for command in COMMANDS:
        lines.extend(f"- `{example}`" for example in command.examples)
    lines.append("")
    return "\n".join(lines)


def generated_files(root: Path | None = None) -> dict[Path, str]:
    selected_root = root or Path(__file__).resolve().parents[2]
    return {
        selected_root / "docs" / "commands.md": render_commands(),
        selected_root / "skills" / "musterctl" / "SKILL.md": render_skill(),
    }


def _write_or_check(path: Path, content: str, check: bool) -> bool:
    if check:
        return not path.is_file() or path.read_text(encoding="utf-8") != content
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return False


def build(
    check: bool,
    root: Path | None = None,
    skill_output: Path | None = None,
    include_repository_artifacts: bool = True,
) -> int:
    drift = (
        [
            path
            for path, content in generated_files(root).items()
            if _write_or_check(path, content, check)
        ]
        if include_repository_artifacts
        else []
    )
    if skill_output is not None and _write_or_check(
        skill_output, render_skill(), check
    ):
        drift.append(skill_output)
    if drift:
        for path in drift:
            print(f"generated_drift: {path}", file=sys.stderr)
        print("next: uv run musterctl-build", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate musterctl artifacts.")
    parser.add_argument(
        "--check", action="store_true", help="fail if generated files would change"
    )
    parser.add_argument(
        "--skill-output",
        type=Path,
        help="also write or check an exported copy of musterctl SKILL.md guidance",
    )
    parser.add_argument(
        "--skill-only",
        action="store_true",
        help="skip committed repository artifacts; requires --skill-output",
    )
    parser.add_argument(
        "--print-skill",
        action="store_true",
        help="print musterctl skill guidance to stdout",
    )
    arguments = parser.parse_args(argv)
    if arguments.print_skill:
        sys.stdout.write(render_skill())
        return 0
    if arguments.skill_only and arguments.skill_output is None:
        parser.error("--skill-only requires --skill-output")
    return build(
        arguments.check,
        skill_output=arguments.skill_output,
        include_repository_artifacts=not arguments.skill_only,
    )


if __name__ == "__main__":
    raise SystemExit(main())
