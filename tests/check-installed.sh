# shellcheck shell=sh
# Runs inside the installed app's sandbox (see scripts/test-installed.sh).
# There is no display, keyring or session bus in CI, so keep these checks
# headless: start the command-line interface, import modules, look for files.
set -eu

test -x /app/bin/reddit_migration
test -x /app/bin/reddit_migration-terminal

# -P keeps a checkout in the working directory from shadowing the installed
# package.
python3 -P - <<'PYTHON'
import os
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET

import praw
import secretstorage

import reddit_migration
from reddit_migration.config import config_path

assert reddit_migration.__file__.startswith("/app/"), reddit_migration.__file__

# The version the app reports must be the newest release in the metainfo.
app_id = os.environ["FLATPAK_ID"]
metainfo = ET.parse(f"/app/share/metainfo/{app_id}.metainfo.xml")
release = metainfo.find("releases/release").get("version")
version = subprocess.run(
    ["reddit_migration", "--version"], check=True, capture_output=True, text=True
).stdout.strip()
assert version == f"reddit_migration {release}", (version, release)

# webbrowser falls back to xdg-open, which forwards to the OpenURI portal.
assert os.environ.get("BROWSER") == "xdg-open"
assert shutil.which("xdg-open"), "xdg-open is missing from the runtime"

# The host's config folder is mounted under the app's XDG_CONFIG_HOME, so the
# default paths resolve to the files a pipx install uses.
host_config = Path(os.environ.get("HOST_XDG_CONFIG_HOME") or Path.home() / ".config")
app_folder = config_path().parent
assert app_folder.is_dir(), app_folder
assert app_folder.samefile(host_config / "reddit_migration"), app_folder
PYTHON

# flatpak-builder records the license files it finds at the root of each
# module's source; the app's must be there.
test -n "$(ls "/app/share/licenses/$FLATPAK_ID/reddit-migration")"

echo 'Installed app checks passed.'
