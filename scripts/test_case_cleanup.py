"""Completion cleanup cannot run against an open case."""
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import case_cleanup


class CleanupTest(unittest.TestCase):
    def test_waits_for_terminal_case_before_invoking_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = root / "cases.db"
            case = "vortex-" + "a" * 64
            with sqlite3.connect(database) as conn:
                conn.execute("CREATE TABLE task_case (id TEXT, status TEXT)")
                conn.execute("INSERT INTO task_case VALUES (?, 'open')", (case,))
            release = root / "release"
            release.write_text('#!/bin/sh\ntouch "' + str(root / 'called') + '"\n')
            release.chmod(0o700)
            with patch.multiple(case_cleanup, ROOT=root, RELEASE=release, DATABASE=database,
                                STATE=root, POLL_SECONDS=0.01):
                result = []
                worker = threading.Thread(target=lambda: result.append(case_cleanup.cleanup(case)))
                worker.start()
                time.sleep(0.05)
                self.assertFalse((root / "called").exists())
                self.assertTrue(worker.is_alive())
                with sqlite3.connect(database) as conn:
                    conn.execute("UPDATE task_case SET status='fixed'")
                worker.join(2)
                self.assertFalse(worker.is_alive())
                self.assertEqual(result[0]["status"], "fixed")
                self.assertEqual(result[0]["cleanup_exit"], 0)


if __name__ == "__main__":
    unittest.main()
