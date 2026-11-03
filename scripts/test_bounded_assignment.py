"""No model or live service: exercise the launch sequence with real child processes."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import bounded_assignment as bounded


class BoundedAssignmentTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.events = root / "events"
        self.fail_file = root / "fail"
        driver = root / "driver"
        driver.write_text('''#!/usr/bin/env python3
import json,pathlib,sys
root=pathlib.Path(__file__).parent
op=sys.argv[1]
if 'assign' in sys.argv: op='assign'
if op=='rpc': op='bind' if 'CaseRecord.event' in sys.argv[2] else ('release' if 'persistent_term.erase' in sys.argv[2] else 'prepare')
with (root/'events').open('a') as f: f.write(op+'\\n')
if (root/'fail').exists() and (root/'fail').read_text()==op: sys.exit(2)
if op=='assign': (root/'assign-args.json').write_text(json.dumps(sys.argv[1:]))
if op=='prepare': print((root/'prepare-reply').read_text() if (root/'prepare-reply').exists() else json.dumps({'output_cap':16384}))
if op=='assign': print((root/'assign-reply').read_text() if (root/'assign-reply').exists() else json.dumps({'case':'vortex-'+('a'*64),'dispatched':True}))
''')
        driver.chmod(0o700)
        watchdog = root / "watchdog.py"
        watchdog.touch()
        for key, value in {"ROOT": root, "RELEASE": driver, "PLANNER": driver,
                           "SYSTEMD_RUN": driver, "CLEANUP": watchdog}.items():
            patcher = patch.object(bounded, key, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def launch(self):
        return bounded.launch("opencode:1234567", "check", ["a.ts"], 0, 1024)

    def test_failed_preparation_cannot_dispatch(self):
        self.fail_file.write_text("prepare")
        with self.assertRaises(subprocess.CalledProcessError):
            self.launch()
        self.assertEqual(self.events.read_text().splitlines(), ["prepare", "release"])

    def test_uncertain_admission_is_never_retried_or_followed_by_a_watchdog(self):
        self.fail_file.write_text("assign")
        with self.assertRaises(subprocess.CalledProcessError):
            self.launch()
        self.assertEqual(self.events.read_text().splitlines(), ["prepare", "assign", "release"])

    def test_success_binds_the_admitted_case_before_starting_its_watchdog(self):
        result = self.launch()
        self.assertEqual(result["case"], "vortex-" + "a" * 64)
        self.assertEqual(result["check_interval_seconds"], 1800)
        self.assertNotIn("wall_seconds", result)
        self.assertEqual(result["reasoning_budget_tokens"], 1024)
        self.assertEqual(result["output_cap"], 16384)
        self.assertEqual(self.events.read_text().splitlines(), ["prepare", "assign", "bind", "--user"])

    def test_confirmation_evidence_is_forwarded_unchanged(self):
        bounded.launch("opencode:1234567", "check", [], 0, 1024,
                       confirmed_unadmitted="journal: refused; no case")
        args=json.loads((Path(self.tmp.name)/"assign-args.json").read_text())
        self.assertEqual(args[args.index("--confirmed-unadmitted")+1],"journal: refused; no case")

    def test_malformed_admission_response_releases_only_unbound_profile(self):
        (Path(self.tmp.name)/"assign-reply").write_text('{"case": null, "dispatched": true}')
        with self.assertRaises(ValueError):self.launch()
        self.assertEqual(self.events.read_text().splitlines(),["prepare","assign","release"])

    def test_malformed_preparation_response_also_releases_owned_profile(self):
        (Path(self.tmp.name)/"prepare-reply").write_text('not JSON')
        with self.assertRaises(ValueError):self.launch()
        self.assertEqual(self.events.read_text().splitlines(),["prepare","release"])

    def test_cleanup_never_releases_another_owner_or_a_bound_profile(self):
        source=bounded.RELEASE_PROFILE.replace("__OWNER__","mine")
        probe='''
key = {:trailblazer, :bounded_smoke_profile}
for profile <- [%{owner_ref: "mine", case: nil}, %{owner_ref: "other", case: nil}, %{owner_ref: "mine", case: "admitted"}] do
  :persistent_term.put(key, profile)
  Code.eval_string(hd(System.argv()))
  expected = if profile == %{owner_ref: "mine", case: nil}, do: nil, else: profile
  unless :persistent_term.get(key, nil) == expected, do: raise("wrong profile released")
end
'''
        subprocess.run(["elixir","-e",probe,source],check=True,capture_output=True,text=True)

    def test_failure_after_admission_does_not_release_the_profile(self):
        self.fail_file.write_text("bind")
        with self.assertRaises(subprocess.CalledProcessError):self.launch()
        self.assertEqual(self.events.read_text().splitlines(),["prepare","assign","bind"])

    def test_thinking_budget_cannot_consume_the_entire_reply(self):
        for budget in [-1, True]:
            with self.assertRaises(ValueError):
                bounded.launch("opencode:1234567", "check", [], 0, budget)
        self.assertFalse(self.events.exists())

    def test_configured_output_budget_allows_a_larger_explicit_thinking_budget(self):
        result = bounded.launch("opencode:1234567", "check", ["a.ts"], 0, 8192)
        self.assertEqual(result["output_cap"], 16384)
        self.assertEqual(result["reasoning_budget_tokens"], 8192)

    def test_replay_flag_is_forwarded_and_invalid_sources_cannot_prepare(self):
        with self.assertRaises(ValueError):
            bounded.launch("opencode:1234567", "check", [], 0, 1024, "../invalid")
        self.assertFalse(self.events.exists())
        bounded.launch("opencode:1234567", "check", [], 0, 1024, "source-case")
        args=json.loads((Path(self.tmp.name)/"assign-args.json").read_text())
        self.assertEqual(args[args.index("--replay-reply-from")+1], "source-case")

    def test_worktree_is_forwarded_and_bound_and_bad_paths_cannot_prepare(self):
        for bad in ["relative/path", str(Path(self.tmp.name)/"missing")]:
            with self.assertRaises(ValueError):
                bounded.launch("opencode:1234567", "check", [], 0, 1024, None, bad)
        self.assertFalse(self.events.exists())
        tree = Path(self.tmp.name)/"tree"; tree.mkdir()
        bounded.launch("opencode:1234567", "check", [], 0, 1024, None, str(tree))
        args=json.loads((Path(self.tmp.name)/"assign-args.json").read_text())
        self.assertEqual(args[args.index("--worktree")+1], str(tree.resolve()))
        self.assertIn("Base.decode64!", bounded.BIND)

    def test_hostile_worktree_path_stays_data_in_the_bind_program(self):
        hostile = '/tmp/a"b\\c#{System.halt(7)}d'
        code = bounded.bind_program("vortex-" + "a" * 64, "f" * 32, 0, 1024, None, hostile)
        self.assertNotIn(hostile, code)
        root = Path(self.tmp.name)
        (root/"bind.exs").write_text(code)
        # It parses, and the decoded literal is exactly the path: no interpolation runs.
        probe = ('{:ok, ast} = Code.string_to_quoted(File.read!(hd(System.argv())));'
                 ' {_, [v]} = Macro.prewalk(ast, [], fn {{:., _, [{:__aliases__, _, [:Base]}, :decode64!]}, _, [s]} = n, _ -> {n, [Base.decode64!(s)]}; n, acc -> {n, acc} end);'
                 ' IO.write(v)')
        out = subprocess.run(["elixir", "-e", probe, str(root/"bind.exs")], check=True, capture_output=True, text=True)
        self.assertEqual(out.stdout, hostile)

    def test_rpc_programs_parse_before_any_live_operation(self):
        root = Path(self.tmp.name)
        paths = []
        for name, source in (("prepare", bounded.PREPARE), ("bind", bounded.BIND)):
            path = root / (name + ".exs")
            path.write_text(source)
            paths.append(str(path))
        subprocess.run(["elixir", "-e", "Enum.each(System.argv(), fn p -> p |> File.read!() |> Code.string_to_quoted!() end)", *paths],
                       check=True, capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()
