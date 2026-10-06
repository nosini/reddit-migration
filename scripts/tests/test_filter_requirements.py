"""Tests for scripts/filter-requirements.py. Needs the packaging module."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "filter-requirements.py"


class FilterRequirementsTest(unittest.TestCase):
    def run_filter(self, lines, python="3.14.0", arches=None):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            source, target = tmp / "requirements.txt", tmp / "filtered.txt"
            source.write_text("".join(line + "\n" for line in lines))
            args = [sys.executable, SCRIPT, python, source, target]
            if arches is not None:
                (tmp / "flathub.json").write_text(json.dumps({"only-arches": arches}))
                args.append(tmp / "flathub.json")
            result = subprocess.run(args, capture_output=True, text=True)
            kept = target.read_text().splitlines() if target.exists() else None
            return result, kept

    def test_keeps_lines_without_markers_and_comments(self):
        lines = ["# pinned", "requests==2.32.5", "", "--only-binary=:all:"]
        result, kept = self.run_filter(lines)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(kept, lines)

    def test_python_version_markers_use_the_runtime(self):
        result, kept = self.run_filter([
            'tomli==2.2.1; python_version < "3.11"',
            'new==1.0; python_full_version >= "3.14.0"',
        ])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(kept, ["new==1.0"])

    def test_implementation_markers_use_the_runtime_not_the_host(self):
        result, kept = self.run_filter([
            'new==1.0; implementation_version >= "3.14"',
            'cpy==1.0; implementation_name == "cpython"',
            'pypy==1.0; platform_python_implementation == "PyPy"',
        ])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(kept, ["new==1.0", "cpy==1.0"])

    def test_platform_markers_are_linux(self):
        result, kept = self.run_filter([
            'win==1.0; sys_platform == "win32"',
            'posix==1.0; os_name == "posix" and platform_system == "Linux"',
        ])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(kept, ["posix==1.0"])

    def test_requirement_for_some_architectures_stops(self):
        result, kept = self.run_filter(['arm==1.0; platform_machine == "aarch64"'])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("only needed on aarch64", result.stderr)

    def test_architectures_come_from_flathub_json(self):
        line = 'arm[extra]>=1.0; platform_machine == "aarch64"'
        # The marker is removed, so pip on an x86_64 machine keeps it too.
        result, kept = self.run_filter([line], arches=["aarch64"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(kept, ["arm[extra]>=1.0"])
        result, kept = self.run_filter([line], arches=["x86_64"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(kept, [])

    def test_kernel_markers_stop(self):
        result, kept = self.run_filter(['k==1.0; platform_release >= "6"'])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("platform_release", result.stderr)


if __name__ == "__main__":
    unittest.main()
