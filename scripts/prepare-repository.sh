#!/usr/bin/env bash
# Combine tested per-architecture repos into signed-repo/, sign every app and
# extension ref, and write the files used to install the package and receive
# updates. Usage: prepare-repository.sh REPO...
set -euo pipefail

: "${GNUPGHOME:?}"
: "${GPG_KEY:?}"
: "${REPO_URL:?}"
: "${HOMEPAGE:?}"
: "${APP_ID:?}"
: "${APP_NAME:?}"
: "${REMOTE_NAME:?}"
: "${FLATPAK_BRANCH:=stable}"
if (( $# == 0 )); then
  echo "Usage: $0 REPO..." >&2
  exit 2
fi
if [[ -e signed-repo ]]; then
  echo 'signed-repo already exists; remove it first.' >&2
  exit 1
fi
sign=(--gpg-sign="$GPG_KEY" --gpg-homedir="$GNUPGHOME")

ostree --repo=signed-repo init --mode=archive-z2
for input in "$@"; do
  ostree --repo=signed-repo pull-local "$input"
done

# Sign every app and extension ref, including the Locale and Debug extensions
# flatpak-builder exports automatically, not just the app.
while IFS=/ read -r kind id arch branch; do
  if [[ "$kind" == runtime ]]; then
    flatpak build-sign --runtime --arch="$arch" "${sign[@]}" signed-repo "$id" "$branch"
  else
    flatpak build-sign --arch="$arch" "${sign[@]}" signed-repo "$id" "$branch"
  fi
done < <(ostree --repo=signed-repo refs | grep -E '^(app|runtime)/')

# build-update-repo reuses unchanged catalog commits without signing them, and
# the test repos' catalogs are unsigned, so have them generated again.
ostree --repo=signed-repo refs --delete appstream
ostree --repo=signed-repo refs --delete appstream2
flatpak build-update-repo "${sign[@]}" --prune \
  --title="$APP_NAME" --default-branch="$FLATPAK_BRANCH" signed-repo

public_key=$(gpg --batch --export --export-options export-minimal "$GPG_KEY" | base64 -w0)
test -n "$public_key"

cat > "signed-repo/$REMOTE_NAME.flatpakrepo" <<REPO
[Flatpak Repo]
Title=$APP_NAME
Url=$REPO_URL
Homepage=$HOMEPAGE
GPGKey=$public_key
REPO
cat > "signed-repo/$REMOTE_NAME.flatpakref" <<REF
[Flatpak Ref]
Name=$APP_ID
Branch=$FLATPAK_BRANCH
Title=$APP_NAME
Url=$REPO_URL
Homepage=$HOMEPAGE
RuntimeRepo=https://dl.flathub.org/repo/flathub.flatpakrepo
IsRuntime=false
SuggestRemoteName=$REMOTE_NAME
GPGKey=$public_key
REF

# OSTree scratch files must not be published.
rm -rf signed-repo/tmp
