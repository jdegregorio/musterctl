"""Small deterministic structured-output renderer."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

from musterctl.errors import MusterctlError

_BARE = re.compile(r"^[A-Za-z0-9_./@:+-]+$")


def atom(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Path):
        value = str(value)
    if isinstance(value, (int, float)):
        return str(value)
    rendered = str(value)
    if rendered and _BARE.fullmatch(rendered):
        return rendered
    return json.dumps(rendered, ensure_ascii=False, separators=(",", ":"))


class Document:
    def __init__(self) -> None:
        self._sections: list[list[str]] = []
        self._section_kinds: list[str] = []

    def _field_lines(self, lines: list[str]) -> None:
        if self._section_kinds and self._section_kinds[-1] == "fields":
            self._sections[-1].extend(lines)
            return
        self._sections.append(lines)
        self._section_kinds.append("fields")

    def scalar(self, key: str, value: object) -> None:
        self._field_lines([f"{key}: {atom(value)}"])

    def fields(self, values: Mapping[str, object]) -> None:
        self._field_lines([f"{key}: {atom(value)}" for key, value in values.items()])

    def items(self, name: str, values: Iterable[object]) -> None:
        materialized = list(values)
        lines = [f"{name}[{len(materialized)}]:"]
        lines.extend(f"  {atom(value)}" for value in materialized)
        self._sections.append(lines)
        self._section_kinds.append("items")

    def records(
        self,
        name: str,
        rows: Iterable[Mapping[str, object]],
        columns: Sequence[str],
    ) -> None:
        materialized = list(rows)
        lines = [f"{name}[{len(materialized)}]{{{','.join(columns)}}}:"]
        lines.extend(
            ",".join(atom(row.get(column)) for column in columns)
            for row in materialized
        )
        self._sections.append(lines)
        self._section_kinds.append("records")

    def extend(self, other: Document) -> None:
        self._sections.extend(other._sections)
        self._section_kinds.extend(other._section_kinds)

    def render(self) -> str:
        if not self._sections:
            return ""
        return "\n\n".join("\n".join(section) for section in self._sections) + "\n"


def error_document(error: MusterctlError) -> Document:
    document = Document()
    document.scalar("error", error.code)
    if error.fields:
        document.fields(error.fields)
    document.scalar("message", error.message)
    if error.next_actions:
        document.items("next", error.next_actions)
    return document
