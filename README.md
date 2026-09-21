# reddit_migration

Migrate saved Reddit items from one account to another. OAuth refresh tokens
(and the client id / user agent) are stored in **GNOME Keyring** — visible in
Seahorse — so nothing sensitive lives in shell history or dotfiles.

## Install (pipx)

```bash
pipx install .
```

(or point pipx at the folder: `pipx install /path/to/reddit_migration_project`)

SecretStorage pulls in `jeepney` + `cryptography`, both pure-wheel installs, so
it works inside the isolated pipx venv without system dbus-python.

## One-time Reddit setup

Create an app at <https://www.reddit.com/prefs/apps>:

- type: **installed app**
- redirect uri: `http://localhost:8080` (or any port — the login flow lets you
  pick one, it just has to match what you register here)

Note the **client_id** shown under the app name.

## Usage

```bash
reddit_migration --login     # browser OAuth for both accounts -> keyring
reddit_migration             # run the migration
reddit_migration --dry-run   # preview without saving/unsaving anything
reddit_migration --version   # show the installed version
```

Migration continues after individual item failures and reports migrated, skipped,
and failed counts. The command exits with status 1 if any item fails (including
during a dry run), or 0 when all items succeed or are skipped.

`--login` prompts for the client_id and user agent (only the first time — after
that they come from the keyring), and for the OAuth **redirect port** (default
8080; pass `--port` to skip the prompt). The port only has to match your Reddit
app's redirect URI — the migrator itself doesn't use it. Because Reddit keeps
one account logged in per browser session, authorize account 1 in your normal
window and account 2 in a private/incognito window.

## Configuration

The subreddit whitelist/blacklist **and** the external source domains live in a
TOML config file. Generate a commented starter:

```bash
reddit_migration --write-config
```

It's written to `$XDG_CONFIG_HOME/reddit_migration/config.toml` (usually
`~/.config/reddit_migration/config.toml`). Override the location with `--config PATH`
or `$REDDIT_MIGRATION_CONFIG`.
An explicitly selected config file must exist; a missing file stops migration.
Without an explicit path, a missing default config uses the built-in defaults.

```toml
[subreddits]
only = ["pics", "art"]        # if non-empty, ONLY these are processed
skip = ["announcements"]      # always skipped (wins over `only`)

[items]
skip_comments = false         # true: skip saved comments, migrate only submissions

[sources]
domains = ["pixiv.net", "danbooru.donmai.us", "gelbooru.com"]

[state]
file = ""                     # external-source vault location; "" = default (see below)
```

After upgrading, `reddit_migration --update-config` regenerates the config
with the latest template — existing values are kept, options added since the
file was written appear with their defaults. (Custom comments in the file are
replaced by the template's.)

The external-source vault (`migrated_sources.json`) is written to, in order
of precedence: `--state-file`, `$MIGRATION_STATE_FILE`, the config's
`[state].file`, a `migrated_sources.json` in the current directory if one
already exists (compatibility with older runs), else
`~/.config/reddit_migration/migrated_sources.json`.

**Where the domains are set:** the `[sources].domains` key above (or the
`--source-domain` flag). Matching is subdomain-aware, so `pixiv.net` also
matches `www.pixiv.net`. Setting the key **replaces** the built-in defaults;
omit the key to keep them.

Precedence for all three lists: built-in defaults, then the config file, then
CLI flags — each layer unions on top (except config `domains`, which replaces
the defaults as noted). The flags are for one-off runs; the config file is the
durable place to set things.

### Options

| flag | meaning |
|------|---------|
| `--login` | run the OAuth flow and store tokens, then exit |
| `--write-config` | write a commented default config file, then exit |
| `--update-config` | regenerate the config, keeping values and adding new options, then exit |
| `--config PATH` | use a specific config file instead of the default location |
| `--port N` | OAuth redirect port for `--login` (prompts if omitted) |
| `--limit N` | process at most N saved items (0 = no limit) |
| `--state-file PATH` | JSON vault for external sources (default: see precedence above) |
| `--sleep SECS` | delay between API calls (default 1.0) |
| `--dry-run` | print actions without changing anything |
| `--skip-comments` | skip saved comments; only migrate submissions |
| `--only a,b` | subreddit whitelist (unions with config + built-in) |
| `--skip a,b` | subreddit blacklist (unions with config + built-in) |
| `--source-domain a,b` | source domains (unions with config domains) |

Environment variables still override the keyring if set:
`REDDIT_CLIENT_ID`, `REDDIT_USER_AGENT`, `REDDIT_ACCOUNT1_REFRESH_TOKEN`,
`REDDIT_ACCOUNT2_REFRESH_TOKEN`.

## License

[AGPL-3.0-or-later](LICENSE).
