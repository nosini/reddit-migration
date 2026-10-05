#!/usr/bin/env python3
"""Pin the Python wheels that reddit-migration needs on top of the runtime.

The Freedesktop 26.08 runtime ships Python 3.14, pip and setuptools. The
dependencies declared in pyproject.toml come from PyPI as prebuilt wheels,
resolved once per architecture. Wheels that differ between architectures
(cffi, cryptography) are marked with only-arches.

Run with Python 3.14 so dependency environment markers match the runtime.
"""

import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import tomllib
from urllib.parse import unquote, urlsplit

HERE = Path(__file__).resolve().parent
PYPROJECT = HERE.parent / "pyproject.toml"
ARCHES = {
    "x86_64": ["manylinux_2_34_x86_64", "manylinux_2_28_x86_64", "manylinux2014_x86_64"],
    "aarch64": ["manylinux_2_34_aarch64", "manylinux_2_28_aarch64", "manylinux2014_aarch64"],
}


def resolve(requirements, platforms):
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "report.json"
        command = [
            sys.executable, "-m", "pip", "install", "--dry-run", "--quiet",
            "--ignore-installed", "--only-binary=:all:",
            "--implementation=cp", "--python-version=3.14",
            *(f"--platform={platform}" for platform in platforms),
            "--index-url=https://pypi.org/simple",
            "--target", str(Path(tmp) / "target"),
            "--report", str(report), *requirements,
        ]
        subprocess.run(command, check=True)
        return json.loads(report.read_text())["install"]


def write_module(name, requirements):
    # url -> (source entry, arches it is needed on)
    wheels = {}
    pins = {}
    for arch, platforms in ARCHES.items():
        for package in resolve(requirements, platforms):
            download = package["download_info"]
            url = download["url"]
            meta = package["metadata"]
            pins[meta["name"].lower()] = f"{meta['name']}=={meta['version']}"
            source, arches = wheels.setdefault(url, ({
                "type": "file",
                "url": url,
                "dest-filename": unquote(urlsplit(url).path.rsplit("/", 1)[1]),
                "sha256": download["archive_info"]["hashes"]["sha256"],
            }, []))
            arches.append(arch)

    sources = []
    for source, arches in sorted(wheels.values(), key=lambda item: item[0]["dest-filename"].lower()):
        if len(arches) != len(ARCHES):
            source["only-arches"] = arches
        sources.append(source)

    module = {
        "name": name,
        "buildsystem": "simple",
        "build-commands": [
            'pip3 install --no-index --find-links="${PWD}" --only-binary=:all:'
            ' --no-deps --ignore-installed --prefix="${FLATPAK_DEST}" '
            + " ".join(shlex.quote(pins[key]) for key in sorted(pins)),
        ],
        "sources": sources,
    }
    (HERE / f"{name}.json").write_text(json.dumps(module, indent=2) + "\n")


def main():
    # pip evaluates dependency environment markers against the running Python.
    if sys.version_info[:2] != (3, 14):
        raise SystemExit("Run this script with Python 3.14 (the runtime's version).")
    project = tomllib.loads(PYPROJECT.read_text())["project"]
    write_module("python-packages", project["dependencies"])


if __name__ == "__main__":
    main()
