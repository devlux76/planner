"""Wait for one case to finish, then release its dispatch profile. Never stop work."""
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
POLL_SECONDS = 5


def cleanup(case):
    if not re.fullmatch(r"vortex-[0-9a-f]{64}", case):
        raise ValueError("invalid case")
    with sqlite3.connect(f"file:{DATABASE}?mode=ro", uri=True) as conn:
        while True:
            row = conn.execute("SELECT status FROM task_case WHERE id=?", (case,)).fetchone()
            if row and row[0] != "open":
                break
            time.sleep(POLL_SECONDS)
    code = '''
id = "__CASE__"
if Trailblazer.Loop.CaseRecord.get(id, inline: false).status == "open",
  do: raise("case still open; leave it running")
key = {:trailblazer, :bounded_smoke_profile}
case :persistent_term.get(key, nil) do
  %{case: ^id, output_cap: _} ->
    :persistent_term.erase(key)
  _ -> raise("profile ownership unconfirmed")
end
IO.puts("owned dispatch profile released after completion")
'''.replace("__CASE__", case)
    env = os.environ | {"RELEASE_DISTRIBUTION": "name", "RELEASE_NODE": "trailblazer@127.0.0.1", "ERL_EPMD_ADDRESS": "127.0.0.1"}
    result = subprocess.run([str(RELEASE), "rpc", code], env=env, cwd=ROOT,
                            capture_output=True, text=True, timeout=30)
    record = {"case": case, "status": row[0], "cleanup_exit": result.returncode,
              "output": result.stdout, "error": result.stderr}
    (STATE / (case + ".cleanup.json")).write_text(json.dumps(record))
    return record


if __name__ == "__main__":
    record = cleanup(sys.argv[1])
    print(json.dumps(record), flush=True)
    sys.exit(record["cleanup_exit"])
