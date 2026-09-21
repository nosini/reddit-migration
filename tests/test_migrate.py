import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from praw.models import Submission

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
            migrate.run_migrate(self.args)
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


if __name__ == "__main__":
    unittest.main()
