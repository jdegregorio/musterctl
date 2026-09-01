"""Machine-local record of the global snapshots musterctl installed."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from musterctl.catalog import Catalog
from musterctl.errors import EXIT_ENVIRONMENT, MusterctlError
from musterctl.resources import runtime_home


def global_lock_path(home: Path | None = None) -> Path:
    selected_home = home or runtime_home()
    explicit = os.environ.get("MUSTERCTL_STATE_HOME")
    if explicit:
        state_home = Path(explicit).expanduser().resolve()
    elif home is None and os.environ.get("XDG_STATE_HOME"):
        state_home = Path(os.environ["XDG_STATE_HOME"]).expanduser().resolve()
    else:
        state_home = selected_home / ".local" / "state"
    return state_home / "musterctl" / "global-lock.json"


def read_global_lock(home: Path | None = None) -> dict[str, dict[str, Any]]:
    path = global_lock_path(home)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        skills = raw["skills"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise MusterctlError(
            "global_lock_invalid",
            f"The musterctl global lock is unreadable: {exc}",
            EXIT_ENVIRONMENT,
            {"path": path},
            ("repair or remove the machine-local global lock",),
        ) from exc
    if not isinstance(raw, dict) or not isinstance(skills, dict):
        raise MusterctlError(
            "global_lock_invalid",
            "The musterctl global lock has no valid skills mapping.",
            EXIT_ENVIRONMENT,
            {"path": path},
        )
    return {
        str(name): entry for name, entry in skills.items() if isinstance(entry, dict)
    }


def write_global_lock(catalog: Catalog, home: Path | None = None) -> Path:
    path = global_lock_path(home)
    payload = {
        "skills": {
            name: {
                "content_sha256": catalog.skills[name].content_sha256,
                "source_pin": catalog.skills[name].pin,
            }
            for name in catalog.global_profile.skills
        },
        "version": 1,
    }
    content = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, raw_path = tempfile.mkstemp(
            prefix=f".{path.name}.", dir=path.parent
        )
        temporary = Path(raw_path)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    except OSError as exc:
        raise MusterctlError(
            "global_lock_write_failed",
            f"The machine-local global lock could not be written: {exc}",
            EXIT_ENVIRONMENT,
            {"path": path},
        ) from exc
    return path
