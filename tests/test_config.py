import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from reddit_migration.cli import main
from reddit_migration.config import Config, load_config, update_config


class ConfigTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "custom.toml"
        env = patch.dict(os.environ, {"XDG_CONFIG_HOME": directory.name}, clear=True)
        env.start()
        self.addCleanup(env.stop)

    def test_missing_explicit_config_is_rejected(self):
        with self.assertRaisesRegex(SystemExit, "Config file not found"):
            load_config(str(self.path))

    def test_missing_environment_config_is_rejected(self):
        with patch.dict(os.environ, {"REDDIT_MIGRATION_CONFIG": str(self.path)}):
            with self.assertRaisesRegex(SystemExit, "Config file not found"):
                load_config()

    def test_missing_default_config_uses_defaults(self):
        self.assertEqual(load_config(), Config())

    def test_missing_config_stops_before_credentials_or_api_access(self):
        with patch("reddit_migration.migrate.load_secrets_into_env") as secrets:
            with patch("reddit_migration.migrate.build_reddit_from_refresh_token") as reddit:
                with self.assertRaisesRegex(SystemExit, "Config file not found"):
                    main(["--config", str(self.path)])
        secrets.assert_not_called()
        reddit.assert_not_called()

    def test_update_can_create_an_explicit_config(self):
        self.assertEqual(update_config(str(self.path)), self.path)
        self.assertEqual(load_config(str(self.path)), Config())

    def test_update_preserves_existing_filters(self):
        self.path.write_text('[subreddits]\nonly = ["pics"]\n', encoding="utf-8")
        update_config(str(self.path))
        self.assertEqual(load_config(str(self.path)).only, {"pics"})


if __name__ == "__main__":
    unittest.main()
