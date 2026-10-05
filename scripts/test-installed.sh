#!/usr/bin/env bash
# Run from the repository root after exporting a build to repo/.
set -euo pipefail

url=$(flatpak --user remotes --columns=name,url | awk '$1 == "local-test" { print $2 }')
if [[ "$url" != "file://$PWD/repo" ]]; then
  echo 'Add local-test pointing to this build before running the checks:' >&2
  echo "  flatpak --user remote-add --no-gpg-verify local-test \"\$PWD/repo\"" >&2
  exit 1
fi

# Avoid replacing an existing user installation when running locally.
ref=app/eu.nosini.RedditMigration/x86_64/stable
if flatpak info --user "$ref" >/dev/null 2>&1; then
  echo "These checks need a fresh installation; $ref is already installed." >&2
  exit 1
fi

test -s build-dir/export/share/icons/hicolor/scalable/apps/eu.nosini.RedditMigration.svg
test -s build-dir/export/share/applications/eu.nosini.RedditMigration.desktop

flatpak build-update-repo repo
flatpak --user install --noninteractive --no-related local-test "$ref"
version=$(flatpak run --user --arch=x86_64 --branch=stable eu.nosini.RedditMigration --version)
expected=$(python3 -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])')
if [[ "$version" != "reddit_migration $expected" ]]; then
  echo "Unexpected version output: $version (expected $expected)" >&2
  exit 1
fi
# -P keeps a checkout in the working directory from shadowing the installed package.
flatpak run --user --arch=x86_64 --branch=stable \
  --command=python3 eu.nosini.RedditMigration -P - < scripts/check-installed.py
# The unit tests, against the installed package and the pinned dependencies.
flatpak run --user --arch=x86_64 --branch=stable --filesystem="$PWD/tests:ro" \
  --command=python3 eu.nosini.RedditMigration -P -m unittest discover -s "$PWD/tests"
