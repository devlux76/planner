"""The launcher's post-mortem gate, on the comment formats planner writes."""
import unittest

import postmortem_gate as gate

CASE = "planner note (trailblazer) #6: Result: accepted as case vortex-" + "a" * 64 + "; supervised by Elixir."
PM = "planner note (claude) cooperative: Post-mortem 1: card too large (whole-file 490 lines); split it"


class GateTest(unittest.TestCase):
    def test_first_launch_goes_ahead(self):
        self.assertIsNone(gate.verdict(*gate.counts(["card body", "planner note (claude) x: Implementation plan: ..."])))

    def test_relaunch_needs_a_post_mortem_per_case(self):
        self.assertIn("no post-mortem", gate.verdict(*gate.counts(["body", CASE])))
        self.assertIsNone(gate.verdict(*gate.counts(["body", CASE, PM])))
        self.assertIn("case 2", gate.verdict(*gate.counts(["body", CASE, PM, CASE])))

    def test_three_post_mortems_end_the_tool_runs(self):
        msgs = ["body"] + [CASE, PM] * 3
        self.assertIn("finish this card by hand", gate.verdict(*gate.counts(msgs)))

    def test_only_a_note_starting_post_mortem_counts(self):
        self.assertEqual(gate.counts(["planner release (claude) #8: Run 1: post-mortem later"]), (0, 0))
        self.assertEqual(gate.counts(["planner note (claude) cooperative: post-mortem 2: harness"]), (0, 1))
        quoting = "planner note (claude) cooperative: Post-mortem 1: " + CASE
        self.assertEqual(gate.counts([quoting]), (0, 1))


if __name__ == "__main__":
    unittest.main()
