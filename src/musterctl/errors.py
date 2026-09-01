"""Stable failures intended for autonomous recovery."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

EXIT_USAGE = 2
EXIT_CONFLICT = 3
EXIT_ENVIRONMENT = 4
EXIT_INTERNAL = 70


@dataclass(slots=True)
class MusterctlError(Exception):
    code: str
    message: str
    exit_code: int = EXIT_USAGE
    fields: Mapping[str, object] = field(default_factory=dict)
    next_actions: Sequence[str] = field(default_factory=tuple)

    def __str__(self) -> str:
        return self.message
