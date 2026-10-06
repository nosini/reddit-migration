#!/usr/bin/env bash
# Test for scripts/generate-python-deps.sh: a package that the generator
# expects from the SDK, but that the Platform lacks, must get a module.
# Downloads from GitHub and PyPI. PIP_GENERATOR_PYTHON defaults to python3,
# which needs Python 3.11 or newer; without the SDK, no wheels are preferred.
set -euo pipefail
root=$(realpath "$(dirname "$0")/../..")
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

mkdir "$tmp/repo"
cp -a "$root/scripts" "$root"/*.yml "$tmp/repo/"
if [[ -d "$root/.cache/flatpak-builder-tools" ]]; then
  mkdir "$tmp/repo/.cache"
  cp -a "$root/.cache/flatpak-builder-tools" "$tmp/repo/.cache/"
fi
cd "$tmp/repo"

# generate REQUIREMENT...: run the script with REQUIREMENTs as the
# project's dependencies and print the generated modules with their number
# of sources.
generate() {
  python3 -c '
import json, sys
print("[project]\ndependencies =", json.dumps(sys.argv[1:]))
' "$@" > pyproject.toml
  PIP_GENERATOR_PYTHON=${PIP_GENERATOR_PYTHON:-python3} PREFER_WHEELS='' \
    bash scripts/generate-python-deps.sh > "$tmp/log" 2>&1 \
    || { cat "$tmp/log" >&2; exit 1; }
  python3 -c '
import json
data = json.load(open("python3-requirements.json"))
for module in data.get("modules", [data]):
    print(module["name"], len(module["sources"]))
'
}

# packaging is in the SDK, but not in the Platform.
modules=$(generate 'packaging==26.0' 'tomli==2.2.1; python_version < "3.11"')
[[ "$modules" == 'python3-packaging 1' ]] || { echo "FAIL: got $modules" >&2; exit 1; }

# An aarch64-only package for an aarch64-only app, generated on any machine.
echo '{"only-arches": ["aarch64"]}' > flathub.json
modules=$(generate 'packaging==26.0; platform_machine == "aarch64"')
[[ "$modules" == 'python3-packaging 1' ]] || { echo "FAIL: got $modules" >&2; exit 1; }

echo 'generate-python-deps.sh: all tests passed'
