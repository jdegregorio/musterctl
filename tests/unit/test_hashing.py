from __future__ import annotations

from pathlib import Path

from musterctl.hashing import hash_tree


def test_hash_tree_is_deterministic_and_content_sensitive(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    (root / "b.txt").write_text("b", encoding="utf-8")
    (root / "a.txt").write_text("a", encoding="utf-8")
    first = hash_tree(root)
    assert hash_tree(root) == first
    (root / "a.txt").write_text("changed", encoding="utf-8")
    assert hash_tree(root) != first


def test_hash_tree_ignores_git_metadata_and_hashes_symlinks(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    (root / ".git").mkdir(parents=True)
    (root / ".git" / "state").write_text("one", encoding="utf-8")
    (root / "content").write_text("same", encoding="utf-8")
    (root / "alias").symlink_to("content")
    first = hash_tree(root)
    (root / ".git" / "state").write_text("two", encoding="utf-8")
    assert hash_tree(root) == first
    (root / "alias").unlink()
    (root / "alias").symlink_to("other-content")
    assert hash_tree(root) != first
