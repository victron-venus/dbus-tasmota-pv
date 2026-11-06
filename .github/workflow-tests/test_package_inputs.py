"""Keep mandatory packaged documentation present without running a package build."""

import subprocess  # nosec B404 - required for a fixed read-only Git metadata query.
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class PackageInputTests(unittest.TestCase):
    """A documentation-only change must not remove a required package input."""

    def test_mandatory_package_inputs_are_tracked_regular_files(self):
        """Check the mandatory README copied by the package and installation scripts."""
        # scripts/build-package.sh and install.sh require this exact file.
        paths = ("README.md",)
        result = subprocess.run(  # nosec B603, B607 - fixed read-only Git index query.
            ["git", "ls-files", "--stage", "-z"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        tracked = {}
        for entry in result.stdout.split("\0"):
            if not entry:
                continue
            metadata, name = entry.split("\t", 1)
            mode, _, stage = metadata.split()
            if stage == "0":
                tracked[name] = mode
        for name in paths:
            with self.subTest(path=name):
                self.assertIsInstance(name, str)
                path = Path(name)
                self.assertFalse(path.is_absolute())
                self.assertNotIn("..", path.parts)
                self.assertIn(tracked.get(name), {"100644", "100755"})
                self.assertFalse((ROOT / path).is_symlink())
                self.assertTrue((ROOT / path).is_file(), f"Missing mandatory package input: {name}")
