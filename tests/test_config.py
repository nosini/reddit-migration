import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from reddit_migration.cli import main
from reddit_migration import config
from reddit_migration.config import Config, config_path, load_config, resolve_state_path, update_config


class ConfigTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "custom.toml"
        env = patch.dict(os.environ, {"XDG_CONFIG_HOME": directory.name}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        flatpak = patch.object(config, "FLATPAK_INFO", Path(directory.name) / ".flatpak-info")
        flatpak.start()
        self.addCleanup(flatpak.stop)

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

    def test_default_paths_use_xdg_config_home(self):
        folder = Path(os.environ["XDG_CONFIG_HOME"]) / "reddit_migration"
        self.assertEqual(config_path(), folder / "config.toml")
        self.assertEqual(resolve_state_path(Config()), folder / "migrated_sources.json")

    def test_flatpak_default_paths_use_the_host_folder(self):
        # The app's private XDG_CONFIG_HOME only exists inside the sandbox;
        # the reported paths must be the host's.
        config.FLATPAK_INFO.touch()
        host = Path(os.environ["XDG_CONFIG_HOME"]) / "host"
        with patch.dict(os.environ, {"HOST_XDG_CONFIG_HOME": str(host)}):
            self.assertEqual(config_path(), host / "reddit_migration" / "config.toml")
            self.assertEqual(
                resolve_state_path(Config()), host / "reddit_migration" / "migrated_sources.json"
            )
        with patch.object(Path, "home", return_value=Path("/home/user")):
            self.assertEqual(config_path(), Path("/home/user/.config/reddit_migration/config.toml"))


if __name__ == "__main__":
    unittest.main()
