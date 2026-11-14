import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from praw.models import Comment, Submission

from reddit_migration import migrate
from reddit_migration.cli import build_parser
from reddit_migration.config import Config


class MigrationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.state_path = Path(directory.name) / "vault.json"
        self.item = Mock(spec=Submission)
        self.item.fullname = "t3_example"
        self.item.id = "example"
        self.item.permalink = "/r/example/example"
        self.item.title = "Example"
        self.item.subreddit = Mock(display_name="example")
        self.source = Mock()
        self.destination = Mock()
        self.source.user.me.return_value = "source"
        self.destination.user.me.return_value = "destination"
        self.source.redditor.return_value.saved.return_value = [self.item]
        self.args = build_parser().parse_args(
            ["--sleep", "0", "--state-file", str(self.state_path)]
        )
        for patcher in (
            patch.dict(os.environ, {
                "REDDIT_CLIENT_ID": "client-id",
                "REDDIT_ACCOUNT1_REFRESH_TOKEN": "source-token",
                "REDDIT_ACCOUNT2_REFRESH_TOKEN": "destination-token",
            }),
            patch.object(migrate, "load_secrets_into_env"),
            patch.object(migrate, "build_reddit_from_refresh_token",
                         side_effect=[self.source, self.destination]),
            patch.object(migrate, "load_config", return_value=Config()),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        detect = patch.object(migrate, "detect_source_url", return_value=None)
        self.detect = detect.start()
        self.addCleanup(detect.stop)
        self.output = io.StringIO()
        self.enter_output = redirect_stdout(self.output)
        self.enter_output.__enter__()
        self.addCleanup(self.enter_output.__exit__, None, None, None)

    def test_vault_survives_interruption_during_unsave(self):
        self.detect.return_value = "https://pixiv.net/artworks/1"
        self.item.unsave.side_effect = KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            migrate.run_migrate(self.args)
        entries = migrate.load_state(self.state_path)["migrated_sources"]
        self.assertEqual(entries[0]["reddit_fullname"], self.item.fullname)

    def test_write_failure_preserves_source_bookmark(self):
        self.detect.return_value = "https://pixiv.net/artworks/1"
        with patch.object(migrate, "save_state", side_effect=OSError("disk full")):
            self.assertEqual(migrate.run_migrate(self.args), 1)
        self.item.unsave.assert_not_called()

    def test_existing_vault_entry_is_not_duplicated(self):
        self.detect.return_value = "https://pixiv.net/artworks/1"
        state = {"migrated_sources": []}
        migrate.record_external_source(state, self.item, self.detect.return_value)
        migrate.save_state(self.state_path, state)
        migrate.run_migrate(self.args)
        self.item.unsave.assert_called_once()
        self.assertEqual(migrate.load_state(self.state_path), state)

    def test_dry_run_does_not_write_or_unsave(self):
        self.detect.return_value = "https://pixiv.net/artworks/1"
        self.args.dry_run = True
        migrate.run_migrate(self.args)
        self.item.unsave.assert_not_called()
        self.assertFalse(self.state_path.exists())

    def test_identical_accounts_are_rejected_before_reading_saved_items(self):
        self.source.user.me.return_value = "Same_User"
        self.destination.user.me.return_value = "same_user"
        with self.assertRaisesRegex(SystemExit, "same Reddit account"):
            migrate.run_migrate(self.args)
        self.source.redditor.assert_not_called()
        self.destination.submission.assert_not_called()
        self.item.unsave.assert_not_called()
        self.assertFalse(self.state_path.exists())

    def test_distinct_accounts_save_before_unsaving(self):
        actions = Mock()
        actions.attach_mock(self.destination.submission.return_value.save, "save")
        actions.attach_mock(self.item.unsave, "unsave")
        self.assertEqual(migrate.run_migrate(self.args), 0)
        self.assertEqual([c[0] for c in actions.mock_calls], ["save", "unsave"])

    def test_all_failures_return_nonzero_and_are_counted(self):
        self.destination.submission.return_value.save.side_effect = RuntimeError("API failure")
        self.assertEqual(migrate.run_migrate(self.args), 1)
        self.item.unsave.assert_not_called()
        self.assertIn("0 items migrated, 0 skipped, 1 failed", self.output.getvalue())

    def test_partial_failure_continues_and_returns_nonzero(self):
        failed_item = Mock(spec=Submission)
        failed_item.fullname = "t3_failed"
        failed_item.permalink = "/r/example/failed"
        failed_item.id = "failed"
        failed_item.subreddit = Mock(display_name="example")
        self.source.redditor.return_value.saved.return_value = [failed_item, self.item]
        # Items are processed oldest first: self.item, then failed_item.
        self.destination.submission.return_value.save.side_effect = [None, RuntimeError("API failure")]
        self.assertEqual(migrate.run_migrate(self.args), 1)
        failed_item.unsave.assert_not_called()
        self.item.unsave.assert_called_once()
        self.assertIn("1 items migrated, 0 skipped, 1 failed", self.output.getvalue())

    def test_only_skips_return_success(self):
        self.args.skip = "example"
        self.assertEqual(migrate.run_migrate(self.args), 0)
        self.item.unsave.assert_not_called()
        self.assertIn("0 items migrated, 1 skipped, 0 failed", self.output.getvalue())

    def test_dry_run_failures_return_nonzero(self):
        self.args.dry_run = True
        self.detect.side_effect = RuntimeError("read failure")
        self.assertEqual(migrate.run_migrate(self.args), 1)
        self.item.unsave.assert_not_called()
        self.assertFalse(self.state_path.exists())
        self.assertIn("0 items would be migrated, 0 skipped, 1 failed", self.output.getvalue())

    def test_failed_comment_fetch_leaves_the_item_saved(self):
        self.detect.side_effect = RuntimeError("comment fetch failed")
        self.assertEqual(migrate.run_migrate(self.args), 1)
        self.item.unsave.assert_not_called()
        self.assertIn("0 items migrated, 0 skipped, 1 failed", self.output.getvalue())

    def test_missing_client_id_points_at_login(self):
        with patch.dict(os.environ, {"REDDIT_CLIENT_ID": ""}):
            with self.assertRaisesRegex(SystemExit, "--login"):
                migrate.run_migrate(self.args)
        self.item.unsave.assert_not_called()

    def test_items_are_saved_oldest_first(self):
        items = []
        for name in ("A", "B", "C"):
            item = Mock(spec=Submission)
            item.fullname = f"t3_{name}"
            item.id = name
            item.permalink = f"/r/example/{name}"
            item.title = name
            item.subreddit = Mock(display_name="example")
            items.append(item)
        self.source.redditor.return_value.saved.return_value = items
        saved_by_id = {}

        def destination_submission(id):
            destination = Mock()
            saved_by_id[id] = destination
            return destination

        self.destination.submission.side_effect = destination_submission
        self.assertEqual(migrate.run_migrate(self.args), 0)
        self.assertEqual(
            [name for name, destination in saved_by_id.items() if destination.save.called],
            ["C", "B", "A"],
        )


class SourceUrlTests(unittest.TestCase):
    def test_extract_urls_keeps_parentheses_and_removes_markdown_escapes(self):
        text = r"https://danbooru.donmai.us/posts?tags=foo\_bar\_(artist)"
        self.assertEqual(
            migrate.extract_urls(text),
            ["https://danbooru.donmai.us/posts?tags=foo_bar_(artist)"],
        )

    def test_extract_urls_drops_the_markdown_link_closing_parenthesis(self):
        text = "[artist](https://example.com/works/a_(b))"
        self.assertEqual(migrate.extract_urls(text), ["https://example.com/works/a_(b)"])

    def test_extract_urls_drops_trailing_punctuation(self):
        text = "See https://example.com/work)."
        self.assertEqual(migrate.extract_urls(text), ["https://example.com/work"])

    def test_domain_of_ignores_ports_and_credentials(self):
        self.assertEqual(
            migrate.domain_of("https://user:pass@www.pixiv.net:443/artworks/1"),
            "www.pixiv.net",
        )

    def test_domain_matches_normalizes_configured_domains(self):
        self.assertTrue(migrate.domain_matches("www.pixiv.net", {"https://pixiv.net/"}))
        self.assertTrue(migrate.domain_matches("pixiv.net", {"pixiv.net:443"}))
        self.assertFalse(migrate.domain_matches("notpixiv.net", {"pixiv.net"}))

    def test_first_allowed_source_url_handles_ports(self):
        urls = ["https://www.pixiv.net:443/artworks/1"]
        self.assertEqual(
            migrate.first_allowed_source_url(urls, {"pixiv.net"}),
            "https://www.pixiv.net:443/artworks/1",
        )


class CommentTests(unittest.TestCase):
    def test_comment_text_does_not_fetch_the_parent_submission(self):
        class SavedComment:
            body = "comment body"
            link_title = "post title"

            @property
            def submission(self):
                raise AssertionError("the parent submission should not be fetched")

        self.assertEqual(
            migrate.comment_text(SavedComment()), "post title\ncomment body"
        )

    def test_submission_comment_text_scans_all_loaded_comments(self):
        submission = Mock()
        comment = Mock(spec=Comment)
        comment.body = "https://pixiv.net/artworks/1"
        submission.comments.list.return_value = [comment]
        self.assertEqual(
            migrate.submission_comment_text(submission),
            "https://pixiv.net/artworks/1",
        )
        submission.comments.replace_more.assert_called_once_with(limit=None)

    def test_submission_comment_text_propagates_fetch_errors(self):
        submission = Mock()
        submission.comments.replace_more.side_effect = RuntimeError("rate limited")
        with self.assertRaisesRegex(RuntimeError, "rate limited"):
            migrate.submission_comment_text(submission)


if __name__ == "__main__":
    unittest.main()
