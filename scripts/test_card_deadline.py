"""The card-hour guard stops only an open case, and only at its deadline."""
from pathlib import Path
import json
import sqlite3
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

import card_deadline

CASE = "vortex-" + "a" * 64


def req(title, body=""):
    return json.dumps({"request": "T " + title + "\n\nImplementation plan: " + body})


class GuardTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = Path(tmp.name) / "cases.db"
        with sqlite3.connect(self.db) as conn:
            conn.execute("CREATE TABLE task_case (id TEXT, task TEXT, status TEXT, opened_at INTEGER)")
            conn.execute("INSERT INTO task_case VALUES (?, ?, 'open', 0)", (CASE, req("bug:1234567")))
        patcher = patch.object(card_deadline, "POLL_SECONDS", 0.01)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_an_open_case_is_stopped_at_the_deadline(self):
        calls = []
        result = card_deadline.guard(CASE, time.time() + 0.05, self.db, lambda c: calls.append(c) or "stopped\n")
        self.assertEqual(calls, [CASE])
        self.assertTrue(result["stopped"])

    def test_a_closed_case_is_left_alone(self):
        with sqlite3.connect(self.db) as conn:
            conn.execute("UPDATE task_case SET status='fixed'")
        result = card_deadline.guard(CASE, time.time() + 60, self.db, lambda c: self.fail("stopped a closed case"))
        self.assertEqual(result["status"], "fixed")

    def test_no_case_yet_gives_a_full_hour_and_bad_refs_are_refused(self):
        now = time.time()
        self.assertEqual(card_deadline.deadline("vortex:7654321", now, self.db), now + 3600)
        with self.assertRaises(ValueError):
            card_deadline.deadline("vortex:x' OR 1=1", now, self.db)

    def test_only_the_title_tag_names_the_card_and_prefixes_match_both_ways(self):
        with sqlite3.connect(self.db) as conn:
            conn.execute("DELETE FROM task_case")
            conn.execute("INSERT INTO task_case VALUES ('a', ?, 'failed', 1000)", (req("bug:7654321", "see bug:1234567"),))
            conn.execute("INSERT INTO task_case VALUES ('b', ?, 'failed', 5000)", (req("bug:1234567"),))
            conn.execute("INSERT INTO task_case VALUES ('c', ?, 'failed', 9000)", (req("bug:1234567"),))
        self.assertEqual(card_deadline.card_started_at("vortex:1234567", self.db), 5)
        self.assertEqual(card_deadline.card_started_at("vortex:1234567abcdef", self.db), 5)
        self.assertEqual(card_deadline.card_started_at("vortex:7654321", self.db), 1)

    def test_stop_program_parses(self):
        subprocess.run(["elixir", "-e", "Code.string_to_quoted!(hd(System.argv()))", card_deadline.STOP],
                       check=True, capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()
