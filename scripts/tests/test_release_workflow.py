#!/usr/bin/env python3
"""Exercise release classification and GitHub CLI commands without publishing."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = yaml.safe_load((ROOT / ".github/workflows/flatpak.yml").read_text())


class ReleaseWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.directory = Path(self.scratch.name)
        self.env = dict(os.environ, APP_NAME="Reddit Migration", TAG="v1.0.1")

    def run_step(self, job, name, **env):
        step = next(step for step in WORKFLOW["jobs"][job]["steps"]
                    if step.get("name") == name)
        return subprocess.run(
            ["bash", "-e", "-o", "pipefail", "-c", step["run"]],
            cwd=self.directory, env=dict(self.env, **env),
            capture_output=True, text=True,
        )

    def test_tag_classification(self):
        for tag, stable in (
            ("v1.0.1", True), ("v1.0.1-1", True), ("v1.0.1-12", True),
            ("v1.0.2-rc1", False), ("v1.0.2-beta.2", False),
            ("v1.0.2rc1", False), ("v1.0.1-", False),
            ("v1.0.1-1rc1", False), ("vnext", False),
        ):
            with self.subTest(tag=tag):
                output = self.directory / "output"
                result = self.run_step(
                    "setup", "Classify the release tag",
                    TAG=tag, GITHUB_OUTPUT=str(output),
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(output.read_text(), f"stable={str(stable).lower()}\n")
                output.unlink()

    def release_commands(self, *, stable="true", exists="false", fail=""):
        bundles = self.directory / "bundles"
        bundles.mkdir()
        for arch in ("x86_64", "aarch64"):
            (bundles / f"reddit-migration-{arch}.flatpak").touch()
        binary = self.directory / "gh"
        binary.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "args = sys.argv[1:]\n"
            "if args[:2] == ['release', 'view']:\n"
            "    sys.exit(0 if os.environ['RELEASE_EXISTS'] == 'true' else 1)\n"
            "with open(os.environ['GH_LOG'], 'a') as log:\n"
            "    log.write(json.dumps(args) + '\\n')\n"
            "sys.exit(1 if args[1] == os.environ['RELEASE_FAIL'] else 0)\n"
        )
        binary.chmod(0o755)
        log = self.directory / "gh.jsonl"
        result = self.run_step(
            "release", "Create the release and upload the tested bundles",
            PATH=f"{self.directory}:{os.environ['PATH']}", STABLE=stable,
            RELEASE_EXISTS=exists, RELEASE_FAIL=fail, GH_LOG=str(log),
        )
        commands = [json.loads(line) for line in log.read_text().splitlines()]
        return result, commands

    def test_stable_release_verifies_tag_and_attaches_both_architectures(self):
        result, commands = self.release_commands()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(commands), 1)
        args = commands[0]
        self.assertEqual(args[:3], ["release", "create", "v1.0.1"])
        self.assertIn("--verify-tag", args)
        self.assertIn("--generate-notes", args)
        for arch in ("x86_64", "aarch64"):
            self.assertIn(f"bundles/reddit-migration-{arch}.flatpak", args)
        self.assertNotIn("--prerelease", args)

    def test_prerelease_cannot_become_latest(self):
        result, commands = self.release_commands(stable="false")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--prerelease", commands[0])
        self.assertIn("--latest=false", commands[0])

    def test_rerun_replaces_assets_on_existing_release(self):
        result, commands = self.release_commands(exists="true")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0][:3], ["release", "upload", "v1.0.1"])
        self.assertIn("--clobber", commands[0])
        for arch in ("x86_64", "aarch64"):
            self.assertIn(f"bundles/reddit-migration-{arch}.flatpak", commands[0])

    def test_rerun_keeps_existing_prerelease_out_of_latest(self):
        result, commands = self.release_commands(stable="false", exists="true")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(commands[0], [
            "release", "edit", "v1.0.1", "--prerelease", "--latest=false",
        ])
        self.assertEqual(commands[1][:3], ["release", "upload", "v1.0.1"])
        self.assertIn("--clobber", commands[1])

    def test_creation_failure_fails_the_step(self):
        result, _ = self.release_commands(fail="create")
        self.assertNotEqual(result.returncode, 0)

    def test_upload_failure_fails_the_step(self):
        result, _ = self.release_commands(exists="true", fail="upload")
        self.assertNotEqual(result.returncode, 0)

    def test_failed_prerelease_update_stops_before_upload(self):
        result, commands = self.release_commands(
            stable="false", exists="true", fail="edit",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0][1], "edit")


if __name__ == "__main__":
    unittest.main()
