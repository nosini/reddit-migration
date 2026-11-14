"""Command-line entry point for reddit_migration.

  reddit_migration --login        run the OAuth flow for both accounts, store in keyring
  reddit_migration                migrate saved items (account 1 -> account 2)
  reddit_migration --dry-run      show what would happen without changing anything
"""

from __future__ import annotations

import argparse
import os

from . import __version__


def _non_negative_float(value: str) -> float:
    try:
        number = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid number: {value!r}")
    if number < 0:
        raise argparse.ArgumentTypeError("must not be negative")
    return number


def _non_negative_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid integer: {value!r}")
    if number < 0:
        raise argparse.ArgumentTypeError("must not be negative")
    return number


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="reddit_migration",
        description="Migrate saved Reddit items between two accounts; tokens live in GNOME Keyring.",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument(
        "--login",
        action="store_true",
        help="Run the OAuth login flow for both accounts, store the tokens in GNOME Keyring, then exit.",
    )
    p.add_argument(
        "--write-config",
        action="store_true",
        help="Write a commented default config to the standard location, then exit.",
    )
    p.add_argument(
        "--update-config",
        action="store_true",
        help="Regenerate the config file, keeping existing values and adding "
        "any options introduced since it was written, then exit. "
        "(Custom comments are replaced by the template's.)",
    )
    p.add_argument("--config", default=None, help="Path to a config file (overrides the default location).")
    p.add_argument(
        "--port",
        type=int,
        default=None,
        help="OAuth redirect port for --login (must match your Reddit app's redirect URI). Prompts if omitted.",
    )
    p.add_argument(
        "--limit",
        type=_non_negative_int,
        default=0,
        help="Max saved items to process; 0 means no limit.",
    )
    p.add_argument(
        "--state-file",
        default=os.environ.get("MIGRATION_STATE_FILE") or None,
        help="JSON vault for external sources. Default: config [state].file, "
        "else ./migrated_sources.json if it exists, "
        "else ~/.config/reddit_migration/migrated_sources.json.",
    )
    p.add_argument("--sleep", type=_non_negative_float, default=None)
    p.add_argument("--dry-run", action="store_true", help="Do not save/unsave anything; only print actions.")
    p.add_argument(
        "--skip-comments",
        action="store_true",
        help="Skip saved comments; only migrate submissions.",
    )
    p.add_argument("--only", default="", help="Comma-separated subreddit whitelist (unions with config + built-in).")
    p.add_argument("--skip", default="", help="Comma-separated subreddit blacklist (unions with config + built-in).")
    p.add_argument("--source-domain", default="", help="Comma-separated source domains (unions with config domains).")
    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.write_config:
        from .config import write_default_config

        path = write_default_config(args.config)
        print(f"Wrote default config to {path}")
        return 0

    if args.update_config:
        from .config import update_config

        path = update_config(args.config)
        print(f"Updated config at {path}")
        return 0

    if args.login:
        from .login import run_login

        return run_login(args.port)

    if args.sleep is None:
        raw_sleep = os.environ.get("MIGRATION_SLEEP_SECS", "1.0")
        try:
            args.sleep = _non_negative_float(raw_sleep)
        except argparse.ArgumentTypeError as exc:
            parser.error(f"MIGRATION_SLEEP_SECS={raw_sleep!r}: {exc}")

    from .migrate import run_migrate

    return run_migrate(args)


if __name__ == "__main__":
    raise SystemExit(main())
