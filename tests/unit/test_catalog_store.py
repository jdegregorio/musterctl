from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from musterctl.catalog import Catalog
from musterctl.catalog_store import CatalogStore
from musterctl.errors import MusterctlError
from musterctl.hashing import hash_tree
from musterctl.sources import SourceSnapshot, source_selector


def _source(path: Path) -> tuple[str, str]:
    path.mkdir()
    (path / "SKILL.md").write_text("# New helper\n", encoding="utf-8")
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
            "source",
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
    return revision, hash_tree(path)


def test_catalog_store_covers_add_configure_update_and_remove(
    catalog: Catalog, tmp_path: Path
) -> None:
    source = tmp_path / "new-source"
    revision, digest = _source(source)
    store = CatalogStore(catalog)
    store.add_skill(
        name="new-helper",
        description="New helper.",
        category="Test",
        ownership="personal",
        update_policy="latest",
        source_url=str(source),
        source_path=".",
        source_skill="new-helper",
        source_ref="main",
        snapshot=SourceSnapshot(revision, digest),
        scopes=("project",),
        global_profile=False,
        license_name=None,
    )
    store.write()
    loaded = Catalog.load(catalog.path)
    assert loaded.skill("new-helper").pin == revision
    assert loaded.skill("new-helper").source_ref == "main"

    configured = CatalogStore(loaded)
    configured.configure_skill("new-helper", scopes=("project",), global_profile=True)
    configured.write()
    loaded = Catalog.load(catalog.path)
    assert loaded.skill("new-helper").scopes == ("project", "global")
    assert "new-helper" in loaded.global_profile.skills

    updated = CatalogStore(loaded)
    new_snapshot = SourceSnapshot("f" * 40, "e" * 64)
    updated.update_skill("new-helper", new_snapshot)
    updated.write()
    loaded = Catalog.load(catalog.path)
    assert loaded.skill("new-helper").source == source_selector(
        str(source), "f" * 40, "."
    )

    removed = CatalogStore(loaded)
    references = removed.remove_skill("new-helper")
    assert "profile:global" in references
    removed.write()
    assert "new-helper" not in Catalog.load(catalog.path).skills


def test_catalog_store_conflicts_and_adoption_are_safe(catalog: Catalog) -> None:
    first = CatalogStore(catalog)
    stale = CatalogStore(catalog)
    first.configure_skill("musterctl", scopes=None, global_profile=False)
    first.write()
    stale.configure_skill("musterctl", scopes=None, global_profile=False)
    with pytest.raises(MusterctlError) as changed:
        stale.write()
    assert changed.value.code == "catalog_changed"

    loaded = Catalog.load(catalog.path)
    skill = loaded.skill("project-helper")
    adoption = CatalogStore(loaded)
    adoption.remove_skill(skill.name)
    adoption.adopt_skill(skill, global_profile=False)
    assert adoption.validate().skill(skill.name).pin == skill.pin
    with pytest.raises(MusterctlError) as duplicate:
        adoption.adopt_skill(skill, global_profile=False)
    assert duplicate.value.code == "catalog_skill_exists"
    with pytest.raises(MusterctlError) as unknown:
        adoption.configure_skill("missing", scopes=None, global_profile=True)
    assert unknown.value.code == "unknown_skill"


def test_catalog_store_rejects_unsupported_values(catalog: Catalog) -> None:
    store = CatalogStore(catalog)
    store.raw["unsupported"] = 1.5
    with pytest.raises(MusterctlError) as error:
        store.rendered()
    assert error.value.code == "catalog_write_unsupported"
