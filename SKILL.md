---
name: planner
description: Plan and track local AI work with the planner command over git-bug. Use for task selection, assignments, kanban status, claims, checkpoints, blockers, and resuming after compaction.
---

# Planner

Planner owns planning and supervision through verified completion. Its job is to
turn the operator's goal into executable steps, guide the worker, detect drift
and blockers, and validate the result. The CLI and automatic selector are tools
for that responsibility; sending an assignment does not discharge it.

For each task:
1. Ground the plan in available code, resolve interfaces and dependencies, and
   define observable acceptance checks. Validate the check baseline in the actual
   provisioned worktree before spending model time. Distinguish expected bug
   failures from missing dependencies or other setup failures; repair setup first.
   A plan marker or restated requirements alone is insufficient. Supply the plan directly or use an available research
   route; expose missing planning capability instead of silently skipping it.
2. Assign one bounded step with the context and tools the worker actually has.
3. Supervise the recorded case and checkpoints. Acknowledged or running is not
   evidence of progress. Investigate repeated exploration, unchanged stages,
   admission uncertainty and drift; record the cause and revise the plan before
   considering another attempt. Reconcile the existing worker first.
4. Verify the exact candidate independently against the acceptance checks,
   record evidence and remaining work, then plan the next dependent step. Keep
   the parent incomplete until every required behavior is verified.

Prefer OTP supervision and event-driven checks. Use the operator's requested
check interval when scheduled supervision is authorized, stay quiet during
normal progress, and reserve expensive coordinator work for planning, diagnosis
and verification. Do not substitute frequent model polling for supervision.

Use `planner` from any directory. It returns compact JSON and uses the repositories listed in `~/.config/bug-watch/repos`. Board and tracking commands call no model; explicit `assign` starts Trailblazer's local coding worker. References are `vortex:6ee260f`, `opencode:b7fe55b`, or `shared:40dbd63`. Use a stable actor name (`glm`, `codex`, `trailblazer`), never a session ID.

```sh
planner --actor glm resume
planner board --repo vortex --column todo --limit 8
planner show vortex:6ee260f
planner --actor glm start vortex:6ee260f --plan 'Shorten wake envelopes; verify room and sender boundaries; measure size.'
planner --actor glm note vortex:6ee260f 'Intent: change the notice text; no mail or service state changes.'
planner --actor glm note vortex:6ee260f 'Result: focused tests passed; next: size comparison.'
planner --actor glm block vortex:6ee260f 'Provider quota exhausted; no retries until operator resumes.'
planner --actor glm start vortex:6ee260f --plan 'Resume from the recorded checkpoint.'
planner --actor glm done vortex:6ee260f --evidence 'Actual commands, results, commit, and remaining limits.'
planner --actor glm release vortex:6ee260f 'Explicit handoff reason; next action.'
planner add vortex --title 'Concrete task title' --plan 'Outcome and acceptance check' --priority p2
```

For well-specified coding work, use `planner assign <repo:bug> trailblazer
--check '<project check>' [--file relative/path]`. Pick a current, ready card
with a bounded requested change. Before assignment, record an `Implementation plan:` on the card (body or a
checkpoint). Name the starting code actually present, ordered changes with exact
files/interfaces, and test assertions. Resolve external APIs before dispatch;
the coder has read/search tools, not git or shell access. Split broad tasks.
`assign` transports the latest explicit plan and refuses a card without one; it
does not generate a plan. The automatic brain selects work; its research route
must produce implementation plans before coding.

Set `--read-rounds N` (0..6, default6) to bound read/search exchanges before
forced native edits. For a fully resolved plan that needs no further code
discovery, use zero so the first coder call must submit edits. This is separate
from output and wall-clock bounds. A repeated assignment cannot change its
budget; confirm termination and explicitly reconcile before any fresh run.

For this operator's bounded local trials, use
`python3 scripts/bounded_assignment.py REF --check CHECK --file PATH --read-rounds 0 --reasoning-tokens 1024`
from this skill directory. It checks preparation before admission, binds the
exact returned case, disables its result deadline with `Companion.observe`,
then starts a cleanup-only observer. Thirty minutes is the coordinator's check
interval, not a runtime cap: let healthy slow work complete. The observer never
stops a worker and restores the owned token profile only after completion.
It retains the configured total output budget and records it on admission;
there is no smaller trial-only override. The explicit thinking budget
reserves final-answer space within that total; high reasoning effort, model and
samplers are unchanged. Direct `assign --reasoning-tokens N` also transports
this optional task budget; omission keeps existing behavior. A reasoning-only
token-limit failure stops without an unchanged automatic retry. Any failed or
uncertain stage stops the launcher; inspect its recorded
assignment and profile before retrying. Keep supervising until cap cleanup and
independent verification are confirmed.

If a completed failed case contains an unapplied but schema-valid JSON reply,
explicit recovery can use `--replay-reply-from CASE` on `assign` or the checked
launcher. This starts a new verification-only case, never revives the source or
regenerates code. Same peer/repository/check/base and complete reply are checked;
the unchanged artifact still needs project checks, fresh review and independent
verification. A failed recovery retains the artifact and does not retry coding.

Assignment starts the local worker through
its existing VORTEX resource gate; adding an owner label alone does not launch
work. Shared issues need a concrete repository part card first.

The actor is `trailblazer`. The Python client claims the card, sends its current
context and optional deadline, records acceptance/case ID, and exits. It starts
no watcher. Trailblazer's Elixir companion owns execution supervision, planner
updates, independent verification, deadlines and restart recovery under OTP.
It checks the exact candidate commit in a separate worktree before `done`; a
candidate is never merged or pushed automatically. Repeating `assign` returns
the same assignment without dispatching again. Use `--deadline-seconds N` to
change Elixir's default four-hour result backstop; expiry blocks without
retrying or cancelling a possibly running case. The client only has a bounded
transport admission timeout, which blocks an unconfirmed request.
After confirming the old case has stopped, explicitly `release` its card as
actor `trailblazer`, then `assign` again for a fresh attempt; earlier assignment
identities remain in the local record. Repeating `assign` without release never
retries a blocked job, and a released card cannot be reassigned while its prior
case is still open. An unconfirmed admission needs explicit reconciliation.
Only repository/check pairs admitted by the local dispatch configuration may
run; Trailblazer self-repair remains forbidden.

Start with `resume` after compaction. Read one card before acting. Use `git -C <repo> bug bug show <id>` if the bounded card omits needed detail. Work on one active card per actor; block or release it before taking another. A blocker retains task ownership but frees the actor for other work. Select ready work within the operator's authorized scope; priority alone is not permission to revive parked work.

Record intent before consequential effects and the observed result afterwards. Include what remains so another session can continue. `done` records verified work; it does **not** close the issue or grant permission to merge, deploy or spend money. Review/closure is separate and need not wait for an unavailable frontier agent.

Git-bug is the durable plan and progress record. Local SQLite claims serialize workers using this helper and survive compaction. Other tools can edit labels, so claims do not enforce all external workers. Claims never expire or automatically transfer. A stale owner requires explicit reconciliation; use its stable actor to release only after confirming it stopped. This helper is not the full lease/generation/reconciliation system tracked by `shared:40dbd63`.

On a write error, inspect `resume` and the issue before repeating a side effect. `planner --actor glm sync <ref>` repairs an interrupted issue mirror without changing the claim or duplicating its comment. Never infer completion from a mail acknowledgement. Keep session IDs, credentials and private runtime paths out of issue text. Check the board on task boundaries or actual notices; do not run a model polling loop. Automatic VORTEX wakes remain quota-held until the operator resumes them.

For service checks, candidate review and restart recovery, read
[the operations handoff](references/operations.md).
