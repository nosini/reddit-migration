"""Configuration loading for reddit_migration.

Config lives at (first match wins):
  1. the path given to --config
  2. $REDDIT_MIGRATION_CONFIG
  3. $XDG_CONFIG_HOME/reddit_migration/config.toml
  4. ~/.config/reddit_migration/config.toml

The file is optional; without it the built-in defaults apply. CLI flags
(--only / --skip / --source-domain) union on top of whatever the config
resolves to.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Built-in source domains, used when the config doesn't specify any.
DEFAULT_SOURCE_DOMAINS = ["pixiv.net", "danbooru.donmai.us", "gelbooru.com"]

CONFIG_TEMPLATE = """\
# reddit_migration configuration
# Subreddit names are lowercase, without the "r/" prefix.

[subreddits]
# Whitelist: if non-empty, ONLY these subreddits are processed.
only = []

# Blacklist: these subreddits are always skipped.
# (If a subreddit is in both lists, it is skipped.)
skip = []

[sources]
# External source domains. A saved post/comment that links to one of these
# domains (or a subdomain of it) is recorded in the local JSON vault instead
# of being re-saved on account 2.
# Setting this key REPLACES the built-in defaults; omit it to keep them.
domains = ["pixiv.net", "danbooru.donmai.us", "gelbooru.com"]
"""


def config_path(explicit: Optional[str] = None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    env = os.environ.get("REDDIT_MIGRATION_CONFIG")
    if env:
        return Path(env).expanduser()
    base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(base) / "reddit_migration" / "config.toml"


@dataclass
class Config:
    only: set = field(default_factory=set)
    skip: set = field(default_factory=set)
    source_domains: set = field(default_factory=lambda: set(DEFAULT_SOURCE_DOMAINS))


def _as_set(value) -> set:
    if not value:
        return set()
    return {str(v).strip().lower() for v in value if str(v).strip()}


def _load_toml(path: Path) -> dict:
    try:
        import tomllib  # Python 3.11+
    except ModuleNotFoundError:  # Python 3.9 / 3.10
        import tomli as tomllib
    with path.open("rb") as f:
        return tomllib.load(f)


def load_config(explicit: Optional[str] = None) -> Config:
    path = config_path(explicit)
    cfg = Config()
    if not path.exists():
        return cfg

    data = _load_toml(path)

    subs = data.get("subreddits", {})
    cfg.only = _as_set(subs.get("only"))
    cfg.skip = _as_set(subs.get("skip"))

    sources = data.get("sources", {})
    domains = sources.get("domains")
    if domains is not None:  # present (even if empty) -> replace defaults
        cfg.source_domains = _as_set(domains)

    return cfg


def write_default_config(explicit: Optional[str] = None) -> Path:
    path = config_path(explicit)
    if path.exists():
        raise SystemExit(f"Config already exists, not overwriting: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(CONFIG_TEMPLATE, encoding="utf-8")
    return path
