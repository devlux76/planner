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

    def test_a_long_file_counts_at_its_ranged_share(self):
        with tempfile.TemporaryDirectory() as d:
            # hub/store.ts shape: 766 lines, ~31 KB; the coder sees <=300 of them
            (Path(d) / "store.ts").write_text("y" * 40 + "\n" + ("x" * 39 + "\n") * 765)
            tokens, _ = window_fit.estimate(d, ["store.ts"])
            self.assertLess(tokens, 10500)
            window_fit.check(d, ["store.ts"])


if __name__ == "__main__":
    unittest.main()
