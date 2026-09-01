from __future__ import annotations

from pathlib import Path

import pytest

from musterctl.generate import build, main, render_commands, render_skill


def test_committed_generated_files_are_current() -> None:
    root = Path(__file__).resolve().parents[2]
    assert build(True, root) == 0
    assert (root / "docs" / "commands.md").read_text(
        encoding="utf-8"
    ) == render_commands()


def test_generator_detects_and_repairs_drift(tmp_path: Path) -> None:
    path = tmp_path / "standalone-skill" / "SKILL.md"
    assert build(False, tmp_path, path) == 0
    assert path.read_text(encoding="utf-8") == render_skill()
    assert build(True, tmp_path, path) == 0
    path.write_text("drift", encoding="utf-8")
    assert build(True, tmp_path, path) == 1


def test_skill_only_generation_does_not_require_repository_docs(
    tmp_path: Path,
) -> None:
    output = tmp_path / "standalone" / "SKILL.md"
    assert build(False, tmp_path, output, include_docs=False) == 0
    assert not (tmp_path / "docs" / "commands.md").exists()
    assert build(True, tmp_path, output, include_docs=False) == 0


def test_generated_skill_defers_to_live_cli_and_includes_policy() -> None:
    skill = render_skill()
    assert "musterctl <command> --help" in skill
    assert "local catalog is versioned workstation policy" in skill
    assert "user-invocable: false" in skill


def test_generated_guidance_uses_the_installed_command() -> None:
    skill = render_skill()
    commands = render_commands()

    assert "Start with:\n\n```bash\nmusterctl\n```" in skill
    assert "uvx" not in skill
    assert "git+ssh" not in skill
    assert "uvx" not in commands


def test_generator_cli_can_print_and_write_standalone_skill(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--print-skill"]) == 0
    captured = capsys.readouterr()
    assert "name: musterctl" in captured.out
    output = tmp_path / "SKILL.md"
    assert main(["--skill-only", "--skill-output", str(output)]) == 0
    assert output.read_text(encoding="utf-8") == render_skill()
    assert main(["--check", "--skill-only", "--skill-output", str(output)]) == 0


def test_skill_only_requires_an_output() -> None:
    with pytest.raises(SystemExit) as error:
        main(["--skill-only"])
    assert error.value.code == 2
