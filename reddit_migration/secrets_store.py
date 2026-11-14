"""GNOME Keyring (Secret Service) helpers.

Secrets are stored with attributes application=reddit-migrator and key=<VAR>,
so they can be looked up deterministically and show up sensibly in Seahorse.
"""

from __future__ import annotations

import os
import sys

KEYRING_APP = "reddit-migrator"

# The four values the tool moves in and out of the keyring.
SECRET_KEYS = (
    "REDDIT_CLIENT_ID",
    "REDDIT_USER_AGENT",
    "REDDIT_ACCOUNT1_REFRESH_TOKEN",
    "REDDIT_ACCOUNT2_REFRESH_TOKEN",
)


def _collection():
    import secretstorage

    conn = secretstorage.dbus_init()
    collection = secretstorage.get_default_collection(conn)
    if collection.is_locked():
        # unlock() returns True when the prompt was dismissed, False on success.
        if collection.unlock():
            raise RuntimeError("the keyring is locked and the unlock prompt was dismissed")
    return collection


def keyring_available() -> bool:
    """True if the default keyring can be reached and is unlocked."""
    try:
        collection = _collection()
    except Exception:
        return False
    return not collection.is_locked()


def keyring_get(key: str) -> str | None:
    """Return a stored value by its `key` attribute, or None if unavailable."""
    try:
        collection = _collection()
    except Exception:
        return None
    for item in collection.search_items({"application": KEYRING_APP, "key": key}):
        return item.get_secret().decode()
    return None


def keyring_store(key: str, value: str, label: str) -> None:
    """Store (or replace) a value under application=reddit-migrator, key=<key>."""
    collection = _collection()
    collection.create_item(
        label,
        {"application": KEYRING_APP, "key": key},
        value.encode(),
        replace=True,
    )


def load_secrets_into_env(app: str = KEYRING_APP) -> None:
    """Populate REDDIT_* env vars from the keyring if not already set.

    Only the known REDDIT_* keys are read, and a non-empty environment
    variable always wins. Silently
    no-ops if secretstorage is missing or the keyring can't be reached, so
    plain env vars still work as a fallback.
    """
    try:
        collection = _collection()
        for item in collection.search_items({"application": app}):
            key = item.get_attributes().get("key")
            if key in SECRET_KEYS and not os.environ.get(key):
                os.environ[key] = item.get_secret().decode()
    except ImportError:
        return
    except Exception as exc:
        print(f"[warn] keyring load skipped: {exc}", file=sys.stderr)
