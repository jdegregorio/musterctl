"""Exercise the built wheel from outside the source checkout."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    wheels = sorted((root / "dist").glob("musterctl-*.whl"))
    if len(wheels) != 1:
        raise SystemExit(f"expected one musterctl wheel, found {len(wheels)}")
    with tempfile.TemporaryDirectory(prefix="musterctl-wheel-") as directory:
        isolated = Path(directory)
        with zipfile.ZipFile(wheels[0]) as archive:
            forbidden = ("catalog/", "skills/", "templates/", "musterctl/_resources/")
            assert not any(name.startswith(forbidden) for name in archive.namelist())
            archive.extractall(isolated / "site")
        catalog = isolated / "config" / "musterctl" / "catalog.toml"
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(isolated / "site")
        environment["MUSTERCTL_HOME"] = str(isolated / "home")
        environment["MUSTERCTL_CATALOG"] = str(catalog)
        commands = (
            (
                sys.executable,
                "-m",
                "musterctl",
                "setup",
                "init",
                "--output",
                str(catalog),
            ),
            (sys.executable, "-m", "musterctl", "status"),
            (sys.executable, "-m", "musterctl", "templates", "list"),
        )
        for command in commands:
            result = subprocess.run(
                command,
                cwd=isolated,
                env=environment,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                sys.stderr.write(result.stdout)
                sys.stderr.write(result.stderr)
                return result.returncode
    print(f"Wheel smoke test passed: {wheels[0].name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
