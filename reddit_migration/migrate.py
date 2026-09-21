"""Migrate saved Reddit items from one account to another.

What it does:
- Reads the saved list from account 1.
- Extracts a source URL from the post body, linked URL, or comments.
- If the source domain is Pixiv, Danbooru, or Gelbooru, it stores that external
  source in a local JSON vault and unsaves the Reddit item from account 1.
- Otherwise, it saves the Reddit submission/comment on account 2 and unsaves it
  from account 1.

Reddit's saved items are submissions/comments, not arbitrary external URLs, so an
external source URL can't literally be "saved" on Reddit on its own — those are
kept in the local JSON vault instead.
"""

from __future__ import annotations

import json
import re
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urlparse

import praw
from praw.models import Comment, Submission

from .config import load_config, resolve_state_path
from .secrets_store import load_secrets_into_env

# Blacklist: items from these subreddits are always skipped.
# Use lowercase names without the "r/" prefix, e.g. "announcements".
# (Can be extended at runtime with --skip.)
SKIP_SUBREDDITS = set()

# Whitelist: if this set is non-empty, ONLY items from these subreddits are
# processed; everything else is skipped. Leave it empty to process every
# subreddit (subject to the blacklist above).
# Use lowercase names without the "r/" prefix, e.g. "pics".
# (Can be extended at runtime with --only.)
ONLY_SUBREDDITS = set()

# Source domains are configured, not hardcoded — see config.py (DEFAULT_SOURCE_DOMAINS),
# the [sources].domains config key, and the --source-domain flag.

URL_RE = re.compile(r"https?://[^\s<>()\[\]{}\"']+", re.IGNORECASE)


@dataclass
class MigratedSource:
    reddit_fullname: str
    reddit_permalink: str
    reddit_kind: str
    source_url: str
    source_domain: str
    title: str


def build_reddit_from_refresh_token(refresh_token: str) -> praw.Reddit:
    import os

    client_id = os.environ["REDDIT_CLIENT_ID"]
    user_agent = os.environ.get("REDDIT_USER_AGENT", "saved-migrator/1.0")

    return praw.Reddit(
        client_id=client_id,
        client_secret=None,
        refresh_token=refresh_token,
        user_agent=user_agent,
    )


def domain_of(url: str) -> str:
    return (urlparse(url).netloc or "").lower()


def normalize_url(url: str) -> str:
    return url.rstrip('.,);]}>"\'')


def extract_urls(text: str) -> list[str]:
    if not text:
        return []
    return [normalize_url(m.group(0)) for m in URL_RE.finditer(text)]


def domain_matches(domain: str, allowed: set) -> bool:
    """True if `domain` equals or is a subdomain of any configured domain."""
    return any(domain == d or domain.endswith("." + d) for d in allowed)


def first_allowed_source_url(urls: Iterable[str], allowed_domains: set) -> Optional[str]:
    for url in urls:
        if domain_matches(domain_of(url), allowed_domains):
            return url
    return None


def comment_text(comment: Comment) -> str:
    body = getattr(comment, "body", "") or ""
    title = getattr(comment.submission, "title", "") if getattr(comment, "submission", None) else ""
    return f"{title}\n{body}"


def submission_self_text(submission: Submission) -> str:
    """Title, selftext, and linked URL of the post itself (no comment fetch)."""
    parts = [
        getattr(submission, "title", "") or "",
        getattr(submission, "selftext", "") or "",
        getattr(submission, "url", "") or "",
    ]
    return "\n".join(parts)


def submission_comment_text(submission: Submission) -> str:
    """Bodies of all comments on the post. Fetches the comment tree."""
    parts = []
    try:
        submission.comments.replace_more(limit=0)
        for comment in submission.comments.list():
            if isinstance(comment, Comment):
                body = getattr(comment, "body", "") or ""
                if body:
                    parts.append(body)
    except Exception as exc:
        print(f"  [warn] comment fetch failed: {exc}", file=sys.stderr)

    return "\n".join(parts)


def item_meta(item) -> tuple[str, str, str]:
    if isinstance(item, Submission):
        return (item.fullname, item.permalink, "submission")
    if isinstance(item, Comment):
        return (item.fullname, item.permalink, "comment")
    raise TypeError(f"Unsupported saved item type: {type(item)!r}")


def item_title(item) -> str:
    if isinstance(item, Submission):
        return getattr(item, "title", "") or ""
    if isinstance(item, Comment):
        body = (getattr(item, "body", "") or "").strip().replace("\n", " ")
        return body[:120]
    return ""


def detect_source_url(item, allowed_domains: set) -> Optional[str]:
    if isinstance(item, Submission):
        # Check the post itself first; only scan the (expensive) comment tree
        # as a fallback when the post's own text/url has no matching source.
        urls = extract_urls(submission_self_text(item))
        match = first_allowed_source_url(urls, allowed_domains)
        if match:
            return match
        comment_urls = extract_urls(submission_comment_text(item))
        return first_allowed_source_url(comment_urls, allowed_domains)
    elif isinstance(item, Comment):
        urls = extract_urls(comment_text(item))
        return first_allowed_source_url(urls, allowed_domains)
    else:
        return None


def load_state(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"migrated_sources": []}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write to a temp file first then replace, so a crash mid-write doesn't corrupt state.
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def already_recorded(state: dict, fullname: str) -> bool:
    return any(entry.get("reddit_fullname") == fullname for entry in state.get("migrated_sources", []))


def record_external_source(state: dict, item, source_url: str) -> None:
    fullname, permalink, kind = item_meta(item)
    entry = MigratedSource(
        reddit_fullname=fullname,
        reddit_permalink=permalink,
        reddit_kind=kind,
        source_url=source_url,
        source_domain=domain_of(source_url),
        title=item_title(item),
    )
    state.setdefault("migrated_sources", []).append(asdict(entry))


def migrate_one(
    item,
    reddit_dst: praw.Reddit,
    state: dict,
    sleep_secs: float,
    skip_subreddits: set,
    only_subreddits: set,
    allowed_domains: set,
    skip_comments: bool = False,
    dry_run: bool = False,
    *,
    state_path: Path,
) -> tuple[bool, str]:
    """Process one saved item.

    Returns (migrated, message): `migrated` is True only when the item was
    actually migrated (external-source or reddit outcome), False for skips.
    """
    fullname, permalink, kind = item_meta(item)

    if skip_comments and kind == "comment":
        return False, f"skip {fullname} (comment)"

    # item.subreddit works for both submissions and comments.
    subreddit = item.subreddit.display_name.lower()

    if only_subreddits and subreddit not in only_subreddits:
        return False, f"skip {fullname} (not in whitelist)"

    if subreddit in skip_subreddits:
        return False, f"skip {fullname} (subreddit)"

    source_url = detect_source_url(item, allowed_domains)
    if source_url:
        # Record only if not already recorded (avoid duplicates), but always
        # perform the unsave so a previous crash between record and unsave
        # self-heals on rerun instead of leaving the item saved forever.
        if not already_recorded(state, fullname):
            record_external_source(state, item, source_url)
        if not dry_run:
            # Commit the vault before removing the only saved Reddit reference.
            # Retry persistence even for an entry retained in memory after a failure.
            save_state(state_path, state)
            item.unsave()
            time.sleep(sleep_secs)
        return True, f"external {fullname} -> {source_url}"

    # No external source found — save the Reddit item on account 2 then unsave from account 1.
    if not dry_run:
        if isinstance(item, Submission):
            dst_item = reddit_dst.submission(id=item.id)
        else:
            dst_item = reddit_dst.comment(id=item.id)
        dst_item.save()
        time.sleep(sleep_secs)
        item.unsave()
        time.sleep(sleep_secs)
    return True, f"reddit {fullname} -> saved on account2 then unsaved on account1"


def _split_csv(value: str) -> set:
    return {part.strip().lower() for part in (value or "").split(",") if part.strip()}


def run_migrate(args) -> int:
    import os

    # Pull REDDIT_* out of GNOME Keyring (populated by `reddit_migration --login`)
    # unless they're already set in the environment.
    load_secrets_into_env()

    if (
        "REDDIT_ACCOUNT1_REFRESH_TOKEN" not in os.environ
        or "REDDIT_ACCOUNT2_REFRESH_TOKEN" not in os.environ
    ):
        raise SystemExit(
            "Missing Reddit refresh tokens. Run `reddit_migration --login` first "
            "to authorize both accounts."
        )

    refresh1 = os.environ["REDDIT_ACCOUNT1_REFRESH_TOKEN"]
    refresh2 = os.environ["REDDIT_ACCOUNT2_REFRESH_TOKEN"]

    reddit1 = build_reddit_from_refresh_token(refresh1)
    reddit2 = build_reddit_from_refresh_token(refresh2)

    me1 = reddit1.user.me()
    me2 = reddit2.user.me()
    if str(me1).casefold() == str(me2).casefold():
        raise SystemExit(
            "Source and destination are the same Reddit account. "
            "Authorize two different accounts before migrating."
        )
    print(f"Account 1: u/{me1}")
    print(f"Account 2: u/{me2}")

    # Effective filters = built-in constants | config file | CLI flags.
    cfg = load_config(getattr(args, "config", None))
    skip_subreddits = set(SKIP_SUBREDDITS) | cfg.skip | _split_csv(getattr(args, "skip", ""))
    only_subreddits = set(ONLY_SUBREDDITS) | cfg.only | _split_csv(getattr(args, "only", ""))
    allowed_domains = set(cfg.source_domains) | _split_csv(getattr(args, "source_domain", ""))
    skip_comments = cfg.skip_comments or getattr(args, "skip_comments", False)

    print(f"Source domains: {', '.join(sorted(allowed_domains)) or '(none)'}")

    # --state-file / $MIGRATION_STATE_FILE win; otherwise the config's
    # [state].file, a legacy ./migrated_sources.json, or the XDG default.
    state_path = Path(args.state_file).expanduser() if args.state_file else resolve_state_path(cfg)
    print(f"State file: {state_path}")
    state = load_state(state_path)

    # Materialize the whole saved listing before processing. Unsaving items as
    # we go mutates the listing that `after`-fullname pagination anchors on, so
    # a lazy iterator would silently skip items.
    items = list(reddit1.redditor(str(me1)).saved(limit=None))

    processed = 0
    skipped = 0
    for item in items:
        if args.limit and processed >= args.limit:
            break

        try:
            migrated, message = migrate_one(
                item,
                reddit2,
                state,
                args.sleep,
                skip_subreddits,
                only_subreddits,
                allowed_domains,
                skip_comments=skip_comments,
                dry_run=args.dry_run,
                state_path=state_path,
            )
            print(message)
            if migrated:
                processed += 1
            else:
                skipped += 1
        except Exception as exc:
            fullname = getattr(item, "fullname", "unknown")
            print(f"error {fullname}: {exc}", file=sys.stderr)
            continue

    if args.dry_run:
        print(f"Dry run complete. {processed} items would be migrated, {skipped} skipped.")
    else:
        print(
            f"Done. {processed} items migrated, {skipped} skipped. "
            f"{len(state.get('migrated_sources', []))} external-source entries in {state_path}"
        )

    return 0
