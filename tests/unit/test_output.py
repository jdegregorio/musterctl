from __future__ import annotations

from pathlib import Path

from musterctl.errors import MusterctlError
from musterctl.output import Document, atom, error_document


def test_atom_uses_bare_values_only_when_unambiguous() -> None:
    assert atom("current") == "current"
    assert atom("has spaces") == '"has spaces"'
    assert atom("a,b") == '"a,b"'
    assert atom(True) == "true"
    assert atom(None) == "null"
    assert atom(Path("/tmp/example")) == "/tmp/example"


def test_document_groups_fields_and_represents_empty_collections() -> None:
    document = Document()
    document.scalar("context", "global")
    document.fields({"health": "ok", "updates": 0})
    document.items("next", ())
    document.records("skills", (), ("name", "status"))
    assert document.render() == (
        "context: global\n"
        "health: ok\n"
        "updates: 0\n\n"
        "next[0]:\n\n"
        "skills[0]{name,status}:\n"
    )


def test_document_extend_preserves_compact_sections() -> None:
    left = Document()
    left.scalar("a", 1)
    right = Document()
    right.items("values", ("x",))
    left.extend(right)
    assert left.render() == "a: 1\n\nvalues[1]:\n  x\n"


def test_empty_document_renders_nothing() -> None:
    assert Document().render() == ""


def test_error_document_has_stable_recovery_shape() -> None:
    error = MusterctlError(
        "unknown_thing",
        "That thing is unknown.",
        fields={"thing": "wat"},
        next_actions=("musterctl things list",),
    )
    assert error_document(error).render() == (
        "error: unknown_thing\n"
        "thing: wat\n"
        'message: "That thing is unknown."\n\n'
        "next[1]:\n"
        '  "musterctl things list"\n'
    )
