"""Behavioral checks for `planner add --label` against a real temporary git-bug repository."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

CLI = Path(__file__).with_name("planner.py")


class PlannerAddLabelTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root/"repo"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("bug", "user", "new", "-n", "fixture", "-e", "fixture@example.invalid", "--non-interactive")
        self.repos = self.root/"repos"
        self.repos.write_text(str(self.repo)+"\n")
        self.base = [sys.executable, str(CLI), "--repos-file", str(self.repos), "--state-dir", str(self.root/"state")]

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True, capture_output=True, text=True).stdout

    def call(self, *args, ok=True):
        p = subprocess.run(self.base+["--actor", "glm", *args], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0 if ok else 1, p.stdout+p.stderr)
        return json.loads(p.stdout if ok else p.stderr)

    def test_extra_label_is_applied_next_to_defaults_and_bad_labels_create_nothing(self):
        ref = self.call("add", "repo", "--title", "t", "--plan", "p", "--label", "dispatch:ready")["ref"]
        self.assertTrue({"dispatch:ready", "status:todo", "kind:task", "priority:p2"} <= set(self.call("show", ref)["labels"]))
        before = self.call("board", "--repo", "repo")["counts"]["todo"]
        for bad in ("status:done", "kind:bug", "priority:p0", "two words", ""):
            self.call("add", "repo", "--title", "t", "--plan", "p", "--label", bad, ok=False)
        self.assertEqual(self.call("board", "--repo", "repo")["counts"]["todo"], before)


if __name__ == "__main__":
    unittest.main()
