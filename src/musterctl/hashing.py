"""Content hashing shared by catalog, installed-state, and lock handling."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path


def hash_tree(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(root)
        if ".git" in relative.parts:
            continue
        digest.update(relative.as_posix().encode())
        digest.update(b"\0")
        if path.is_symlink():
            digest.update(b"symlink\0")
            digest.update(os.fsencode(path.readlink()))
        elif path.is_file():
            digest.update(b"file\0")
            digest.update(path.read_bytes())
        elif path.is_dir():
            digest.update(b"directory\0")
        else:
            digest.update(b"other\0")
        digest.update(b"\0")
    return digest.hexdigest()
