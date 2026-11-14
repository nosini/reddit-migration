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
- `scripts/tests/`: tests for these scripts.
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

## Debugging

A shell in the sandbox of the last build, without installing it:

```sh
flatpak run org.flatpak.Builder --run build-dir eu.nosini.RedditMigration.yml sh
```

A shell in the installed app's sandbox, with the SDK and its debugging tools
in place of the Platform runtime (the SDK must be installed):

```sh
flatpak run --devel --command=sh eu.nosini.RedditMigration
```

To see which D-Bus names the app tries to reach, and so which `--talk-name`
permissions it needs:

```sh
flatpak run --log-session-bus eu.nosini.RedditMigration 2>&1 | grep '(required 1)'
```

## GitHub Actions

`.github/workflows/flatpak.yml` runs when a `v*` version tag is pushed,
for pull requests and on manual runs. Release builds check out the tagged
commit. Pushes to `main` run the lightweight checks and the app's unit tests
without building the Flatpak. For each architecture, the packaging workflow
lints the manifest and metainfo, builds with
[flatpak-github-actions](https://github.com/flatpak/flatpak-github-actions),
lints the exported build, runs the installed-app checks and the unit tests,
and uploads an installable bundle as an artifact. Install a downloaded
artifact with `flatpak install --user reddit-migration-x86_64.flatpak`.
Bundles are unsigned and don't update; the published repository does.

CI builds for x86_64 and aarch64, like Flathub. The aarch64 build uses
GitHub's Arm runners, which are free for public repositories only.

`.github/workflows/checks.yml` lints the scripts (including the menu
launcher) and workflows, checks that the manifest and metadata files parse,
and runs the tests in `scripts/tests/`, including release tag classification
and release creation with a fake GitHub CLI. The publishing test makes small
fake builds and publishes them several times to a local web server.

### Build cache

CI restores `.flatpak-builder`, so the downloaded sources and the generated
Python dependency modules are reused. Flatpak checks their inputs and rebuilds
a module when its sources, dependencies or the SDK change. The app module is
a `type: dir` source, which flatpak-builder never caches, so it and the
modules after it are always built, as are the lint, installed-app checks and
unit tests.

The key covers this workflow and `python3-requirements.json`, so changing
either starts a new snapshot; otherwise the newest earlier snapshot is
restored. The container image is pinned by digest, so a new image means a
workflow change and a new key. Downloads are carried over and not pruned when a
dependency is dropped, so a snapshot grows slowly. To start over, bump
`CACHE_PREFIX` in the workflow; the key and the restore prefix both use it,
so they can't drift apart. Cache misses build normally.

Snapshots are saved only on `main`, and only after the tests and the artifact
upload, because a snapshot saved on a tag or pull request can only be restored
by reruns of that ref. GitHub removes caches unused for more than seven days
and evicts older entries when the repository's storage limit is reached; see
its [cache access and retention rules](https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching).

To populate the cache before a release without publishing, run the workflow
on `main` without the **publish** input, or run this from the checkout:

```sh
gh workflow run flatpak.yml --ref main
```

### Publishing

With the repository variable `PUBLISH_FLATPAK` set to `true`, pushing a
stable version tag publishes a signed Flatpak repository to GitHub Pages.
Manual runs build and test only unless the **publish** input is selected;
they can publish from `main`. Pull requests and prerelease tags never
publish. Runs that can publish wait for one another, so a tag pushed during
another publication isn't built from an outdated repository head. After a tag
build passes, the workflow creates its GitHub Release with the runner's
`GITHUB_TOKEN` and attaches the tested bundles for every architecture. When
stable publication is enabled, the release waits for the signed repository's
validation and Pages deployment to succeed. Reruns replace assets on an
existing release.

A separate job, which never runs the build, downloads the published
repository and checks it against the signing key. It adds the tested builds of all
architectures as new signed commits, generates static deltas, signs a new
software catalog and summary, and writes `reddit-migration.flatpakrepo` and
`reddit-migration.flatpakref` with the public key embedded. Both files take
the app's summary from its metainfo and point to a copy of its icon, which
software centers show when the remote or app is added. Before deploying, a
fresh remote that only knows the public key must accept the summary, every
app and extension commit, and each architecture's software catalog.

The catalog refs are deleted before signing because `flatpak
build-update-repo` reuses unchanged catalog commits, including the unsigned
ones from the test repositories, without signing them.

The repository keeps the five previous versions of the app, so users can go
back to one with `flatpak update --commit`. A build whose files didn't
change adds no version. A build older than the published one, such as a rerun
of an earlier tag or a packaging revision before the current version, is
refused, because it would become the head and downgrade users on their next
update. Static deltas let Flatpak download an install or
update as a few large files instead of one request per file. They add about
a third to the repository's size, and each kept version adds only the files
that changed. If the published repository can't be downloaded or doesn't
match the signing key, for example after replacing the key, the job fails.
Set the variable `FLATPAK_KEEP_HISTORY` to `false` to publish a new
repository without the earlier versions.

The repository URL defaults to `https://OWNER.github.io/REPOSITORY/`. For a
custom domain, set the `FLATPAK_REPO_URL` variable to the real URL. The
trailing slash is optional.

To set publishing up:

1. In **Settings → Pages**, select **GitHub Actions** as the source.
2. Store the signing key as the secret `FLATPAK_GPG_PRIVATE_KEY` (see
   below).
3. Set the variable:
   `gh variable set PUBLISH_FLATPAK --body true --repo nosini/reddit-migration`.
4. Push a version tag pointing to the commit to build, or run the Flatpak
   workflow manually on `main` with **publish** selected.

Stable tags have the form `v1.0.1`. A numeric suffix such as `v1.0.1-1`
identifies a stable packaging revision of the same app version. Other
suffixes, such as `v1.0.2-rc1`, create GitHub prereleases without replacing
the stable Flatpak repository or becoming the latest stable GitHub Release.
Tag the commit containing the intended app version, metadata and workflow:

```sh
git tag -s v1.0.1 -m 'Reddit Migration 1.0.1'
git push origin v1.0.1
```

There is no need to publish a GitHub Release manually to start the build.
If **Settings → Environments → github-pages** restricts deployments to
selected branches and tags, add a Tag rule for `v*` and retain the Branch
rule for `main` so manual publication remains available.
[Deployment rules](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments#deployment-branches-and-tags)
must permit version tags separately from branches.

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
  (`~/.var/app/eu.nosini.RedditMigration/config`). On the host the private
  copy is an empty mount point, so when `/.flatpak-info` exists the app builds
  its default paths from `HOST_XDG_CONFIG_HOME` (or `~/.config`) instead, and
  the paths it prints can be opened on the host. The linter reports this grant
  as unnecessary; it is an exception in `lint-exceptions.json`.

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
source archives, except for the packages in `PREFER_WHEELS`, by default
cryptography and cffi, which need a Rust or C toolchain to build and use
prebuilt wheels for x86_64 and aarch64.

The script works around three problems of the generator. It doesn't
evaluate markers on the listed requirements, so
`scripts/filter-requirements.py` leaves out lines whose markers don't apply
to the runtime's Python on Linux, for every architecture CI builds (tomli,
for example, is only needed before Python 3.11), and removes the markers of
the lines it keeps, so pip doesn't evaluate them again for the machine it
runs on. A requirement needed on only some architectures stops the script;
add such a package as a module with `only-arches` instead. The generator
also skips packaging, pip, wheel, Cython and Meson, which are in the SDK but
not in the Platform, so the script tells it to bundle them when the app
needs them. And for `--prefer-wheels` it imports `packaging` inside the
SDK, which only has pip's copy, so the script runs a copy of the generator
that imports that one.

Without a working `flatpak run`, set `PIP_GENERATOR_PYTHON` to an
interpreter of the runtime's Python version, for example
`PIP_GENERATOR_PYTHON=python3.14`. Then pip runs there, and prebuilt wheels
aren't available, so `PREFER_WHEELS` must be empty.

The generated file pins exact wheels, so it changes only when the script
runs. Dependabot tracks the GitHub Actions but not these entries, and the
ranges in `pyproject.toml` stay valid across patch and minor releases. To
pick up upstream releases, including security fixes, rerun the script before
a release and commit the changed `python3-requirements.json`; nothing in CI
regenerates it.

## Releases

Bump `version` in `pyproject.toml` and `__version__` in
`reddit_migration/__init__.py`, and add a `<release>` entry to the metainfo
file, newest first. The workflow fails a stable tag whose version, without a
numeric packaging suffix, isn't the newest metainfo release, and a test checks
that `pyproject.toml`, `__version__` and the metainfo agree. The
installed-app checks fail when the version the app reports isn't the newest
release in the metainfo.

## Moving to a newer runtime

Change `runtime-version` in the manifest. The container image tag
`freedesktop-VERSION` appears twice in `.github/workflows/flatpak.yml`, in
the `build` and `publish` jobs, and again in the `publishing` job of
`.github/workflows/checks.yml`; keep all three in step with the manifest.
Each is pinned by digest (`freedesktop-VERSION@sha256:...`), because the
publish job imports the signing key inside it and the tag can be moved.
Dependabot doesn't update these, so look up the new tag's digest, for
example with `skopeo inspect --format '{{.Digest}}'
docker://ghcr.io/flathub-infra/flatpak-github-actions:freedesktop-VERSION`,
and refresh it the same way to pick up a rebuilt image. The actions are
pinned by commit, which Dependabot keeps updated, and the actionlint download
in `checks.yml` by checksum; update its version and checksum by hand.
`checks.yml` also pins the runtimes' Python in `python-version`, for the app
tests and the script tests; change both when the runtime's Python version
changes. If the new runtime has a different Python version, regenerate the
Python dependencies, and update the version examples in this file and in
`scripts/generate-python-deps.sh`.
