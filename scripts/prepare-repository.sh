#!/usr/bin/env bash
# Sign a tested build and generate the files used to install/update it.
set -euo pipefail

: "${GNUPGHOME:?}"
: "${GPG_KEY:?}"
: "${REPO_URL:?}"
: "${GITHUB_REPOSITORY:?}"

cp -a repo signed-repo
flatpak build-sign --gpg-sign="$GPG_KEY" --gpg-homedir="$GNUPGHOME" \
  signed-repo eu.nosini.RedditMigration stable
# Flatpak skips catalog commits whose content hasn't changed, including their
# signatures. The test repo's catalogs are unsigned, so regenerate them here.
ostree --repo=signed-repo refs --delete appstream
ostree --repo=signed-repo refs --delete appstream2
flatpak build-update-repo --gpg-sign="$GPG_KEY" --gpg-homedir="$GNUPGHOME" \
  --title="Reddit Migration" --default-branch=stable signed-repo

PUBLIC_KEY=$(gpg --batch --export --export-options export-minimal "$GPG_KEY" | base64 -w0)
test -n "$PUBLIC_KEY"

cat > signed-repo/reddit-migration.flatpakrepo <<REPO
[Flatpak Repo]
Title=Reddit Migration
Url=$REPO_URL
Homepage=https://github.com/$GITHUB_REPOSITORY
GPGKey=$PUBLIC_KEY
REPO
cat > signed-repo/reddit-migration.flatpakref <<REF
[Flatpak Ref]
Name=eu.nosini.RedditMigration
Branch=stable
Title=Reddit Migration
Url=$REPO_URL
RuntimeRepo=https://dl.flathub.org/repo/flathub.flatpakrepo
IsRuntime=false
SuggestRemoteName=reddit-migration
GPGKey=$PUBLIC_KEY
REF

# OSTree scratch files must not be published by Pages.
rm -rf signed-repo/tmp
