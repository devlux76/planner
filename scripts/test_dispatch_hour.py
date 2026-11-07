"""The dispatch-hour guard stops only an open case, and only at its deadline."""
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

import dispatch_hour

CASE = "vortex-" + "a" * 64


class GuardTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = Path(tmp.name) / "cases.db"
        with sqlite3.connect(self.db) as conn:
            conn.execute("CREATE TABLE task_case (id TEXT, task TEXT, status TEXT, opened_at INTEGER)")
            conn.execute("INSERT INTO task_case VALUES (?, ?, 'open', 0)", (CASE, "{}"))
        patcher = patch.object(dispatch_hour, "POLL_SECONDS", 0.01)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_an_open_case_is_stopped_at_the_deadline(self):
        calls = []
        result = dispatch_hour.guard(CASE, time.time() + 0.05, self.db, lambda c: calls.append(c) or "stopped\n")
        self.assertEqual(calls, [CASE])
        self.assertTrue(result["stopped"])

    def test_a_closed_case_is_left_alone(self):
        with sqlite3.connect(self.db) as conn:
            conn.execute("UPDATE task_case SET status='fixed'")
        result = dispatch_hour.guard(CASE, time.time() + 60, self.db, lambda c: self.fail("stopped a closed case"))
        self.assertEqual(result["status"], "fixed")

    def test_stop_program_parses(self):
        subprocess.run(["elixir", "-e", "Code.string_to_quoted!(hd(System.argv()))", dispatch_hour.STOP],
                       check=True, capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()
