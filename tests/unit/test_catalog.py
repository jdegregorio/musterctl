from __future__ import annotations

from pathlib import Path

import pytest

from musterctl.catalog import Catalog
from musterctl.errors import EXIT_ENVIRONMENT, MusterctlError


def test_catalog_is_external_small_and_source_complete(catalog: Catalog) -> None:
    assert len(catalog.skills) == 4
    assert catalog.global_profile.skills == ("musterctl", "skill-creator", "gh-axi")
    third_party = catalog.skill("gh-axi")
    assert third_party.ownership == "third-party"
    assert third_party.update_policy == "pinned"
    assert third_party.pin and len(third_party.pin) == 40
    assert third_party.pin in third_party.source
    assert len(third_party.content_sha256 or "") == 64
    assert catalog.template_layer("agent-project").source_url


def test_catalog_search_and_unknown_recovery(catalog: Catalog) -> None:
    assert [skill.name for skill in catalog.search("github development")] == ["gh-axi"]
    assert catalog.search("not-present") == []
    assert len(catalog.search("")) == 4
    with pytest.raises(MusterctlError) as skill_error:
        catalog.skill("gh-axis")
    assert "gh-axi" in str(skill_error.value.fields["available_matches"])
    with pytest.raises(MusterctlError) as template_error:
        catalog.template("python-command")
    assert template_error.value.next_actions == ("musterctl templates list",)


def test_catalog_rejects_unpinned_third_party(catalog: Catalog, tmp_path: Path) -> None:
    text = catalog.path.read_text(encoding="utf-8")
    text = text.replace(
        'ownership = "third-party"\nupdate_policy = "pinned"',
        'ownership = "third-party"\nupdate_policy = "latest"',
    )
    path = tmp_path / "invalid.toml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(MusterctlError) as error:
        Catalog.load(path)
    assert "third-party source must be pinned" in error.value.message


def test_catalog_rejects_bad_source_and_template_metadata(
    catalog: Catalog, tmp_path: Path
) -> None:
    text = catalog.path.read_text(encoding="utf-8")
    text = text.replace(catalog.skill("musterctl").pin or "", "v1", 2)
    text = text.replace('layers = ["agent-project"]', 'layers = ["missing-layer"]', 1)
    path = tmp_path / "invalid.toml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(MusterctlError) as error:
        Catalog.load(path)
    assert "pinned source needs a full commit SHA" in error.value.message
    assert "unknown layer missing-layer" in error.value.message


def test_catalog_rejects_more_than_five_skills(
    catalog: Catalog, tmp_path: Path
) -> None:
    text = catalog.path.read_text(encoding="utf-8")
    entry = text[
        text.index('[skills."project-helper"]') : text.index(
            "[template_layers.agent-project]"
        )
    ]
    text = text.replace(
        "[template_layers.agent-project]",
        entry.replace('[skills."project-helper"]', '[skills."extra-one"]').replace(
            'source_skill = "project-helper"', 'source_skill = "extra-one"'
        )
        + entry.replace('[skills."project-helper"]', '[skills."extra-two"]').replace(
            'source_skill = "project-helper"', 'source_skill = "extra-two"'
        )
        + "[template_layers.agent-project]",
    )
    path = tmp_path / "too-many.toml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(MusterctlError) as error:
        Catalog.load(path)
    assert "more than five skills" in error.value.message


def test_catalog_wraps_toml_errors(tmp_path: Path) -> None:
    path = tmp_path / "bad.toml"
    path.write_text("not = [valid", encoding="utf-8")
    with pytest.raises(MusterctlError) as error:
        Catalog.load(path)
    assert error.value.code == "catalog_invalid"
    assert error.value.exit_code == EXIT_ENVIRONMENT
