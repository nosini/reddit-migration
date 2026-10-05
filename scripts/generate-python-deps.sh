#!/usr/bin/env bash
# Regenerate python3-requirements.json from the dependencies in
# pyproject.toml with flatpak-pip-generator. pip runs inside the manifest's
# SDK, so environment markers and wheel tags match the runtime's Python; that
# needs a working `flatpak run`, also for the prebuilt cryptography and cffi
# wheels selected below.
#
# Extra arguments go to the generator.
set -euo pipefail
cd "$(dirname "$0")/.."

tools=$(bash scripts/builder-tools.sh)
manifest=$(grep -l '^id: ' ./*.yml)
sdk=$(sed -n 's/^sdk: *//p' "$manifest")
version=$(sed -n 's/^runtime-version: *//p' "$manifest" | tr -d "'\"")

venv=.cache/pip-generator
if [[ ! -x "$venv/bin/python" ]]; then
  python3 -m venv "$venv"
fi
"$venv/bin/pip" install -q --disable-pip-version-check 'requirements-parser>=0.11,<1' 'packaging>=23'

# Building cryptography and cffi from source would need Rust and a C
# toolchain. The generator doesn't evaluate python_version markers, so tomli
# (only needed before Python 3.11) has to be left out by name.
args=(--pyproject-file=pyproject.toml --output=python3-requirements
  --runtime="$sdk//$version" '--prefer-wheels=cryptography,cffi' --ignore-pkg=tomli)
# The generator reads the runtime's wheel tags with `from packaging import
# tags`, but the Freedesktop SDK only has the copy vendored in pip. Run a copy
# of the generator that imports that one.
generator=.cache/flatpak-pip-generator.py
sed 's/"from packaging import tags; "/"from pip._vendor.packaging import tags; "/' \
  "$tools/pip/flatpak-pip-generator.py" > "$generator"
grep -q 'from pip._vendor.packaging import tags' "$generator"
"$venv/bin/python" "$generator" "${args[@]}" "$@"
