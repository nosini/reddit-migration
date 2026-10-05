# Development

## Layout

- `reddit_migration/`: the app, a setuptools project described by
  `pyproject.toml`.
- `tests/`: unit tests, run with `python3 -m unittest discover -s tests` in an
  environment with the app's dependencies installed.
- `eu.nosini.RedditMigration.yml`: the Flatpak manifest. It builds the app
  from this checkout.
- `eu.nosini.RedditMigration.metainfo.xml`, `.desktop` and `.svg`:
  software-center metadata, launcher and icon.
- `python3-requirements.json`: pinned Python dependencies, generated from
  `pyproject.toml` by `scripts/generate-python-deps.sh`.
- `launcher/reddit_migration-terminal`: wrapper used by the application menu
  entry, which keeps the terminal open after the run.
- `lint-exceptions.json`: linter errors that don't apply to a self-hosted
  repository, each with its reason.
- `tests/check-installed.sh`: checks that run inside the installed app.
- `scripts/test-installed.sh`: installs a local build and runs those checks
  and the unit tests.
- `scripts/prepare-repository.sh`: signs tested builds for publishing.
- `scripts/builder-tools.sh`: fetches the pinned
  [flatpak-builder-tools](https://github.com/flatpak/flatpak-builder-tools).
- `docs/screenshots/`: the screenshot shown in software centers.

## Installing from a checkout

With pipx:

```sh
pipx install .
```

## Building the Flatpak

The simplest way to build is with `org.flatpak.Builder` from Flathub. It
contains flatpak-builder and the linter in the versions Flathub uses:

```sh
flatpak install --user flathub org.flatpak.Builder
flatpak run org.flatpak.Builder --user --install --install-deps-from=flathub \
  --default-branch=stable --force-clean --repo=repo build-dir eu.nosini.RedditMigration.yml
```

The build downloads the pinned Python packages, so it needs a network
connection. pip installs them without contacting PyPI.

Building from a checkout installs the app from a local remote named
`eu.nosini.RedditMigration-origin`. Once the build directories are gone,
`flatpak update` warns that it can't reach it. Switch to the published
remote as the README describes, or disable it with
`flatpak remote-modify --user --disable eu.nosini.RedditMigration-origin`.

To get a single-file bundle instead of installing:

```sh
flatpak build-bundle --runtime-repo=https://dl.flathub.org/repo/flathub.flatpakrepo \
  repo reddit-migration.flatpak eu.nosini.RedditMigration stable
```

## Checking

CI runs the same linter checks as Flathub. Run them locally with:

```sh
alias lint='flatpak run --command=flatpak-builder-lint org.flatpak.Builder'
lint --exceptions --user-exceptions lint-exceptions.json manifest eu.nosini.RedditMigration.yml
lint appstream eu.nosini.RedditMigration.metainfo.xml
lint --exceptions --user-exceptions lint-exceptions.json repo repo
```

Only add an exception when the rule doesn't apply to a package published
outside Flathub, and say why in `lint-exceptions.json`.

To run the checks inside the installed app, build without `--install` (but
with `--repo=repo`), then run:

```sh
bash scripts/test-installed.sh
```

The script adds a `local-test` remote for `repo/`, installs the app from
it and runs `tests/check-installed.sh` with `flatpak run`, so the checks see
the Platform runtime the app runs with, not the SDK. The checks compare
`--version` with the newest metainfo release, import the app and its
dependencies, and look for the launchers and the shared config folder. Then
the unit tests run against the installed package. No display or keyring is
needed. The script refuses to replace an existing installation. Afterwards,
remove the test installation with
`flatpak --user uninstall eu.nosini.RedditMigration` and the remote with
`flatpak --user remote-delete local-test`.

## GitHub Actions

`.github/workflows/flatpak.yml` runs for pushes to `main`, pull requests and
manual runs. For each architecture, it lints the manifest and metainfo,
builds with [flatpak-github-actions](https://github.com/flatpak/flatpak-github-actions),
lints the exported build, runs the installed-app checks and the unit tests,
and uploads an installable bundle as an artifact. Install a downloaded
artifact with `flatpak install --user reddit-migration-x86_64.flatpak`.
Bundles are unsigned and don't update; the published repository does.

CI builds for x86_64 and aarch64, like Flathub. The aarch64 build uses
GitHub's Arm runners, which are free for public repositories only.

### Publishing

On `main`, when the repository variable `PUBLISH_FLATPAK` is `true`, the
workflow also publishes a signed Flatpak repository to GitHub Pages. A
separate job, which never runs the build, combines the tested builds of all
architectures, signs the app ref, generates and signs the software catalog
and summary, and writes `reddit-migration.flatpakrepo` and
`reddit-migration.flatpakref` with the public key embedded. Before deploying,
a fresh remote that only knows the public key must accept the result.

The catalog refs are deleted before signing because `flatpak
build-update-repo` reuses unchanged catalog commits, including the unsigned
ones from the test repositories, without signing them.

Each deployment contains only the latest build. The repository URL defaults
to `https://OWNER.github.io/REPOSITORY/`. For a custom domain, set the
`FLATPAK_REPO_URL` variable to the real URL, including the trailing slash.

To set publishing up:

1. In **Settings → Pages**, select **GitHub Actions** as the source.
2. Store the signing key as the secret `FLATPAK_GPG_PRIVATE_KEY` (see
   below).
3. Set the variable:
   `gh variable set PUBLISH_FLATPAK --body true --repo nosini/reddit-migration`.
4. Run the workflow on `main`, or push to it.

### Signing key

The key has to be an ASCII-armored GnuPG private key without a passphrase.
An existing Flatpak signing key can be reused. To make a new one, generate
it on your own machine, outside the source checkout, in a separate GnuPG
directory:

```sh
mkdir -p -m 700 "$HOME/.gnupg-flatpak/private-keys-v1.d"
gpgconf --homedir "$HOME/.gnupg-flatpak" --create-socketdir
gpg --homedir "$HOME/.gnupg-flatpak" --batch --pinentry-mode loopback \
  --passphrase '' --quick-generate-key 'Nosini Flatpak signing' ed25519 sign 0
```

Upload it through a private temporary file, so a failed export can't upload
an empty secret:

```sh
(
  set -eu
  umask 077
  key_file=$(mktemp "$HOME/.gnupg-flatpak/export.XXXXXX")
  trap 'rm -f "$key_file"' EXIT
  gpg --homedir "$HOME/.gnupg-flatpak" --armor \
    --export-secret-keys 'Nosini Flatpak signing' > "$key_file"
  test -s "$key_file"
  gh secret set FLATPAK_GPG_PRIVATE_KEY --repo nosini/reddit-migration < "$key_file"
)
```

Keep a backup of the key. Installed copies trust the public key from the
`.flatpakref` they were installed with, so replacing the key breaks their
updates.

### Shared remote

[flatpak-repo](https://github.com/nosini/flatpak-repo) collects the
published package into the shared `nosini` remote, from the entry for this
app in its `apps.json`. The app exports no extensions.

## How the package works

The app uses the Freedesktop 26.08 runtime, which provides Python 3.14, pip
and setuptools. The dependencies come from PyPI; cryptography and cffi as
prebuilt wheels for each architecture, so they aren't built from source. The
app itself is installed from the checkout with
`pip install --no-build-isolation`, using the runtime's setuptools. Every
pull request therefore builds and tests its own code.

The sandbox has these permissions:

- network access, for the Reddit API and the OAuth redirect listener on
  localhost during `--login`;
- the Secret Service (`org.freedesktop.secrets`). The app uses it directly
  rather than the Secret portal, so the tokens stay shared with a pipx
  install and visible in Seahorse;
- `~/.config/reddit_migration`. Flatpak mounts the host folder both at its
  own path and under the app's private `XDG_CONFIG_HOME`
  (`~/.var/app/eu.nosini.RedditMigration/config`), where the app looks for it.
  The default paths therefore reach the host's files without changing
  `XDG_CONFIG_HOME`. The linter reports this grant as unnecessary; it is an
  exception in `lint-exceptions.json`.

Python's `webbrowser` only tries `xdg-open` when a display socket is
available, and the app has none. `BROWSER=xdg-open` makes `--login` call it
anyway; the runtime's `xdg-open` forwards the URL to the OpenURI portal, which
opens the host browser.

GNOME Software hides AppStream `console-application` components from its
lists, so the metadata describes a desktop application with the terminal
launcher as its `launchable`, and a screenshot of the terminal.

The only native code comes from the prebuilt wheels, so the manifest sets
`no-debuginfo` and no `.Debug` extension is exported.

## Python dependencies

After changing the dependencies in `pyproject.toml`, regenerate the module:

```sh
bash scripts/generate-python-deps.sh
```

The script runs flatpak-pip-generator from flatpak-builder-tools with pip
inside the manifest's SDK, so dependency markers match the runtime's Python.
It needs `flatpak run` and the SDK (`flatpak install --user flathub
org.freedesktop.Sdk//26.08`). It prefers pure-Python wheels and otherwise
source archives, except for cryptography and cffi, which need a Rust or C
toolchain to build and use prebuilt wheels for x86_64 and aarch64. The
generator doesn't evaluate `python_version` markers, so the script leaves
out tomli, which is only needed before Python 3.11. The generator also
expects the SDK to have the `packaging` module for reading wheel tags; the
Freedesktop SDK only has pip's copy, so the script runs a copy of the
generator that imports that one.

## Releases

Bump `version` in `pyproject.toml` and `__version__` in
`reddit_migration/__init__.py`, and add a `<release>` entry to the metainfo
file, newest first. The installed-app checks fail when the version the app
reports isn't the newest release in the metainfo.

## Moving to a newer runtime

Change `runtime-version` in the manifest and the image tag in
`.github/workflows/flatpak.yml`. If the new runtime has a different Python
version, regenerate the Python dependencies.
