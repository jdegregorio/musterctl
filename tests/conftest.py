from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from musterctl.catalog import Catalog
from musterctl.hashing import hash_tree


def _git_repo(path: Path, files: dict[str, str]) -> tuple[Path, str, str]:
    path.mkdir(parents=True)
    for relative, content in files.items():
        target = path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        if relative.startswith("scripts/"):
            target.chmod(0o755)
    subprocess.run(("git", "init", "--quiet", "-b", "main"), cwd=path, check=True)
    subprocess.run(("git", "add", "."), cwd=path, check=True)
    subprocess.run(
        (
            "git",
            "-c",
            "user.name=Tests",
            "-c",
            "user.email=tests@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "fixture",
        ),
        cwd=path,
        check=True,
    )
    revision = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return path, revision, hash_tree(path)


@pytest.fixture
def catalog(tmp_path: Path) -> Catalog:
    sources = tmp_path / "sources"
    skill_rows: list[str] = []
    skills = {
        "musterctl": (
            "Operate the agent development environment.",
            "Core",
            "first-party",
            ["global"],
        ),
        "skill-creator": (
            "Create and maintain portable skills.",
            "Core",
            "first-party",
            ["global"],
        ),
        "gh-axi": (
            "Operate GitHub for agent development workflows.",
            "Development",
            "third-party",
            ["global"],
        ),
        "project-helper": (
            "Test-only project helper.",
            "Test",
            "first-party",
            ["project"],
        ),
    }
    for name, (description, category, ownership, scopes) in skills.items():
        repo, revision, digest = _git_repo(
            sources / f"{name}-skill",
            {
                "SKILL.md": (
                    f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n"
                )
            },
        )
        skill_rows.extend(
            (
                "",
                f"[skills.{json.dumps(name)}]",
                f"description = {json.dumps(description)}",
                f"category = {json.dumps(category)}",
                f"ownership = {json.dumps(ownership)}",
                'update_policy = "pinned"',
                f"source = {json.dumps(f'{repo.as_uri()}@{revision}')}",
                f"source_url = {json.dumps(str(repo))}",
                'source_path = "."',
                f"source_skill = {json.dumps(name)}",
                f"pin = {json.dumps(revision)}",
                f"content_sha256 = {json.dumps(digest)}",
                f"scope = {json.dumps(scopes)}",
            )
        )

    base, base_revision, base_digest = _git_repo(
        sources / "agent-project-template",
        {
            "README.md": "# {{PROJECT_NAME}}\n",
            "scripts/check": "#!/bin/sh\nset -eu\ntest -f README.md\n",
            ".gitignore": ".cache/\n",
        },
    )
    python, python_revision, python_digest = _git_repo(
        sources / "python-cli-template",
        {
            "pyproject.toml": (
                '[project]\nname = "{{PROJECT_NAME}}"\nversion = "0.1.0"\n'
                "[project.scripts]\n"
                '"{{PROJECT_NAME}}" = "{{PROJECT_MODULE}}.cli:main"\n'
            ),
            "src/__PROJECT_MODULE__/__init__.py": "\n",
            "src/__PROJECT_MODULE__/cli.py": "def main() -> int:\n    return 0\n",
        },
    )
    path = tmp_path / "catalog.toml"
    path.write_text(
        "\n".join(
            [
                "version = 1",
                "",
                "[profiles.global]",
                'agents = ["codex", "claude-code"]',
                'skills = ["musterctl", "skill-creator", "gh-axi"]',
                *skill_rows,
                "",
                "[template_layers.agent-project]",
                f"source_url = {json.dumps(str(base))}",
                f"revision = {json.dumps(base_revision)}",
                'source_path = "."',
                f"content_sha256 = {json.dumps(base_digest)}",
                "",
                "[template_layers.python-cli]",
                f"source_url = {json.dumps(str(python))}",
                f"revision = {json.dumps(python_revision)}",
                'source_path = "."',
                f"content_sha256 = {json.dumps(python_digest)}",
                "",
                "[templates.base]",
                'category = "General"',
                'description = "Language-neutral project."',
                'layers = ["agent-project"]',
                "recommended_skills = []",
                "optional_categories = []",
                "",
                "[templates.python-cli]",
                'category = "Python"',
                'description = "Python command-line project."',
                'layers = ["agent-project", "python-cli"]',
                'recommended_skills = ["project-helper"]',
                "optional_categories = []",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return Catalog.load(path)


@pytest.fixture
def project_catalog(catalog: Catalog) -> Catalog:
    return catalog


@pytest.fixture
def isolated_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, catalog: Catalog
) -> Path:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("MUSTERCTL_HOME", str(home))
    monkeypatch.setenv("MUSTERCTL_CATALOG", str(catalog.path))
    return home
