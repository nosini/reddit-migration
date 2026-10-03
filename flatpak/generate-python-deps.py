#!/usr/bin/env python3
"""Regenerate python3-deps.json, the Flatpak module with the app's PyPI dependencies.

Resolves the [project].dependencies from pyproject.toml for the runtime's
Python on each architecture and pins every wheel by URL and sha256. Wheels
that differ per architecture (cffi, cryptography) get `only-arches`.

Needs Python 3.11+ and pip 23.1+ (for `pip install --dry-run --report`).
Run it after changing dependencies or the runtime version:

    python3 flatpak/generate-python-deps.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
PYPROJECT = HERE.parent / "pyproject.toml"
OUTPUT = HERE / "python3-deps.json"

# Python shipped by org.freedesktop.Platform 26.08.
PYTHON_VERSION = "3.14"

# Flatpak arch -> manylinux platform tags, newest first. The runtime's glibc is
# far newer than any of these, so every listed tag is usable.
ARCHES = {
    "x86_64": ["manylinux_2_34_x86_64", "manylinux_2_28_x86_64", "manylinux2014_x86_64"],
    "aarch64": ["manylinux_2_34_aarch64", "manylinux_2_28_aarch64", "manylinux2014_aarch64"],
}


def resolve(requirements: list[str], platforms: list[str]) -> list[dict]:
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "report.json"
        cmd = [
            sys.executable, "-m", "pip", "install",
            "--quiet", "--dry-run", "--ignore-installed",
            "--report", str(report),
            "--target", str(Path(tmp) / "target"),
            "--only-binary=:all:",
            "--implementation", "cp",
            "--python-version", PYTHON_VERSION,
        ]
        for platform in platforms:
            cmd += ["--platform", platform]
        subprocess.run(cmd + requirements, check=True)
        install = json.loads(report.read_text())["install"]

    wheels = []
    for item in install:
        info = item["download_info"]
        wheels.append({
            "name": item["metadata"]["name"],
            "url": info["url"],
            "sha256": info["archive_info"]["hashes"]["sha256"],
        })
    return wheels


def main() -> int:
    project = tomllib.loads(PYPROJECT.read_text())["project"]
    requirements = project["dependencies"]

    # url -> source entry, keeping the arches each wheel is needed on.
    sources: dict[str, dict] = {}
    names: set[str] = set()
    for arch, platforms in ARCHES.items():
        for wheel in resolve(requirements, platforms):
            names.add(wheel["name"])
            entry = sources.setdefault(wheel["url"], {
                "type": "file",
                "url": wheel["url"],
                "sha256": wheel["sha256"],
                "arches": [],
            })
            entry["arches"].append(arch)

    for entry in sources.values():
        arches = entry.pop("arches")
        if len(arches) != len(ARCHES):
            entry["only-arches"] = arches

    module = {
        "name": "python3-deps",
        "buildsystem": "simple",
        "build-commands": [
            "pip3 install --verbose --no-index --find-links=\"file://${PWD}\""
            " --prefix=${FLATPAK_DEST} --no-build-isolation " + " ".join(sorted(names)),
        ],
        "sources": sorted(sources.values(), key=lambda s: s["url"].rsplit("/", 1)[1].lower()),
    }
    OUTPUT.write_text(json.dumps(module, indent=4) + "\n")
    print(f"Wrote {OUTPUT.relative_to(Path.cwd()) if OUTPUT.is_relative_to(Path.cwd()) else OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
