#!/usr/bin/env bash
# Refuse to publish a build whose source commit is no longer main.
set -euo pipefail

expected=${1:?Usage: check-main.sh EXPECTED_COMMIT}
current=$(git ls-remote --exit-code origin refs/heads/main | cut -f1)
if [[ "$current" != "$expected" ]]; then
  echo 'main changed during this run; retry on the latest main before publishing.' >&2
  exit 1
fi
