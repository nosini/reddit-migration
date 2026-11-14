"""Configuration loading for reddit_migration.

Config lives at (first match wins):
  1. the path given to --config
  2. $REDDIT_MIGRATION_CONFIG
  3. $XDG_CONFIG_HOME/reddit_migration/config.toml
  4. ~/.config/reddit_migration/config.toml

Inside the Flatpak the host's config folder is used (see _config_home).

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

FLATPAK_INFO = Path("/.flatpak-info")

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
# Setting this key REPLACES the built-in defaults; leave it commented out to
# keep them (and pick up domains added in newer versions).
{domains}

[state]
# Where the external-source vault (the JSON file of migrated sources) is
# written. Empty means the default:
#   $XDG_CONFIG_HOME/reddit_migration/migrated_sources.json
# except that a migrated_sources.json in the current directory is used if it
# exists (compatibility with runs from before this option existed).
# Overridable per run with --state-file or $MIGRATION_STATE_FILE.
file = {state_file}
"""


def _config_home() -> Path:
    # Flatpak points XDG_CONFIG_HOME at the app's private folder and mounts the
    # host's reddit_migration folder both there and at its host path. Use the
    # host path, so the paths we print are ones the user can open on the host.
    if FLATPAK_INFO.exists():
        base = os.environ.get("HOST_XDG_CONFIG_HOME")
    else:
        base = os.environ.get("XDG_CONFIG_HOME")
    return Path(base) if base else Path.home() / ".config"


def config_path(explicit: Optional[str] = None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    env = os.environ.get("REDDIT_MIGRATION_CONFIG")
    if env:
        return Path(env).expanduser()
    return _config_home() / "reddit_migration" / "config.toml"


@dataclass
class Config:
    only: set = field(default_factory=set)
    skip: set = field(default_factory=set)
    source_domains: set = field(default_factory=lambda: set(DEFAULT_SOURCE_DOMAINS))
    skip_comments: bool = False
    state_file: str = ""
    # The folder of the config file, used to resolve a relative [state].file.
    _state_file_base: Optional[Path] = field(default=None, repr=False, compare=False)


def _toml_str_list(values) -> str:
    # json.dumps produces valid TOML basic strings (same escaping rules).
    return "[" + ", ".join(json.dumps(v) for v in sorted(values)) + "]"


def render_config(cfg: Config) -> str:
    domains = _toml_str_list(cfg.source_domains)
    if cfg.source_domains == set(DEFAULT_SOURCE_DOMAINS):
        # Keep the key commented out so a later release can extend the defaults.
        domains = "# domains = " + domains
    else:
        domains = "domains = " + domains
    return CONFIG_TEMPLATE_FMT.format(
        only=_toml_str_list(cfg.only),
        skip=_toml_str_list(cfg.skip),
        skip_comments="true" if cfg.skip_comments else "false",
        domains=domains,
        state_file=json.dumps(cfg.state_file),
    )


def _as_set(value) -> set:
    if not value:
        return set()
    return {str(v).strip().lower() for v in value if str(v).strip()}


def _error(path: Path, key: str, message: str) -> SystemExit:
    return SystemExit(f"Invalid config {path}: {key} {message}")


def _table(data: dict, section: str, path: Path) -> dict:
    value = data.get(section)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise _error(path, section, "must be a table")
    return value


def _reject_unknown(data: dict, section: Optional[str], allowed: set, path: Path) -> None:
    for key in sorted(set(data) - allowed):
        name = f"{section}.{key}" if section else key
        raise _error(path, name, "is not a known option")


def _string_list(value, path: Path, key: str) -> Optional[list]:
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise _error(path, key, "must be a list of strings")
    return value


def _boolean(value, path: Path, key: str) -> bool:
    if value is None:
        return False
    if not isinstance(value, bool):
        raise _error(path, key, "must be true or false")
    return value


def _string(value, path: Path, key: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise _error(path, key, "must be a string")
    return value


def _load_toml(path: Path) -> dict:
    try:
        import tomllib  # Python 3.11+
    except ModuleNotFoundError:  # Python 3.9 / 3.10
        import tomli as tomllib
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise SystemExit(f"Could not read config {path}: {exc}")


def load_config(explicit: Optional[str] = None) -> Config:
    path = config_path(explicit)
    cfg = Config()
    if not path.exists():
        if explicit or os.environ.get("REDDIT_MIGRATION_CONFIG"):
            raise SystemExit(f"Config file not found: {path}")
        return cfg

    data = _load_toml(path)
    _reject_unknown(data, None, {"subreddits", "items", "sources", "state"}, path)

    subs = _table(data, "subreddits", path)
    _reject_unknown(subs, "subreddits", {"only", "skip"}, path)
    cfg.only = _as_set(_string_list(subs.get("only"), path, "subreddits.only"))
    cfg.skip = _as_set(_string_list(subs.get("skip"), path, "subreddits.skip"))

    items = _table(data, "items", path)
    _reject_unknown(items, "items", {"skip_comments"}, path)
    cfg.skip_comments = _boolean(items.get("skip_comments"), path, "items.skip_comments")

    sources = _table(data, "sources", path)
    _reject_unknown(sources, "sources", {"domains"}, path)
    if "domains" in sources:  # present (even if empty) -> replace defaults
        cfg.source_domains = _as_set(_string_list(sources["domains"], path, "sources.domains"))

    state = _table(data, "state", path)
    _reject_unknown(state, "state", {"file"}, path)
    cfg.state_file = _string(state.get("file"), path, "state.file")
    cfg._state_file_base = path.parent

    return cfg


def resolve_state_path(cfg: Config) -> Path:
    """Default location of the external-source vault (when --state-file and
    $MIGRATION_STATE_FILE are unset): the config's [state].file if given,
    else a legacy migrated_sources.json in the current directory if one
    exists, else $XDG_CONFIG_HOME/reddit_migration/migrated_sources.json."""
    if cfg.state_file:
        path = Path(cfg.state_file).expanduser()
        if not path.is_absolute() and cfg._state_file_base is not None:
            path = cfg._state_file_base / path
        return path
    legacy = Path(DEFAULT_STATE_FILENAME)
    if legacy.exists():
        return legacy
    return _config_home() / "reddit_migration" / DEFAULT_STATE_FILENAME


def _write_config(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def write_default_config(explicit: Optional[str] = None) -> Path:
    path = config_path(explicit)
    if path.exists():
        raise SystemExit(f"Config already exists, not overwriting: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_config(path, render_config(Config()))
    return path


def update_config(explicit: Optional[str] = None) -> Path:
    """Regenerate the config file from the current template, keeping the
    values of an existing config and adding any options introduced since it
    was written. Custom comments in the file are not preserved (the template's
    comments replace them). Creates the file if it doesn't exist."""
    path = config_path(explicit)
    cfg = load_config(explicit) if path.exists() else Config()
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_config(path, render_config(cfg))
    return path
