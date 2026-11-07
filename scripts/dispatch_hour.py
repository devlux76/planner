"""Each dispatch gets one hour; then it stops so we look at what it taught us.

A relaunch (after a post-mortem, tool fix or split) starts a fresh hour: the
point is progress, not a lifetime budget per card. Each admitted case gets
this guard: it waits for the case to close or its hour to end, and at the
deadline stops the case's worker. The runner then closes the case failed
("The task worker stopped: :dispatch_hour_expired") and the bridge reports it
on the card.
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
HOUR_SECONDS = 3600
POLL_SECONDS = 5

# A running case's worker is stopped; a case still queued in the VORTEX
# bridge (waiting for the model resource: live 2026-11-06 it never reached
# the runner and the guard left it open) is closed as cancelled, the way the
# bridge cancels a caller's request before execution.
STOP = '''
id = "__CASE__"
case {:sys.get_state(Trailblazer.Loop.Runner).active, Trailblazer.Vortex.Store.get(id)} do
  {{pid, _ref, ^id}, _} ->
    Process.exit(pid, :dispatch_hour_expired)
    Process.sleep(2000)
    if Process.alive?(pid), do: Process.exit(pid, :kill)
    IO.puts("stopped")
  {_, %{state: "waiting_resource"}} ->
    :ok = Trailblazer.Loop.CaseRecord.close(id, %{case: id, status: :cancelled,
      summary: "Dispatch hour expired before execution: still waiting for the model resource."})
    IO.puts("stopped")
  _ -> IO.puts("not active")
end
'''


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
