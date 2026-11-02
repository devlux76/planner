# Planner and Trailblazer operations

Planner owns the plan, execution supervision and verified outcome. Admission is
a handoff checkpoint, not task completion. Before dispatch, resolve the starting
code, ordered changes, interfaces and acceptance assertions. During execution,
check for meaningful progress and drift, and keep evidence and blockers on the
issue. After verification, plan the next dependency; a completed child cannot
complete a parent with unmet requirements. The CLI transports plans, the brain
selects work, and the companion supervises execution; the coordinating agent
must close any planning or supervision gap between those components.

Assignment is explicit: `planner assign <repo:bug> trailblazer --check '<check>'
[--file path] [--deadline-seconds 14400]`. Use a current concrete-repository card,
not a shared tracker issue or a stale mailbox request. The local configuration
and Trailblazer's peer policy must both admit that repository/check pair.

The CLI returns an assignment and case ID after admission. It leaves no Python
daemon. Elixir durably associates the card with the case before accepting it.
The planner companion and verification task supervisor form one OTP restart
group; a companion crash terminates its old verification tasks, then restores
durable work. Model execution itself is never replayed by this recovery.

Check actual state at a task boundary or a real notice:

```sh
planner --actor trailblazer resume
planner show <repo:bug>
trailblazer case <case-id>
systemctl --user status trailblazer vortex-codex --no-pager
```

`done` means an independently checked candidate commit, with command/output
evidence on the issue. It does not mean merged or deployed. Review the candidate
with `git show <commit>` before integrating it. No automatic merge/push exists.

The result backstop defaults to four hours. Verification and planner mirrors
also have bounded process-group checks. Backstop expiry blocks for investigation;
it does not cancel a potentially running case or retry a model. Failed mirrors
remain durable and are retried once on companion restart. Repeating the same
`done`/`block` repairs the mirror without duplicating its recorded evidence.

If a card is blocked, inspect its case and evidence first. Confirm that the old
case has ended before `planner --actor trailblazer release <ref> '<reason>'`,
then assign explicitly for a fresh request. Unknown admission is not permission
to retry. A producer interrupted before admission may require reconciliation;
the complete assignment lease/generation protocol remains shared:40dbd63.

Restart the Trailblazer service only when its active coding case is finished;
a restart during model work fails the interrupted case rather than replaying it.
For an ordinary planner mirror outage, fix the CLI problem, then restart the
companion/service to repair the pending durable mirror. Keep quota-held paid
agent wakes held; no periodic paid-model check-in is needed by this path.

Current limits: only explicitly admitted repository/check pairs can run;
Trailblazer self-repair is forbidden. General frontier-returned fixes and
automatic candidate integration remain separate work (trailblazer:a3339f5 and
trailblazer:1beebca). Those are not prerequisites for producing a checked planner
candidate, but they prevent claiming unattended repository integration.


Verified installation (2026-10-25): planner source 2bc587c and Trailblazer
1c86b5f. Full Elixir suite: 634 passed (4 live/integration tests excluded);
installed planner: 21 passed. Live OTP crash recovery terminated old BEAM
and OS verification workers. A hermetic BEAM-to-real-CLI smoke recovered a
failed mirror without duplicate evidence or leftover verification worktrees.
The earlier local coding trial produced a checked candidate; a second full
coding run was intentionally avoided after the supervision correction.
