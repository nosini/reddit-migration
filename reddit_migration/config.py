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

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Built-in source domains, used when the config doesn't specify any.
DEFAULT_SOURCE_DOMAINS = ["pixiv.net", "danbooru.donmai.us", "gelbooru.com"]

DEFAULT_STATE_FILENAME = "migrated_sources.json"

# The commented config template. The {placeholders} are filled by
# render_config, so --update-config can re-render it with the values from an
# existing config while picking up sections added in newer versions.
CONFIG_TEMPLATE_FMT = """\
# reddit_migration configuration
# Subreddit names are lowercase, without the "r/" prefix.

[subreddits]
# Whitelist: if non-empty, ONLY these subreddits are processed.
only = {only}

# Blacklist: these subreddits are always skipped.
# (If a subreddit is in both lists, it is skipped.)
skip = {skip}

[items]
# Skip saved comments entirely; only submissions are migrated.
# (The --skip-comments flag turns this on regardless of the config.)
skip_comments = {skip_comments}

[sources]
# External source domains. A saved post/comment that links to one of these
# domains (or a subdomain of it) is recorded in the local JSON vault instead
# of being re-saved on account 2.
# Setting this key REPLACES the built-in defaults; omit it to keep them.
domains = {domains}

[state]
# Where the external-source vault (the JSON file of migrated sources) is
# written. Empty means the default:
#   $XDG_CONFIG_HOME/reddit_migration/migrated_sources.json
# except that a migrated_sources.json in the current directory is used if it
# exists (compatibility with runs from before this option existed).
# Overridable per run with --state-file or $MIGRATION_STATE_FILE.
file = {state_file}
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
    skip_comments: bool = False
    state_file: str = ""


def _toml_str_list(values) -> str:
    # json.dumps produces valid TOML basic strings (same escaping rules).
    return "[" + ", ".join(json.dumps(v) for v in sorted(values)) + "]"


def render_config(cfg: Config) -> str:
    return CONFIG_TEMPLATE_FMT.format(
        only=_toml_str_list(cfg.only),
        skip=_toml_str_list(cfg.skip),
        skip_comments="true" if cfg.skip_comments else "false",
        domains=_toml_str_list(cfg.source_domains),
        state_file=json.dumps(cfg.state_file),
    )


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

    items = data.get("items", {})
    cfg.skip_comments = bool(items.get("skip_comments", False))

    sources = data.get("sources", {})
    domains = sources.get("domains")
    if domains is not None:  # present (even if empty) -> replace defaults
        cfg.source_domains = _as_set(domains)

    state = data.get("state", {})
    cfg.state_file = str(state.get("file", "") or "")

    return cfg


def resolve_state_path(cfg: Config) -> Path:
    """Default location of the external-source vault (when --state-file and
    $MIGRATION_STATE_FILE are unset): the config's [state].file if given,
    else a legacy migrated_sources.json in the current directory if one
    exists, else $XDG_CONFIG_HOME/reddit_migration/migrated_sources.json."""
    if cfg.state_file:
        return Path(cfg.state_file).expanduser()
    legacy = Path(DEFAULT_STATE_FILENAME)
    if legacy.exists():
        return legacy
    base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(base) / "reddit_migration" / DEFAULT_STATE_FILENAME


def write_default_config(explicit: Optional[str] = None) -> Path:
    path = config_path(explicit)
    if path.exists():
        raise SystemExit(f"Config already exists, not overwriting: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_config(Config()), encoding="utf-8")
    return path


def update_config(explicit: Optional[str] = None) -> Path:
    """Regenerate the config file from the current template, keeping the
    values of an existing config and adding any options introduced since it
    was written. Custom comments in the file are not preserved (the template's
    comments replace them). Creates the file if it doesn't exist."""
    path = config_path(explicit)
    cfg = load_config(explicit)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_config(cfg), encoding="utf-8")
    return path
