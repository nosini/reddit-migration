#!/usr/bin/env bash
# Regenerate python3-requirements.json from the dependencies in
# pyproject.toml with flatpak-pip-generator. pip runs inside the manifest's
# SDK, so environment markers and wheel tags match the runtime's Python; that
# needs a working `flatpak run`, also for the prebuilt wheels selected with
# PREFER_WHEELS (cryptography and cffi by default). Where Flatpak can't run,
# set PIP_GENERATOR_PYTHON to an interpreter of the runtime's Python version
# (python3.14 for Freedesktop 26.08) and PREFER_WHEELS to an empty value to
# run pip there instead.
#
# Extra arguments go to the generator.
set -euo pipefail
cd "$(dirname "$0")/.."

tools=$(bash scripts/builder-tools.sh)
manifest=$(grep -l '^id: ' ./*.yml)
sdk=$(sed -n 's/^sdk: *//p' "$manifest")
version=$(sed -n 's/^runtime-version: *//p' "$manifest" | tr -d "'\"")

python=${PIP_GENERATOR_PYTHON:-python3}
venv=.cache/pip-generator-$(basename "$python")
if [[ ! -x "$venv/bin/python" ]]; then
  "$python" -m venv "$venv"
fi
"$venv/bin/pip" install -q --disable-pip-version-check 'requirements-parser>=0.11,<1' 'packaging>=23'

version_probe='import platform; print(platform.python_version())'
args=(--requirements-file=.cache/requirements.txt --output=python3-requirements)
if [[ -n "${PIP_GENERATOR_PYTHON:-}" ]]; then
  # The generator runs pip3 from PATH.
  PATH="$PWD/$venv/bin:$PATH"
  runtime_python=$("$python" -c "$version_probe")
else
  args+=(--runtime="$sdk//$version")
  runtime_python=$(flatpak run --command=python3 "$sdk//$version" -c "$version_probe")
fi
# Building cryptography and cffi from source would need Rust and a C
# toolchain.
prefer_wheels=${PREFER_WHEELS-cryptography,cffi}
if [[ -n "$prefer_wheels" ]]; then
  args+=("--prefer-wheels=$prefer_wheels")
fi

# The app's dependencies, one per line. setuptools, the build backend, is in
# the Platform.
"$venv/bin/python" -c '
import tomllib
with open("pyproject.toml", "rb") as f:
    print("\n".join(tomllib.load(f)["project"]["dependencies"]))
' > .cache/pyproject-requirements.txt
# The generator ignores markers on the listed requirements; leave out the
# lines that don't apply to the runtime (see the script for details).
"$venv/bin/python" scripts/filter-requirements.py "$runtime_python" \
  .cache/pyproject-requirements.txt .cache/requirements.txt flathub.json

# For --prefer-wheels, the generator reads the runtime's wheel tags with
# `from packaging import tags`, but the Freedesktop SDK only has the copy
# vendored in pip. Run a copy of the generator that imports that one.
generator=.cache/flatpak-pip-generator.py
sed 's/"from packaging import tags; "/"from pip._vendor.packaging import tags; "/' \
  "$tools/pip/flatpak-pip-generator.py" > "$generator"
grep -q 'from pip._vendor.packaging import tags' "$generator"
# The generator skips packages it expects from the SDK. The Platform the app
# runs with has setuptools, Mako and Markdown, but not the others, so those
# are bundled when the app needs them. Check the list after updating the
# generator.
skipped=$(sed -n '/^    system_packages = \[$/,/^    \]$/s/^ *"\([^"]*\)",$/\1/p' "$generator" | sort | tr '\n' ' ')
if [[ "$skipped" != 'cython mako markdown meson packaging pip setuptools wheel ' ]]; then
  echo "The generator's system_packages changed: $skipped" >&2
  exit 1
fi
args+=('--ignore-installed=cython,meson,packaging,pip,wheel')
"$venv/bin/python" "$generator" "${args[@]}" "$@"
