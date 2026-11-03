"""Bounded admission client. Trailblazer's Elixir companion owns supervision."""
import json
from pathlib import Path
import re
import subprocess
import time


def configuration(path):
    value = json.loads(path.read_text())
    argv = value.get("vortex_command")
    if not isinstance(argv, list) or not argv or not all(isinstance(x, str) for x in argv):
        raise ValueError("dispatch config needs vortex_command as a command array")
    if not value.get("peer") or not value.get("vortex_dir"):
        raise ValueError("dispatch config needs the admitted peer and owner-local VORTEX directory")
    seconds = value.get("deadline_seconds", 4*60*60)
    if isinstance(seconds, bool) or not isinstance(seconds, int) or seconds <= 0:
        raise ValueError("deadline_seconds must be a positive integer for the Elixir companion")
    value["deadline_seconds"] = seconds
    return value


def worktree_target(repo, path):
    """A registered worktree of `repo` other than its main checkout; its HEAD becomes the case base."""
    target = Path(path).expanduser().resolve()
    listed = subprocess.run(["git", "-C", str(repo), "worktree", "list", "--porcelain"], capture_output=True, text=True)
    if listed.returncode:
        raise ValueError("cannot list the card repository's worktrees")
    paths = [Path(line[len("worktree "):]).resolve() for line in listed.stdout.splitlines() if line.startswith("worktree ")]
    if target == Path(repo).resolve():
        raise ValueError("--worktree names the card repository itself; omit it")
    if target not in paths:
        raise ValueError("--worktree is not a registered worktree of the card repository")
    return target


def head(repo):
    out = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True)
    if out.returncode:
        raise ValueError("cannot resolve the target worktree HEAD")
    return out.stdout.strip()


def validate(repo, check, files, config):
    if check not in config.get("repos", {}).get(str(repo), []):
        raise ValueError("repository/check is not admitted in the local dispatch configuration")
    manifest = subprocess.run(["git", "-C", str(repo), "show", "HEAD:mix.exs"], capture_output=True, text=True)
    if repo.name == "trailblazer" or re.search(r"\bapp:\s*:trailblazer\b", manifest.stdout):
        raise ValueError("Trailblazer self-repair is forbidden")
    for name in files:
        path = Path(name)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise ValueError("task files must be repository-relative paths")


def implementation_plan(card):
    # Keep the latest explicit plan independently of the rolling checkpoints.
    for comment in reversed(card["comments"]):
        found = re.search(r"Implementation plan:\s*(\S[\s\S]*)", comment["message"])
        if found:
            return found.group(1).strip()
    raise ValueError("coding assignment needs an Implementation plan: with ordered changes, interfaces and tests; plan or research the card first")


def rpc(config, op, *args, timeout=10):
    try:
        result = subprocess.run(config["vortex_command"]+[op, "--dir", config["vortex_dir"], *args],
                                capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise ValueError("No admission within the client timeout; investigate the existing request before retrying") from None
    data = json.loads(result.stdout)
    if data.get("error") == "wait timed out" and op == "wait":
        return {"events": [], "cursor": int(args[args.index("--after")+1])}
    if result.returncode or data.get("error"):
        raise ValueError(data.get("error") or result.stderr.strip() or "VORTEX request failed")
    return data


def send(config, job, kind, payload, timeout):
    message = {"protocol":"trailblazer/1", "type":kind, "id":job["id"]+":"+kind,
               "request_id":job["id"], "payload":payload}
    body = "From Codex, not typed by the operator:\n"+json.dumps(message)
    if len(body.encode()) > 16384:
        raise ValueError("task card exceeds the VORTEX envelope limit; narrow the assignment")
    if not rpc(config, "send", "--peer", config["peer"], "--text", body, timeout=timeout).get("sent"):
        raise ValueError("VORTEX did not confirm the transport write")


def admit(job, config):
    # This is a bounded transport handshake, not a task lifetime watcher.
    until = time.monotonic()+config.get("admission_timeout_seconds", 60)
    def remaining():
        seconds = until-time.monotonic()
        if seconds <= 0:
            raise ValueError("No admission within the client timeout; investigate the existing request before retrying")
        return seconds
    cursor = 0
    while True:
        page = rpc(config, "read", "--after", str(cursor), timeout=remaining())
        cursor = page["cursor"]
        if not page.get("events"):
            break
    request = (job["card"]["title"].splitlines()[0][:100]+" bug:"+job["ref"].split(":")[1]+"\n\n"+
               job["card"]["body"]+"\n\nCurrent checkpoints:\n"+"\n".join(job["card"]["recent"]))
    payload = {"repo":job["repo"], "request":request, "check":job["check"], "files":job["files"],
               "planner":{"ref":job["ref"], "deadline_seconds":job["deadline_seconds"]},
               "design":["Implementation plan: "+job["plan"], "Current planner card "+job["ref"]+". Elixir owns execution, independent verification, planner updates and recovery. Never merge or push."]}
    if job.get("read_rounds") is not None:
        payload["read_rounds"] = job["read_rounds"]
    if job.get("reasoning_budget_tokens") is not None:
        payload["reasoning_budget_tokens"] = job["reasoning_budget_tokens"]
    if job.get("replay_reply_from") is not None:
        payload["replay_reply_from"] = job["replay_reply_from"]
    send(config, job, "task", payload, remaining())
    while True:
        page = rpc(config, "wait", "--after", str(cursor), "--for", "message", "--timeout", "60", timeout=remaining())
        cursor = page["cursor"]
        for event in page.get("events", []):
            if event.get("peer") != config["peer"] or event.get("kind") != "message":
                continue
            try:
                message = json.loads(event["body"].split("\n",1)[1])
            except (ValueError, KeyError, IndexError):
                continue
            if message.get("protocol") != "trailblazer/1" or message.get("request_id") != job["id"]:
                continue
            if message.get("type") == "rejected":
                raise ValueError("Trailblazer rejected the assigned task")
            if message.get("type") == "accepted":
                case = message.get("payload", {}).get("case")
                if not isinstance(case, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:._-]{0,127}", case):
                    raise ValueError("invalid case in Trailblazer admission reply")
                send(config, job, "receipt", {"message_id":message["id"]}, remaining())
                return case


def confirm_closed(job, config):
    if not job.get("case"):
        raise ValueError("previous admission is uncertain; reconcile it before a fresh assignment")
    argv = config.get("case_command", [str(Path.home()/".local/bin/trailblazer")])
    try:
        result = subprocess.run(argv+["case", job["case"]], capture_output=True, text=True, timeout=10)
    except subprocess.TimeoutExpired:
        raise ValueError("previous case is not confirmed closed; case query timed out; do not redispatch it") from None
    if result.returncode or json.loads(result.stdout).get("status") not in ("fixed", "failed", "cancelled", "unverified", "escalated"):
        raise ValueError("previous case is not confirmed closed; do not redispatch it")
