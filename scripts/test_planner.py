"""Behavioral checks against real temporary git-bug repositories."""
import json
from pathlib import Path
import subprocess
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

import trailblazer_assignment as assignment

CLI = Path(__file__).with_name("planner.py")


class PlannerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root/"repo"
        self.repo.mkdir()
        self.run_git("init", "-q")
        self.run_git("config", "user.name", "fixture")
        self.run_git("config", "user.email", "fixture@example.invalid")
        self.run_git("bug", "user", "new", "-n", "fixture", "-e", "fixture@example.invalid", "--non-interactive")
        self.repos = self.root/"repos"
        self.repos.write_text(str(self.repo)+"\n")
        self.base = [sys.executable, str(CLI), "--repos-file", str(self.repos), "--state-dir", str(self.root/"state")]

    def tearDown(self):
        self.tmp.cleanup()

    def run_git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True, capture_output=True, text=True).stdout

    def call(self, *args, actor="glm", ok=True):
        p = subprocess.run(self.base+["--actor", actor, *args], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0 if ok else 1, p.stdout+p.stderr)
        return json.loads(p.stdout if ok else p.stderr)

    def card(self, title="fixture task"):
        return self.call("add", "repo", "--title", title, "--plan", "Implementation plan: 1. Change value to the requested marker; 2. Verify the marker with the admitted check.")["ref"]

    def test_workflow_survives_new_process_and_separates_completion_from_closure(self):
        ref = self.card()
        self.call("start", ref, "--plan", "one bounded task")
        self.call("note", ref, "intent: write marker")
        self.call("note", ref, "result: marker exists; next: verify")
        self.call("block", ref, "quota; wait for operator")
        resumed = self.call("resume")["cards"][0]
        self.assertEqual(resumed["state"], "blocked")
        self.assertIn("marker exists", resumed["notes"][-2]["text"])
        self.call("start", ref, "--plan", "verify marker")
        self.call("done", ref, "--evidence", "marker inspected; focused checks pass")
        self.assertEqual(self.call("show", ref)["column"], "done")
        raw = json.loads(self.run_git("bug", "bug", "show", ref.split(":")[1], "-f", "json"))
        self.assertEqual(raw["status"], "open")
        self.assertEqual(self.call("resume")["cards"], [])

    def test_two_claimants_have_exactly_one_winner(self):
        ref = self.card()
        workers = [subprocess.Popen(self.base+["--actor", actor, "start", ref, "--plan", "claim"],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                   for actor in ("worker-a", "worker-b")]
        results = [p.communicate() for p in workers]
        self.assertEqual(sorted(p.returncode for p in workers), [0, 1], results)
        self.assertIn("already owned", "".join(err for _, err in results))

    def test_serial_work_and_explicit_release(self):
        first, second = self.card("first"), self.card("second")
        self.call("start", first, "--plan", "first")
        self.assertIn("active work", self.call("start", second, "--plan", "second", ok=False)["error"])
        self.call("release", first, "handoff: remaining check")
        self.call("start", second, "--plan", "second")
        self.assertEqual(self.call("show", first)["column"], "todo")

    def test_sync_repairs_labels_without_duplicate_comment(self):
        ref = self.card()
        self.call("start", ref, "--plan", "claim")
        before = self.call("show", ref)
        self.run_git("bug", "bug", "label", "rm", ref.split(":")[1], "status:doing")
        self.call("sync", ref)
        after = self.call("show", ref)
        self.assertEqual(after["column"], "doing")
        self.assertEqual(before["recent"], after["recent"])

    def test_repeated_done_repairs_a_durable_mirror_without_duplicate_evidence(self):
        ref=self.card()
        self.call("start",ref,"--plan","bounded task",actor="trailblazer")
        self.call("done",ref,"--evidence","verified candidate",actor="trailblazer")
        self.run_git("bug","bug","label","rm",ref.split(":")[1],"status:done")
        before=self.call("show",ref)
        self.call("done",ref,"--evidence","verified candidate",actor="trailblazer")
        after=self.call("show",ref)
        self.assertEqual(after["column"],"done")
        self.assertEqual(before["recent"],after["recent"])

    def test_completion_requires_nonempty_evidence_and_current_actor(self):
        ref = self.card()
        self.call("start", ref, "--plan", "claim")
        self.call("done", ref, "--evidence", " ", ok=False)
        self.call("done", ref, "--evidence", "claimed result", actor="other", ok=False)
        self.assertEqual(self.call("show", ref)["column"], "doing")

    def test_board_is_bounded_and_closed_work_cannot_restart(self):
        ref = self.card()
        self.card("another")
        board = self.call("board", "--limit", "1")
        self.assertEqual(len(board["cards"]), 1)
        self.assertEqual(board["more"], 1)
        self.run_git("bug", "bug", "status", "close", ref.split(":")[1])
        self.assertIn("closed issue", self.call("start", ref, "--plan", "revive", ok=False)["error"])

    def test_unlabelled_bug_and_empty_store_are_supported(self):
        self.assertEqual(self.call("board")["cards"], [])
        ref = self.card()
        for label in ("status:todo", "kind:task", "priority:p2"):
            self.run_git("bug", "bug", "label", "rm", ref.split(":")[1], label)
        self.assertEqual(self.call("board")["cards"][0]["column"], "todo")
        self.call("start", ref, "--plan", "labelled on claim")

    def dispatch_fixture(self, ref):
        (self.repo/"value").write_text("base\n")
        self.run_git("add","value")
        self.run_git("commit","-qm","Fixture bug:"+ref.split(":")[1])
        base=self.run_git("rev-parse","HEAD").strip()
        fake=self.root/"dispatch.py"
        fake.write_text('''import json,pathlib,sys,time
root=pathlib.Path(__file__).parent
kind,op,*args=sys.argv[1:]
if kind=='case':
    if '--follow' in args:
        (root/'followed').touch(); sys.exit(91)
    status=(root/'case-status').read_text() if (root/'case-status').exists() else 'failed'
    print(json.dumps({'status':status})); sys.exit(0)
if op=='send':
    message=json.loads(args[args.index('--text')+1].split('\\n',1)[1])
    if message['type']=='task':
        with (root/'sent').open('a') as out: out.write(json.dumps(message)+'\\n')
        (root/'task.json').write_text(json.dumps(message))
    print(json.dumps({'sent':True}))
elif op in ('read','wait'):
    if op=='wait' and (root/'hang-admission').exists(): time.sleep(100)
    events=[]
    cursor=len((root/'sent').read_text().splitlines()) if (root/'sent').exists() else 0
    after=int(args[args.index('--after')+1])
    if (root/'task.json').exists() and cursor>after:
        task=json.loads((root/'task.json').read_text())
        kind='rejected' if (root/'reject').exists() else 'accepted'
        message={'protocol':'trailblazer/1','type':kind,'id':'reply-'+str(cursor),
                 'request_id':task['request_id'],'payload':{'case':'fixture-case','state':'waiting_resource'}}
        events=[{'cursor':cursor,'kind':'message','peer':'fixture-trailblazer',
                 'body':'From Trailblazer, not typed by the operator:\\n'+json.dumps(message)}]
    print(json.dumps({'events':events,'cursor':cursor}))
''')
        self.config=self.root/"dispatch.json"
        self.config.write_text(json.dumps({"peer":"fixture-trailblazer",
            "vortex_command":[sys.executable,str(fake),"vortex"],
            "case_command":[sys.executable,str(fake),"case"],
            "vortex_dir":str(self.root/"vortex"),
            "repos":{str(self.repo):["test -f value"]}}))
        return base

    def assign(self, ref, ok=True, extra=()):
        return self.call("assign",ref,"trailblazer","--check","test -f value",
                         "--dispatch-config",str(self.config),*extra,actor="codex",ok=ok)

    def test_assignment_refuses_requirements_without_implementation_plan(self):
        ref=self.call("add","repo","--title","unplanned task","--plan","Make fallback work; checks must pass")["ref"]
        self.dispatch_fixture(ref)
        self.assertIn("implementation plan",self.assign(ref,ok=False)["error"].lower())
        self.assertFalse((self.root/"sent").exists())
        self.assertIsNone(self.call("show",ref)["claim"])

    def test_assignment_preserves_plan_after_newer_checkpoints(self):
        ref=self.card()
        self.dispatch_fixture(ref)
        self.call("start",ref,"--plan","planning")
        self.call("note",ref,"Implementation plan:\n1. Update value;\n2. Check its contents.")
        for n in range(4): self.call("note",ref,"checkpoint "+str(n))
        self.call("release",ref,"ready for implementation")
        self.assign(ref)
        task=json.loads((self.root/"sent").read_text().splitlines()[0])
        self.assertIn("1. Update value", "\n".join(task["payload"]["design"]))

    def test_assignment_exits_after_admission_and_delegates_supervision_to_elixir(self):
        ref=self.card()
        self.dispatch_fixture(ref)
        result=self.assign(ref)
        self.assertEqual(result["case"],"fixture-case")
        task=json.loads((self.root/"sent").read_text().splitlines()[0])
        self.assertEqual(task["payload"]["planner"],{"ref":ref,"deadline_seconds":14400})
        with sqlite3.connect(self.root/"state/board.sqlite3") as db:
            job=json.loads(db.execute("SELECT data FROM assignments WHERE ref=?",(ref,)).fetchone()[0])
        self.assertNotIn("pid",job)
        self.assertEqual(self.call("show",ref)["column"],"doing")
        self.assertFalse((self.root/"followed").exists())

    def side_worktree(self, admit=True):
        tree=self.root/"side"
        self.run_git("worktree","add","-q","-b","side",str(tree))
        subprocess.run(["git","-C",str(tree),"commit","-q","--allow-empty","-m","Side work"],check=True)
        head=subprocess.run(["git","-C",str(tree),"rev-parse","HEAD"],check=True,capture_output=True,text=True).stdout.strip()
        if admit:
            config=json.loads(self.config.read_text())
            config["repos"][str(tree.resolve())]=["test -f value"]
            self.config.write_text(json.dumps(config))
        return tree,head

    def test_assignment_targets_a_registered_worktree_and_records_its_base(self):
        ref=self.card()
        self.dispatch_fixture(ref)
        tree,head=self.side_worktree()
        result=self.assign(ref,extra=("--worktree",str(tree)))
        self.assertEqual(result["case"],"fixture-case")
        task=json.loads((self.root/"sent").read_text().splitlines()[0])
        self.assertEqual(task["payload"]["repo"],str(tree.resolve()))
        notes=self.call("show",ref)["recent"]
        self.assertTrue(any(head in n and "case base" in n for n in notes),notes)
        # Same card, different target: refused as different inputs, nothing re-sent.
        self.assertIn("different inputs",self.assign(ref,ok=False)["error"])
        self.assertEqual(len((self.root/"sent").read_text().splitlines()),1)

    def test_assignment_refuses_an_unregistered_worktree_or_the_repository_itself(self):
        ref=self.card()
        self.dispatch_fixture(ref)
        stray=self.root/"stray"; stray.mkdir()
        self.assertIn("not a registered worktree",self.assign(ref,ok=False,extra=("--worktree",str(stray)))["error"])
        self.assertIn("card repository itself",self.assign(ref,ok=False,extra=("--worktree",str(self.repo)))["error"])
        self.assertFalse((self.root/"sent").exists())

    def test_assignment_worktree_still_needs_its_own_admission(self):
        ref=self.card()
        self.dispatch_fixture(ref)
        tree,_=self.side_worktree(admit=False)
        self.assertIn("not admitted",self.assign(ref,ok=False,extra=("--worktree",str(tree)))["error"])
        self.assertFalse((self.root/"sent").exists())

    def test_assignment_is_idempotent_before_and_after_elixir_completion(self):
        ref=self.card()
        self.dispatch_fixture(ref)
        first=self.assign(ref)
        self.assertEqual(self.assign(ref)["assignment"],first["assignment"])
        self.call("done",ref,"--evidence","Elixir verified candidate",actor="trailblazer")
        self.assertEqual(self.assign(ref)["assignment"],first["assignment"])
        self.assertEqual(len((self.root/"sent").read_text().splitlines()),1)

    def test_explicit_read_budget_reaches_admission_and_cannot_change_on_repeat(self):
        ref=self.card()
        self.dispatch_fixture(ref)
        first=self.assign(ref,extra=("--read-rounds","0","--reasoning-tokens","1024"))
        task=json.loads((self.root/"sent").read_text().splitlines()[0])
        self.assertEqual(task["payload"]["read_rounds"],0)
        self.assertEqual(task["payload"]["reasoning_budget_tokens"],1024)
        again=self.assign(ref,extra=("--read-rounds","0","--reasoning-tokens","1024"))
        self.assertEqual(again["assignment"],first["assignment"])
        self.assertIn("different inputs",self.assign(ref,ok=False,extra=("--read-rounds","1"))["error"])
        self.assertIn("different inputs",self.assign(ref,ok=False,extra=("--read-rounds","0","--reasoning-tokens","512"))["error"])
        self.assertEqual(len((self.root/"sent").read_text().splitlines()),1)

    def test_invalid_read_budget_does_not_claim_or_send(self):
        ref=self.card()
        self.dispatch_fixture(ref)
        for invalid in ("-1","7"):
            self.assertIn("read_rounds",self.assign(ref,ok=False,extra=("--read-rounds",invalid))["error"])
        self.assertFalse((self.root/"sent").exists())
        self.assertIsNone(self.call("show",ref)["claim"])

    def test_invalid_reasoning_budget_does_not_claim_or_send(self):
        ref=self.card()
        self.dispatch_fixture(ref)
        self.assertIn("reasoning",self.assign(ref,ok=False,extra=("--reasoning-tokens","-1"))["error"])
        self.assertFalse((self.root/"sent").exists())
        self.assertIsNone(self.call("show",ref)["claim"])

    def test_recovery_source_is_transported_and_cannot_change_on_repeat(self):
        ref=self.card()
        self.dispatch_fixture(ref)
        self.assign(ref,extra=("--replay-reply-from","fixture-source"))
        task=json.loads((self.root/"sent").read_text().splitlines()[0])
        self.assertEqual(task["payload"]["replay_reply_from"],"fixture-source")
        self.assertIn("different inputs",self.assign(ref,ok=False,extra=("--replay-reply-from","other-source"))["error"])
        self.assertEqual(len((self.root/"sent").read_text().splitlines()),1)

    def test_assignment_cannot_steal_another_actors_card(self):
        ref=self.card()
        self.dispatch_fixture(ref)
        self.call("start",ref,"--plan","existing work",actor="glm")
        self.assertIn("owned",self.assign(ref,ok=False)["error"])
        self.assertFalse((self.root/"sent").exists())

    def test_assignment_refuses_trailblazer_self_repair_after_history_rewrite(self):
        ref=self.card()
        self.dispatch_fixture(ref)
        (self.repo/"mix.exs").write_text('def project, do: [app: :trailblazer]\n')
        self.run_git("add","mix.exs")
        self.run_git("commit","-qm","Guard fixture bug:"+ref.split(":")[1])
        self.assertIn("self",self.assign(ref,ok=False)["error"])
        self.assertFalse((self.root/"sent").exists())

    def test_concurrent_assignment_returns_same_assignment_with_one_task(self):
        # Adapted from the local coding model's verified candidate d77b848.
        ref=self.card()
        base=self.dispatch_fixture(ref)
        cmd=self.base+["--actor","codex","assign",ref,"trailblazer","--check","test -f value",
                       "--dispatch-config",str(self.config)]
        workers=[subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for _ in range(2)]
        results=[p.communicate() for p in workers]
        self.assertEqual([p.returncode for p in workers],[0,0],results)
        assignments=[json.loads(out) for out,_ in results]
        self.assertEqual(assignments[0]["assignment"],assignments[1]["assignment"])
        self.assertEqual(self.call("show",ref)["column"],"doing")
        self.assertEqual(len((self.root/"sent").read_text().splitlines()),1)
        self.assertEqual(self.run_git("rev-parse","HEAD").strip(),base)
        self.assertEqual((self.repo/"value").read_text(),"base\n")

    def test_rejected_admission_blocks_without_automatic_retry(self):
        ref=self.card()
        self.dispatch_fixture(ref)
        (self.root/"reject").touch()
        self.assertIn("rejected",self.assign(ref,ok=False)["error"])
        self.assertEqual(self.call("show",ref)["column"],"blocked")
        self.assign(ref)
        self.assertEqual(len((self.root/"sent").read_text().splitlines()),1)

    def rejected_and_released(self):
        ref=self.card()
        self.dispatch_fixture(ref)
        (self.root/"reject").touch()
        self.assign(ref,ok=False)
        self.call("release",ref,"confirmed refusal",actor="trailblazer")
        (self.root/"reject").unlink()
        return ref

    def test_confirmed_unadmitted_preserves_evidence_and_old_attempt(self):
        ref=self.rejected_and_released()
        old=json.loads((self.root/"task.json").read_text())["request_id"]
        result=self.assign(ref,extra=("--confirmed-unadmitted","journal: unauthorized_task; no case"))
        self.assertNotEqual(result["assignment"],old)
        with sqlite3.connect(self.root/"state"/"board.sqlite3") as db:
            job=json.loads(db.execute("SELECT data FROM assignments WHERE ref=?",(ref,)).fetchone()[0])
        self.assertEqual(job["previous"][-1]["id"],old)
        self.assertEqual(job["previous"][-1]["state"],"unadmitted")
        self.assertEqual(job["previous"][-1]["evidence"],"journal: unauthorized_task; no case")

    def test_uncertain_retry_requires_nonempty_evidence(self):
        ref=self.rejected_and_released()
        self.assertIn("uncertain",self.assign(ref,ok=False)["error"])
        self.assertIn("evidence",self.assign(ref,ok=False,extra=("--confirmed-unadmitted","  "))["error"])
        self.assertEqual(len((self.root/"sent").read_text().splitlines()),1)

    def test_confirmed_unadmitted_refuses_admitted_case_or_unreleased_card(self):
        ref=self.card();self.dispatch_fixture(ref);self.assign(ref)
        self.assertIn("released",self.assign(ref,ok=False,extra=("--confirmed-unadmitted","evidence"))["error"])
        self.call("block",ref,"terminal",actor="trailblazer")
        self.call("release",ref,"deliberate retry",actor="trailblazer")
        self.assertIn("without a case",self.assign(ref,ok=False,extra=("--confirmed-unadmitted","evidence"))["error"])
        self.assertEqual(len((self.root/"sent").read_text().splitlines()),1)

    def test_confirmed_unadmitted_requires_a_previous_attempt(self):
        ref=self.card();self.dispatch_fixture(ref)
        self.assertIn("previous",self.assign(ref,ok=False,extra=("--confirmed-unadmitted","evidence"))["error"])
        self.assertFalse((self.root/"sent").exists())

    def test_no_admission_blocks_at_client_timeout_without_leaving_a_watcher(self):
        ref=self.card()
        self.dispatch_fixture(ref)
        config=json.loads(self.config.read_text())
        config["admission_timeout_seconds"]=0.5
        self.config.write_text(json.dumps(config))
        (self.root/"hang-admission").touch()
        self.assertIn("client timeout",self.assign(ref,ok=False)["error"])
        self.assertEqual(self.call("show",ref)["column"],"blocked")

    def test_resume_does_not_treat_absence_of_a_python_pid_as_failure(self):
        ref=self.card()
        self.dispatch_fixture(ref)
        self.assign(ref)
        held=self.call("resume",actor="trailblazer")["cards"][0]
        self.assertEqual(held["state"],"doing")

    def test_released_closed_case_can_be_assigned_afresh(self):
        ref=self.card()
        self.dispatch_fixture(ref)
        first=self.assign(ref)
        self.call("block",ref,"Elixir closed failed",actor="trailblazer")
        self.call("release",ref,"case confirmed closed; deliberate retry",actor="trailblazer")
        second=self.assign(ref)
        self.assertNotEqual(first["assignment"],second["assignment"])
        self.assertEqual(len((self.root/"sent").read_text().splitlines()),2)

    def test_released_but_open_case_cannot_be_redispatched(self):
        ref=self.card()
        self.dispatch_fixture(ref)
        self.assign(ref)
        self.call("block",ref,"Elixir deadline; case still running",actor="trailblazer")
        self.call("release",ref,"attempted retry",actor="trailblazer")
        (self.root/"case-status").write_text("open")
        self.assertIn("not confirmed closed",self.assign(ref,ok=False)["error"])
        self.assertEqual(len((self.root/"sent").read_text().splitlines()),1)

    def test_closed_case_query_timeout_refuses_retry_with_clear_error(self):
        with patch.object(assignment.subprocess, "run", side_effect=subprocess.TimeoutExpired("case", 10)):
            with self.assertRaisesRegex(ValueError, "not confirmed closed"):
                assignment.confirm_closed({"case":"fixture-case"}, {})

    def test_elixir_deadline_is_passed_as_metadata_not_a_python_watch_timer(self):
        ref=self.card()
        self.dispatch_fixture(ref)
        self.assign(ref,extra=("--deadline-seconds","123"))
        task=json.loads((self.root/"sent").read_text().splitlines()[0])
        self.assertEqual(task["payload"]["planner"],{"ref":ref,"deadline_seconds":123})

    def test_shared_card_requires_a_repository_part_before_assignment(self):
        ref=self.card()
        self.dispatch_fixture(ref)
        moved=self.root/".bugs"
        self.repo.rename(moved)
        self.repo=moved
        self.repos.write_text(str(moved)+"\n")
        shared="shared:"+ref.split(":")[1]
        self.assertIn("concrete repository",self.assign(shared,ok=False)["error"])
        self.assertFalse((self.root/"sent").exists())


if __name__ == "__main__":
    unittest.main()
