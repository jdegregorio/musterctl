from __future__ import annotations

from pathlib import Path


def test_tool_repository_contains_no_catalog_skill_or_template_source() -> None:
    root = Path(__file__).resolve().parents[2]
    assert not (root / "catalog").exists()
    assert not (root / "skills").exists()
    assert not (root / "templates").exists()
