from __future__ import annotations

import tomllib
from copy import deepcopy
from typing import Any

import pytest

from musterctl.catalog import Catalog
from musterctl.errors import MusterctlError


def _broken(raw: dict[str, Any], case: str) -> dict[str, Any]:
    value = deepcopy(raw)
    skill = value["skills"]["project-helper"]
    layer = value["template_layers"]["agent-project"]
    if case == "version":
        value["version"] = 2
    elif case == "ownership":
        skill["ownership"] = "mystery"
    elif case == "name":
        value["skills"]["../escape"] = value["skills"].pop("project-helper")
    elif case == "policy":
        skill["update_policy"] = "sometimes"
    elif case == "scope":
        skill["scope"] = []
    elif case == "lineage":
        skill["source_url"] = ""
    elif case == "skill_path":
        skill["source_path"] = "../escape"
    elif case == "digest":
        skill["content_sha256"] = "bad"
    elif case == "pin":
        skill["pin"] = "short"
    elif case == "selector_pin":
        skill["source"] = "owner/repo"
    elif case == "layer_revision":
        layer["revision"] = "main"
    elif case == "layer_digest":
        layer["content_sha256"] = "bad"
    elif case == "layer_source":
        layer["source_url"] = ""
    elif case == "layer_path":
        layer["source_path"] = "../escape"
    elif case == "global_profile":
        del value["profiles"]["global"]
    elif case == "profile_unknown":
        value["profiles"]["global"]["skills"].append("missing")
    elif case == "profile_scope":
        value["profiles"]["global"]["skills"].append("project-helper")
    elif case == "template_unknown_skill":
        value["templates"]["base"]["required_skills"] = ["missing"]
    elif case == "template_global_skill":
        value["templates"]["base"]["required_skills"] = ["musterctl"]
    elif case == "template_scope":
        value["profiles"]["global"]["skills"].remove("musterctl")
        value["templates"]["base"]["required_skills"] = ["musterctl"]
    elif case == "manifest_path":
        value["templates"]["base"]["skill_manifest"] = "../project.toml"
    else:  # pragma: no cover - test table guards this
        raise AssertionError(case)
    return value


@pytest.mark.parametrize(
    "case",
    [
        "version",
        "ownership",
        "name",
        "policy",
        "scope",
        "lineage",
        "skill_path",
        "digest",
        "pin",
        "selector_pin",
        "layer_revision",
        "layer_digest",
        "layer_source",
        "layer_path",
        "global_profile",
        "profile_unknown",
        "profile_scope",
        "template_unknown_skill",
        "template_global_skill",
        "template_scope",
        "manifest_path",
    ],
)
def test_catalog_validation_rejects_each_invalid_policy(
    catalog: Catalog, case: str
) -> None:
    raw = tomllib.loads(catalog.path.read_text(encoding="utf-8"))
    with pytest.raises(MusterctlError) as error:
        Catalog.from_mapping(catalog.path, _broken(raw, case))
    assert error.value.code == "catalog_invalid"


def test_global_profile_property_has_structured_failure(catalog: Catalog) -> None:
    catalog.profiles.clear()
    with pytest.raises(MusterctlError) as error:
        _ = catalog.global_profile
    assert error.value.code == "catalog_invalid"
