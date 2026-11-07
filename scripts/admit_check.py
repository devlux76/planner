"""Admit one check command for a registered worktree, in both places that must agree.

A dispatch needs the exact check string in planner's Trailblazer config
(repos[worktree]) and in Trailblazer's VORTEX config (the peer that serves the
worktree: repos[worktree], plus compilation[worktree][check] when the check has
a compile step). Hand edits got this wrong (2026-11-06: a compile step written
at the top level of `compilation` made Trailblazer refuse the whole VORTEX
config, so its task runner never started). This writes both atomically and
checks the shape Trailblazer validates.

Usage: admit_check.py WORKTREE CHECK [--compile CMD] [--restart]
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time

PLANNER = Path.home() / ".config/planner/trailblazer.json"
VORTEX = Path.home() / ".config/trailblazer/vortex.json"


def _write(path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    os.replace(tmp, path)


def _check_shape(peer):
    repos = peer.get("repos", {})
    for repo, policy in peer.get("compilation", {}).items():
        if repo not in repos or not isinstance(policy, dict):
            raise ValueError(f"compilation entry {repo!r} is not a repo of this peer")
        for check, command in policy.items():
            if check not in repos[repo] or not isinstance(command, str) or not command.strip():
                raise ValueError(f"compilation[{repo!r}][{check!r}] is not an admitted check")


def admit(worktree, check, compile_cmd=None, planner=PLANNER, vortex=VORTEX):
    worktree = str(Path(worktree).expanduser().resolve())
    if not check.strip():
        raise ValueError("empty check")
    if compile_cmd is not None and not compile_cmd.strip():
        raise ValueError("empty compile command (Trailblazer refuses the whole VORTEX config)")
    p = json.loads(planner.read_text())
    if worktree not in p.get("repos", {}):
        raise ValueError(f"{worktree} is not a registered planner repo")
    v = json.loads(vortex.read_text())
    peers = [peer for peer in v.get("peers", []) if worktree in peer.get("repos", {})]
    if not peers:
        raise ValueError(f"no VORTEX peer serves {worktree}")
    if check not in p["repos"][worktree]:
        p["repos"][worktree].append(check)
    for peer in peers:
        if check not in peer["repos"][worktree]:
            peer["repos"][worktree].append(check)
        if compile_cmd:
            peer.setdefault("compilation", {}).setdefault(worktree, {})[check] = compile_cmd
        _check_shape(peer)
    _write(vortex, v)
    _write(planner, p)
    return {"worktree": worktree, "check": check, "compile": compile_cmd, "peers": len(peers)}


def restart(wait=30):
    """Restart Trailblazer and fail loudly if it rejects its VORTEX config."""
    since = time.strftime("%Y-%m-%d %H:%M:%S")
    subprocess.run(["systemctl", "--user", "restart", "trailblazer"], check=True)
    time.sleep(wait)
    log = subprocess.run(["journalctl", "--user", "-u", "trailblazer", "--since", since, "--no-pager"],
                         capture_output=True, text=True, check=True).stdout
    # Trailblazer logs "invalid local VORTEX configuration" (settings.ex)
    if "invalid local vortex configuration" in log.lower():
        raise RuntimeError("Trailblazer rejected the VORTEX config after restart")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("worktree")
    parser.add_argument("check")
    parser.add_argument("--compile", dest="compile_cmd")
    parser.add_argument("--restart", action="store_true")
    args = parser.parse_args()
    result = admit(args.worktree, args.check, args.compile_cmd)
    if args.restart:
        restart()
        result["restarted"] = True
    print(json.dumps(result))
