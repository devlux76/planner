"""admit_check writes both configs in the shape Trailblazer validates."""
import json
from pathlib import Path
import tempfile
import unittest

import admit_check

W = "/tmp/wt-admit-test"


class AdmitTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.planner = root / "planner.json"
        self.vortex = root / "vortex.json"
        self.planner.write_text(json.dumps({"repos": {W: ["old"]}}))
        self.vortex.write_text(json.dumps({"peers": [
            {"peer": "a", "repos": {"/other": ["x"]}},
            {"peer": "b", "repos": {W: ["old"]}, "compilation": {W: {"old": "tsc"}}}]}))
        Path(W).mkdir(exist_ok=True)

    def admit(self, check, compile_cmd=None):
        return admit_check.admit(W, check, compile_cmd, self.planner, self.vortex)

    def test_both_configs_get_the_check_and_compile_nests_under_the_repo(self):
        self.admit("bash check.sh", "python3 -m py_compile a.py")
        self.assertEqual(json.loads(self.planner.read_text())["repos"][W], ["old", "bash check.sh"])
        peer = json.loads(self.vortex.read_text())["peers"][1]
        self.assertEqual(peer["repos"][W], ["old", "bash check.sh"])
        self.assertEqual(peer["compilation"][W], {"old": "tsc", "bash check.sh": "python3 -m py_compile a.py"})
        self.assertNotIn("bash check.sh", peer["compilation"])

    def test_a_blank_compile_command_is_refused(self):
        before = (self.planner.read_text(), self.vortex.read_text())
        with self.assertRaises(ValueError):
            self.admit("bash check.sh", "  ")
        self.assertEqual(before, (self.planner.read_text(), self.vortex.read_text()))

    def test_admitting_twice_changes_nothing(self):
        self.admit("bash check.sh")
        before = (self.planner.read_text(), self.vortex.read_text())
        self.admit("bash check.sh")
        self.assertEqual(before, (self.planner.read_text(), self.vortex.read_text()))

    def test_unregistered_worktree_or_bad_shape_writes_nothing(self):
        before = (self.planner.read_text(), self.vortex.read_text())
        with self.assertRaises(ValueError):
            admit_check.admit("/tmp", "c", None, self.planner, self.vortex)
        bad = json.loads(self.vortex.read_text())
        bad["peers"][1]["compilation"]["stray check"] = "tsc"
        self.vortex.write_text(json.dumps(bad))
        before = (self.planner.read_text(), self.vortex.read_text())
        with self.assertRaises(ValueError):
            self.admit("new")
        self.assertEqual(before, (self.planner.read_text(), self.vortex.read_text()))


if __name__ == "__main__":
    unittest.main()
