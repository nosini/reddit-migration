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
        # Keep the legacy ./migrated_sources.json check independent of where
        # the tests are run from.
        self.cwd = Path.cwd()
        working = tempfile.TemporaryDirectory()
        self.addCleanup(working.cleanup)
        os.chdir(working.name)
        self.addCleanup(os.chdir, self.cwd)
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

    def test_update_preserves_custom_domains(self):
        self.path.write_text('[sources]\ndomains = ["example.org"]\n', encoding="utf-8")
        update_config(str(self.path))
        self.assertEqual(load_config(str(self.path)).source_domains, {"example.org"})
        self.assertIn('domains = ["example.org"]', self.path.read_text(encoding="utf-8"))

    def test_default_config_keeps_domains_unpinned(self):
        text = config.render_config(Config())
        self.assertIn("# domains = ", text)
        self.assertNotIn("\ndomains = ", text)

    def test_string_instead_of_list_is_rejected(self):
        self.path.write_text('[subreddits]\nonly = "pics"\n', encoding="utf-8")
        with self.assertRaises(SystemExit) as caught:
            load_config(str(self.path))
        message = str(caught.exception)
        self.assertIn(str(self.path), message)
        self.assertIn("subreddits.only", message)
        self.assertIn("list of strings", message)

    def test_string_instead_of_domain_list_is_rejected(self):
        self.path.write_text('[sources]\ndomains = "pixiv.net"\n', encoding="utf-8")
        with self.assertRaises(SystemExit) as caught:
            load_config(str(self.path))
        self.assertIn("sources.domains", str(caught.exception))

    def test_string_instead_of_boolean_is_rejected(self):
        self.path.write_text('[items]\nskip_comments = "false"\n', encoding="utf-8")
        with self.assertRaises(SystemExit) as caught:
            load_config(str(self.path))
        self.assertIn("items.skip_comments", str(caught.exception))

    def test_scalar_instead_of_table_is_rejected(self):
        self.path.write_text("subreddits = 1\n", encoding="utf-8")
        with self.assertRaises(SystemExit) as caught:
            load_config(str(self.path))
        self.assertIn("subreddits", str(caught.exception))
        self.assertIn("table", str(caught.exception))

    def test_unknown_key_is_rejected(self):
        self.path.write_text('[items]\nskip_comment = true\n', encoding="utf-8")
        with self.assertRaises(SystemExit) as caught:
            load_config(str(self.path))
        self.assertIn("items.skip_comment", str(caught.exception))

    def test_toml_syntax_error_names_the_file(self):
        self.path.write_text('[subreddits\nonly = ["pics"]\n', encoding="utf-8")
        with self.assertRaises(SystemExit) as caught:
            load_config(str(self.path))
        self.assertIn(str(self.path), str(caught.exception))

    def test_relative_state_file_is_resolved_against_the_config_folder(self):
        self.path.write_text('[state]\nfile = "vault.json"\n', encoding="utf-8")
        cfg = load_config(str(self.path))
        self.assertEqual(resolve_state_path(cfg), self.path.parent / "vault.json")

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
