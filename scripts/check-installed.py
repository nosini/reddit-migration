#!/usr/bin/env python3
"""Headless checks run inside the installed app's Platform runtime."""

import os
from pathlib import Path
import shutil

import praw
import secretstorage

import reddit_migration
from reddit_migration.config import config_path

assert reddit_migration.__file__.startswith("/app/"), reddit_migration.__file__

for name in ("reddit_migration", "reddit_migration-terminal"):
    launcher = Path("/app/bin", name)
    assert launcher.is_file() and os.access(launcher, os.X_OK), launcher

# webbrowser falls back to xdg-open, which forwards to the OpenURI portal.
assert os.environ.get("BROWSER") == "xdg-open"
assert shutil.which("xdg-open"), "xdg-open is missing from the runtime"

# The host's config folder is mounted under the app's XDG_CONFIG_HOME, so the
# default paths resolve to the files a pipx install uses.
host_config = Path(os.environ.get("HOST_XDG_CONFIG_HOME") or Path.home() / ".config")
app_folder = config_path().parent
assert app_folder.is_dir(), app_folder
assert app_folder.samefile(host_config / "reddit_migration"), app_folder

for relative in (
    "share/icons/hicolor/scalable/apps/eu.nosini.RedditMigration.svg",
    "share/applications/eu.nosini.RedditMigration.desktop",
    "share/metainfo/eu.nosini.RedditMigration.metainfo.xml",
):
    path = Path("/app", relative)
    assert path.is_file() and path.stat().st_size > 0, path

print("Installed app: imports, launchers, config folder and packaged files passed.")
