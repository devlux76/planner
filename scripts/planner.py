#!/usr/bin/env python3
"""Local kanban over git-bug; explicit assignment uses Trailblazer's supervised service."""
import argparse
import contextlib
import fcntl
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import uuid

import trailblazer_assignment as assignment


def git(repo, *args):
    p = subprocess.run(["git", "-C", str(repo), "bug", *args], capture_output=True, text=True)
    if p.returncode:
        raise ValueError(p.stderr.strip() or p.stdout.strip() or "git-bug failed")
    return p.stdout.strip()


def repositories(file):
    result = {}
    for line in file.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        path = Path(line.strip()).expanduser().resolve()
        name = "shared" if path.name == ".bugs" else path.name
        if name in result:
            raise ValueError(f"duplicate repository name: {name}")
        result[name] = path
    return result


def column(bug):
    labels = bug["labels"] or []
    if bug["status"] == "closed" or "status:done" in labels:
        return "done"
    if "board:blocked" in labels:
        return "blocked"
    return "doing" if "status:doing" in labels else "todo"


def show(repo, bug):
    return json.loads(git(repo, "bug", "show", bug, "-f", "json"))


def labels(repo, bug, old, state, blocked=False):
    desired = {f"status:{state}"}
    if blocked:
        desired.add("board:blocked")
    present = {x for x in (old or []) if x.startswith("status:") or x == "board:blocked"}
    for label in sorted(present - desired):
        git(repo, "bug", "label", "rm", bug, label)
    for label in sorted(desired - present):
        git(repo, "bug", "label", "new", bug, label)


def mirror(repo, bug, card, claim):
    note = json.loads(claim["notes"])[-1]
    text = f'planner {note["action"]} ({claim["actor"]}) #{note["n"]}: {note["text"]}'
    if not any(c["message"] == text for c in card["comments"]):
        git(repo, "bug", "comment", "new", bug, "-m", text, "--non-interactive")
    state = claim["state"]
    labels(repo, bug, card["labels"], "doing" if state == "blocked" else state, state == "blocked")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--actor", default=os.environ.get("PLANNER_ACTOR", "glm"))
    p.add_argument("--repos-file", type=Path, default=Path.home()/".config/bug-watch/repos")
    p.add_argument("--state-dir", type=Path, default=Path.home()/".local/state/planner")
    sub = p.add_subparsers(dest="command", required=True)
    board = sub.add_parser("board")
    board.add_argument("--repo")
    board.add_argument("--column", choices=["todo", "doing", "blocked", "done"])
    board.add_argument("--limit", type=int, default=12)
    sub.add_parser("resume")
    assign = sub.add_parser("assign")
    assign.add_argument("ref")
    assign.add_argument("target", choices=["trailblazer"])
    assign.add_argument("--check", required=True)
    assign.add_argument("--file", action="append", default=[])
    assign.add_argument("--deadline-seconds", type=int)
    assign.add_argument("--read-rounds", type=int,
                        help="read/search exchanges before forced edits, 0..6 (default 6)")
    assign.add_argument("--reasoning-tokens", type=int,
                        help="explicit thinking budget; must leave room within the response cap")
    assign.add_argument("--replay-reply-from", help="recover a closed failed case reply without coding inference")
    assign.add_argument("--confirmed-unadmitted", metavar="EVIDENCE",
                        help="retire a released card's case-less previous assignment, with evidence that no case was admitted")
    assign.add_argument("--worktree", type=Path,
                        help="a registered git worktree of the card's repository to work in; its HEAD is the base")
    assign.add_argument("--dispatch-config", type=Path,
                        default=Path.home()/".config/planner/trailblazer.json")
    add = sub.add_parser("add")
    add.add_argument("repo")
    add.add_argument("--title", required=True)
    add.add_argument("--plan", required=True)
    add.add_argument("--priority", choices=["p0", "p1", "p2", "p3"], default="p2")
    for command in ["show", "start", "note", "block", "release", "done", "sync"]:
        action = sub.add_parser(command)
        action.add_argument("ref", help="repository:bug-id (shared for the cross-repo tracker)")
        if command == "start":
            action.add_argument("--plan", required=True)
        elif command == "done":
            action.add_argument("--evidence", required=True)
        elif command not in ("show", "sync"):
            action.add_argument("text", help="checkpoint, blocker or release reason")
    a = p.parse_args()
    if not 1 <= len(a.actor) <= 32 or not all(c.isalnum() or c in "_-" for c in a.actor):
        raise ValueError("actor must be a short name, not a session id")
    repos = repositories(a.repos_file)
    a.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (a.state_dir/"lock").open("a") as lock, contextlib.closing(sqlite3.connect(a.state_dir/"board.sqlite3")) as db:
        fcntl.flock(lock, fcntl.LOCK_EX)
        db.row_factory = sqlite3.Row
        db.execute("CREATE TABLE IF NOT EXISTS claims (ref TEXT PRIMARY KEY, actor TEXT, state TEXT, plan TEXT, notes TEXT)")
        db.execute("CREATE TABLE IF NOT EXISTS assignments (ref TEXT PRIMARY KEY, data TEXT NOT NULL)")
        claims = {r["ref"]: dict(r) for r in db.execute("SELECT * FROM claims")}
        if a.command == "resume":
            return {"actor": a.actor, "cards": [{"ref": r["ref"], "state": r["state"], "plan": r["plan"],
                    "notes": [n for n in json.loads(r["notes"]) if n["action"] != "start"][-3:]} for r in claims.values()
                    if r["actor"] == a.actor and r["state"] in ("doing", "blocked")]}
        if a.command == "board":
            if a.repo and a.repo not in repos:
                raise ValueError("unknown repository; use a name from the watched repositories")
            cards = []
            counts = {c: 0 for c in ("todo", "doing", "blocked", "done")}
            for name, repo in repos.items():
                if a.repo and name != a.repo:
                    continue
                for b in (json.loads(git(repo, "bug", "-f", "json")) or []):
                    col = column(b)
                    counts[col] += 1
                    if (a.column and col != a.column) or (not a.column and col == "done"):
                        continue
                    ref = f'{name}:{b["human_id"]}'
                    cards.append({"ref": ref, "column": col, "actor": claims.get(ref, {}).get("actor"),
                                  "priority": next((x[9:] for x in sorted(b["labels"] or []) if x.startswith("priority:")), "p2"),
                                  "title": b["title"][:140]})
            cards.sort(key=lambda c: ({"doing": 0, "blocked": 1, "todo": 2, "done": 3}[c["column"]], c["priority"], c["ref"]))
            limit = max(1, min(a.limit, 100))
            return {"counts": counts, "cards": cards[:limit], "more": max(0, len(cards)-limit)}
        if a.command == "add":
            if a.repo not in repos:
                raise ValueError("unknown repository")
            if not a.title.strip() or not a.plan.strip():
                raise ValueError("title and plan must not be empty")
            repo = repos[a.repo]
            result = git(repo, "bug", "new", "-t", a.title, "-m", a.plan, "--non-interactive")
            ref = result.split()[0]
            git(repo, "bug", "label", "new", ref, "status:todo", "kind:task", "priority:"+a.priority)
            return {"ref": a.repo+":"+ref, "column": "todo"}
        name, sep, bug = a.ref.partition(":")
        if not sep or name not in repos or not bug:
            raise ValueError("expected known-repository:bug-id")
        repo = repos[name]
        b = show(repo, bug)
        ref = name+":"+b["human_id"]
        claim = claims.get(ref)
        if a.command == "show":
            comments = b["comments"]
            return {"ref": ref, "column": column(b), "title": b["title"], "labels": b["labels"],
                    "body": comments[0]["message"][:1800] if comments else "",
                    "recent": [c["message"][:900] for c in comments[1:][-3:]],
                    "claim": {**claim, "notes": json.loads(claim["notes"])[-3:]} if claim else None}
        if b["status"] == "closed":
            raise ValueError("closed issue; do not revive old work")
        if a.command == "assign":
            if a.read_rounds is not None and not 0 <= a.read_rounds <= 6:
                raise ValueError("read_rounds must be an integer from 0 to 6")
            if a.reasoning_tokens is not None and a.reasoning_tokens < 0:
                raise ValueError("reasoning budget must be nonnegative")
            if a.replay_reply_from is not None and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:._-]{0,127}",a.replay_reply_from):
                raise ValueError("invalid replay reply case")
            target = assignment.worktree_target(repo, a.worktree) if a.worktree is not None else repo
            previous = db.execute("SELECT data FROM assignments WHERE ref=?", (ref,)).fetchone()
            history = []
            if previous:
                job = json.loads(previous[0])
                if claim and claim["state"] == "todo":
                    record = {key: job[key] for key in ("id", "state", "case", "commit", "reason") if key in job}
                    if a.confirmed_unadmitted is not None:
                        # A refused or timed-out request never got a case. Only an explicit,
                        # evidenced confirmation that nothing was admitted retires it.
                        if job.get("case"):
                            raise ValueError("--confirmed-unadmitted applies only to an assignment without a case")
                        if not a.confirmed_unadmitted.strip():
                            raise ValueError("--confirmed-unadmitted needs the evidence that no case was admitted")
                        record |= {"state": "unadmitted", "evidence": a.confirmed_unadmitted.strip()}
                    else:
                        assignment.confirm_closed(job, assignment.configuration(a.dispatch_config))
                    history = job.get("previous", [])+[record]
                elif a.confirmed_unadmitted is not None:
                    raise ValueError("--confirmed-unadmitted needs a released card whose last assignment has no case")
                else:
                    if job["repo"] != str(target) or job["check"] != a.check or job["files"] != a.file or job.get("read_rounds") != a.read_rounds or job.get("reasoning_budget_tokens") != a.reasoning_tokens or job.get("replay_reply_from") != a.replay_reply_from:
                        raise ValueError("assignment already exists with different inputs; reconcile it first")
                    return {"ref": ref, "assignment": job["id"], "case": job.get("case"), "column": column(b), "dispatched": False}
            if name == "shared":
                raise ValueError("assign a concrete repository part card, not a shared issue")
            if column(b) == "done":
                raise ValueError("verified task; do not restart")
            if claim and claim["state"] in ("doing", "blocked"):
                raise ValueError(f'already owned by {claim["actor"]}; reconcile with that owner')
            if column(b) == "doing":
                raise ValueError("already doing outside planner; reconcile the existing assignment first")
            if any(r["actor"] == "trailblazer" and r["state"] == "doing" for r in claims.values()):
                raise ValueError("trailblazer already has active work")
            config = assignment.configuration(a.dispatch_config)
            assignment.validate(target, a.check, a.file, config)
            seconds = a.deadline_seconds if a.deadline_seconds is not None else config["deadline_seconds"]
            if seconds <= 0:
                raise ValueError("deadline_seconds must be positive")
            plan = assignment.implementation_plan(b)
            notes = json.loads(claim["notes"]) if claim else []
            notes.append({"n": len(notes)+1, "action": "assign", "text": plan})
            if target != repo:
                notes.append({"n": len(notes)+1, "action": "note",
                              "text": f"Target worktree {target} at {assignment.head(target)}; that HEAD is the case base."})
            job = {"id": "planner-"+uuid.uuid4().hex, "ref": ref, "repo": str(target),
                   "check": a.check, "files": a.file, "state": "admitting", "previous": history,
                   "deadline_seconds": seconds, "read_rounds": a.read_rounds, "plan": plan,
                   "reasoning_budget_tokens": a.reasoning_tokens,
                   "replay_reply_from": a.replay_reply_from,
                   "card": {"title": b["title"], "body": b["comments"][0]["message"],
                            "recent": [c["message"] for c in b["comments"][1:][-3:]]}}
            new_claim = {"actor": "trailblazer", "state": "doing", "plan": plan, "notes": json.dumps(notes)}
            with db:
                db.execute("INSERT OR REPLACE INTO claims VALUES (?,?,?,?,?)",
                           (ref, "trailblazer", "doing", plan, json.dumps(notes)))
                db.execute("INSERT OR REPLACE INTO assignments VALUES (?,?)", (ref, json.dumps(job)))
            mirror(repo, bug, b, new_claim)
            try:
                job["case"] = assignment.admit(job, config)
                job["state"] = "accepted"
                notes.append({"n": len(notes)+1, "action": "note",
                              "text": "Result: accepted as case "+job["case"]+"; supervised by Elixir."})
            except BaseException as error:
                job.update(state="blocked", reason=str(error) or "admission client interrupted")
                notes.append({"n": len(notes)+1, "action": "block", "text": job["reason"]})
                new_claim["state"] = "blocked"
            new_claim["notes"] = json.dumps(notes)
            with db:
                db.execute("UPDATE assignments SET data=? WHERE ref=?", (json.dumps(job), ref))
                db.execute("UPDATE claims SET state=?,notes=? WHERE ref=?", (new_claim["state"], new_claim["notes"], ref))
            mirror(repo, bug, show(repo, bug), new_claim)
            if job["state"] == "blocked":
                raise ValueError(job["reason"])
            return {"ref": ref, "assignment": job["id"], "case": job["case"], "column": "doing", "dispatched": True}
        if a.command == "sync":
            if not claim or claim["actor"] != a.actor:
                raise ValueError("only the recorded actor can repair its issue mirror")
            mirror(repo, bug, b, claim)
            return {"ref": ref, "column": claim["state"], "recorded": "sync"}
        if a.command == "start":
            if not a.plan.strip():
                raise ValueError("plan must not be empty")
            if claim and claim["state"] in ("doing", "blocked") and claim["actor"] != a.actor:
                raise ValueError(f'already owned by {claim["actor"]}; reconcile with that owner')
            if not claim and column(b) == "doing":
                raise ValueError("already doing outside planner; reconcile the existing assignment first")
            if column(b) == "done":
                raise ValueError("verified task; do not restart")
            if any(r["actor"] == a.actor and r["state"] == "doing" and r["ref"] != ref for r in claims.values()):
                raise ValueError("actor already has active work; finish, block or release it first")
            state, plan, text = "doing", a.plan, "plan: "+a.plan
        else:
            text = a.evidence if a.command == "done" else a.text
            if claim and claim["actor"] == a.actor and a.command in ("done", "block"):
                last = json.loads(claim["notes"])[-1]
                target = "done" if a.command == "done" else "blocked"
                if claim["state"] == target and last["action"] == a.command and last["text"] == text:
                    mirror(repo, bug, b, claim)
                    return {"ref": ref, "column": target, "actor": a.actor, "recorded": "sync"}
            if not claim or claim["actor"] != a.actor or claim["state"] not in ("doing", "blocked"):
                raise ValueError("start this card first; only its current actor may update it")
            plan = claim["plan"]
            if not text.strip():
                raise ValueError("checkpoint, reason or evidence must not be empty")
            state = {"note": claim["state"], "block": "blocked", "release": "todo", "done": "done"}[a.command]
        notes = json.loads(claim["notes"]) if claim else []
        notes.append({"n": len(notes)+1, "action": a.command, "text": text})
        # Claim is durable before touching the issue. A failed mirror is visible
        # on resume and is repaired by repeating the command; never auto-take over.
        with db:
            db.execute("INSERT OR REPLACE INTO claims VALUES (?,?,?,?,?)", (ref, a.actor, state, plan, json.dumps(notes)))
        mirror(repo, bug, b, {"state": state, "actor": a.actor, "notes": json.dumps(notes)})
        return {"ref": ref, "column": state, "actor": a.actor, "recorded": a.command}


if __name__ == "__main__":
    try:
        print(json.dumps(main(), separators=(",", ":")))
    except (ValueError, OSError, sqlite3.Error) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        sys.exit(1)
