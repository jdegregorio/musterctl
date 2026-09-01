from __future__ import annotations

from pathlib import Path


def test_tool_repository_contains_only_its_own_skill_source() -> None:
    root = Path(__file__).resolve().parents[2]
    assert not (root / "catalog").exists()
    assert not (root / "templates").exists()
    skill_names = sorted(
        path.name for path in (root / "skills").iterdir() if path.is_dir()
    )
    assert skill_names == ["musterctl"]
