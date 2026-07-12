"""Interactive Reddit OAuth login for both accounts.

Runs the installed-app OAuth flow twice (source + destination) and stores the
client id, user agent, and both refresh tokens in GNOME Keyring.

One-time Reddit setup (https://www.reddit.com/prefs/apps):
  - Create an app of type "installed app"
  - Set the redirect uri to exactly:  http://localhost:8080
  - Note the client_id (the string just under the app name)
"""

from __future__ import annotations

import os
import secrets
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import praw

from .secrets_store import keyring_get, keyring_store

REDIRECT_HOST = "localhost"
DEFAULT_REDIRECT_PORT = 8080


def _redirect_uri(port: int) -> str:
    return f"http://{REDIRECT_HOST}:{port}"


def _resolve_port(port: int | None) -> int:
    if port is None:
        raw = input(
            f"OAuth redirect port (must match your Reddit app) [{DEFAULT_REDIRECT_PORT}]: "
        ).strip()
        if not raw:
            return DEFAULT_REDIRECT_PORT
        try:
            port = int(raw)
        except ValueError:
            raise SystemExit(f"Invalid port: {raw!r}")
    if not 1 <= port <= 65535:
        raise SystemExit(f"Port out of range (1-65535): {port}")
    return port

# Scopes the migrator needs:
#   identity -> reddit.user.me()
#   history  -> reading the saved list
#   read     -> fetching submissions/comments (and their comments)
#   save     -> save() / unsave()
SCOPES = ["identity", "history", "read", "save"]

DEFAULT_USER_AGENT = "linux:reddit-migration:1.0 (by /u/your_username)"


class _CallbackHandler(BaseHTTPRequestHandler):
    result: dict = {}

    def do_GET(self):
        _CallbackHandler.result = {
            k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()
        }
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        ok = "code" in _CallbackHandler.result and "error" not in _CallbackHandler.result
        msg = (
            "Authorized. You can close this tab and return to the terminal."
            if ok
            else "Authorization failed or was denied — check the terminal."
        )
        self.wfile.write(f"<html><body><h2>{msg}</h2></body></html>".encode())

    def log_message(self, *args):
        pass  # keep the console quiet


def _wait_for_callback(port: int) -> dict:
    try:
        server = HTTPServer((REDIRECT_HOST, port), _CallbackHandler)
    except OSError as exc:
        raise SystemExit(
            f"Could not bind {_redirect_uri(port)} ({exc}). "
            f"Is something already using port {port}?"
        )
    with server:
        server.handle_request()  # blocks until exactly one request is handled
    return _CallbackHandler.result


def _authorize_account(label: str, client_id: str, user_agent: str, port: int) -> str:
    reddit = praw.Reddit(
        client_id=client_id,
        client_secret=None,          # installed apps have no secret
        redirect_uri=_redirect_uri(port),
        user_agent=user_agent,
    )
    state = secrets.token_urlsafe(24)
    url = reddit.auth.url(scopes=SCOPES, state=state, duration="permanent")

    print(f"\n=== Authorize {label} ===")
    print("Opening the authorization page in your browser.")
    print("If it doesn't open, paste this URL manually:\n")
    print(f"  {url}\n")
    webbrowser.open(url)

    result = _wait_for_callback(port)

    if "error" in result:
        raise SystemExit(f"Reddit returned an error: {result['error']}")
    if result.get("state") != state:
        raise SystemExit("State mismatch — possible CSRF or a stale tab. Aborting.")
    code = result.get("code")
    if not code:
        raise SystemExit("No authorization code was received.")

    refresh_token = reddit.auth.authorize(code)  # also arms this instance
    print(f"Authorized as u/{reddit.user.me()}")
    return refresh_token


def run_login(port: int | None = None) -> int:
    client_id = (
        os.environ.get("REDDIT_CLIENT_ID")
        or keyring_get("REDDIT_CLIENT_ID")
        or input("Reddit client_id (from your installed app): ").strip()
    )
    if not client_id:
        raise SystemExit("A client_id is required.")

    user_agent = os.environ.get("REDDIT_USER_AGENT") or keyring_get("REDDIT_USER_AGENT")
    if not user_agent:
        entered = input(f"Reddit user agent [{DEFAULT_USER_AGENT}]: ").strip()
        user_agent = entered or DEFAULT_USER_AGENT

    port = _resolve_port(port)

    print(f"\nRedirect URI: {_redirect_uri(port)}  (must match your Reddit app exactly)")
    print(
        "\nReddit keeps only one account logged in per browser session, so:\n"
        "  - Account 1: authorize in your normal browser window.\n"
        "  - Account 2: open a private/incognito window and log into the other\n"
        "    account there before the second step."
    )

    input("\nStep 1/2 — log into ACCOUNT 1 (source), then press Enter...")
    rt1 = _authorize_account("ACCOUNT 1 (source)", client_id, user_agent, port)

    input("\nStep 2/2 — log into ACCOUNT 2 (destination), then press Enter...")
    rt2 = _authorize_account("ACCOUNT 2 (destination)", client_id, user_agent, port)

    keyring_store("REDDIT_CLIENT_ID", client_id, "Reddit migrator: client id")
    keyring_store("REDDIT_USER_AGENT", user_agent, "Reddit migrator: user agent")
    keyring_store("REDDIT_ACCOUNT1_REFRESH_TOKEN", rt1, "Reddit migrator: acct1 refresh")
    keyring_store("REDDIT_ACCOUNT2_REFRESH_TOKEN", rt2, "Reddit migrator: acct2 refresh")

    print("\nStored all four values in GNOME Keyring (Login keyring, visible in Seahorse).")
    print("You can now run:  reddit_migration")
    return 0
