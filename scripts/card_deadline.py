"""Every card gets one hour of tool time, counted from its first case.

The launcher refuses a card whose hour is spent, and each admitted case gets
this guard: it waits for the case to close or the card's hour to end, and at
the deadline stops the case's worker. The runner then closes the case failed
("The task worker stopped: :card_hour_expired") and the bridge reports it on
the card, so post-mortem / split / fix-directly happens before any rerun.
"""
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time

ROOT = Path.home() / "projects/trailblazer"
RELEASE = ROOT / "_build/prod/rel/trailblazer/bin/trailblazer"
DATABASE = Path.home() / ".local/share/trailblazer/cases.db"
STATE = Path.home() / ".local/state/planner/trials"
CARD_SECONDS = 3600
POLL_SECONDS = 5

STOP = '''
id = "__CASE__"
case :sys.get_state(Trailblazer.Loop.Runner).active do
  {pid, _ref, ^id} ->
    Process.exit(pid, :card_hour_expired)
    Process.sleep(2000)
    if Process.alive?(pid), do: Process.exit(pid, :kill)
    IO.puts("stopped")
  _ -> IO.puts("not active")
end
'''


def card_started_at(ref, database=None):
    """Epoch seconds of the card's first case, or None if it has none yet.
    Planner writes the card only at the end of the request's title line
    ("<title> bug:<id>"); plan bodies may cite other cards, so only that
    title tag counts. Either id may be the longer prefix of the other."""
    match = re.fullmatch(r"[a-z0-9_-]+:([0-9a-f]{7,64})", ref)
    if not match:
        raise ValueError("invalid card ref")
    card = match.group(1)
    with sqlite3.connect(f"file:{database or DATABASE}?mode=ro", uri=True) as conn:
        rows = conn.execute("SELECT opened_at, json_extract(task, '$.request') FROM task_case").fetchall()
    times = []
    for opened_at, request in rows:
        tag = re.search(r" bug:([0-9a-f]{7,64})$", (request or "").split("\n", 1)[0])
        if tag and (tag.group(1).startswith(card) or card.startswith(tag.group(1))):
            times.append(opened_at)
    return min(times) / 1000 if times else None


def deadline(ref, now=None, database=None):
    """Epoch seconds when the card's hour ends; raises once it has ended."""
    now = time.time() if now is None else now
    started = card_started_at(ref, database)
    end = (now if started is None else started) + CARD_SECONDS
    if end <= now:
        spent = time.strftime("%H:%M", time.localtime(started))
        raise ValueError(f"{ref} used its {CARD_SECONDS // 60}-minute card budget (first case {spent}); "
                         "post-mortem it, then fix directly or split it into smaller cards; no relaunch")
    return end


def guard(case, end, database=None, stop=None):
    if not re.fullmatch(r"vortex-[0-9a-f]{64}", case):
        raise ValueError("invalid case")
    with sqlite3.connect(f"file:{database or DATABASE}?mode=ro", uri=True) as conn:
        while True:
            row = conn.execute("SELECT status FROM task_case WHERE id=?", (case,)).fetchone()
            if row and row[0] != "open":
                return {"case": case, "status": row[0], "stopped": False}
            if time.time() >= end:
                break
            time.sleep(min(POLL_SECONDS, max(0.0, end - time.time())))
    output = (stop or _stop)(case)
    return {"case": case, "status": "open", "stopped": output.strip() == "stopped", "output": output}


def _stop(case):
    env = os.environ | {"RELEASE_DISTRIBUTION": "name", "RELEASE_NODE": "trailblazer@127.0.0.1",
                        "ERL_EPMD_ADDRESS": "127.0.0.1"}
    return subprocess.run([str(RELEASE), "rpc", STOP.replace("__CASE__", case)], env=env, cwd=ROOT,
                          capture_output=True, text=True, timeout=30).stdout


if __name__ == "__main__":
    record = guard(sys.argv[1], float(sys.argv[2]))
    STATE.mkdir(parents=True, exist_ok=True)
    (STATE / (sys.argv[1] + ".deadline.json")).write_text(json.dumps(record))
    print(json.dumps(record), flush=True)
