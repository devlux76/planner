"""The window fit check, against the measured case sizes."""
from pathlib import Path
import tempfile
import unittest

import window_fit


class FitTest(unittest.TestCase):
    def test_small_files_fit_and_a_646_line_file_does_not(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "small.ts").write_text("x" * 4000)
            (Path(d) / "big.ts").write_text("x" * 26000)  # claude.test.ts, 646 lines
            window_fit.check(d, ["small.ts", "missing.ts"])
            with self.assertRaisesRegex(ValueError, "too large for one coder window"):
                window_fit.check(d, ["big.ts"])
            window_fit.check(None, ["big.ts"])


if __name__ == "__main__":
    unittest.main()
