"""No bare relaunch: every earlier case of a card needs its post-mortem first.

Operator process (2026-11-06): when a dispatch fails or reaches its hour, write
a full post-mortem on the card (was the card too large or underspecified, did
the model or the harness fail), fix what it points at, and only then relaunch.
After three post-mortems the card is finished by hand, closed, and the next
card begins. A post-mortem is a planner note whose text starts "Post-mortem".
"""
import json
from pathlib import Path
import re
import subprocess

REPOS_FILE = Path.home() / ".config/bug-watch/repos"
LIMIT = 3
CASE = re.compile(r"Result: accepted as case vortex-[0-9a-f]{64}")
POSTMORTEM = re.compile(r"^planner note \([^)]*\)[^:]*: Post-mortem", re.IGNORECASE)


def counts(messages):
    """(cases, post-mortems) recorded in a card's comments."""
    cases = sum(1 for m in messages if CASE.search(m))
    postmortems = sum(1 for m in messages if POSTMORTEM.match(m))
    return cases, postmortems


def verdict(cases, postmortems):
    """None when a launch may go ahead, else why not."""
    if postmortems >= LIMIT:
        return (f"{postmortems} post-mortems already: finish this card by hand, close it with "
                "evidence, and move to the next card (operator process); no relaunch")
    if cases > postmortems:
        return (f"case {postmortems + 1} of this card has no post-mortem: note "
                "'Post-mortem N: too large? underspecified? model? harness? -> fix' first; no bare relaunch")
    return None


def messages(ref, repos_file=None):
    name, bug = ref.split(":", 1)
    repo = None
    for line in (repos_file or REPOS_FILE).read_text().splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            path = Path(line.strip()).expanduser().resolve()
            if ("shared" if path.name == ".bugs" else path.name) == name:
                repo = path
    if repo is None:
        raise ValueError(f"unknown repository {name!r}")
    out = subprocess.run(["git", "-C", str(repo), "bug", "bug", "show", bug, "--format", "json"],
                         capture_output=True, text=True, check=True, timeout=60).stdout
    return [c.get("message") or "" for c in json.loads(out)["comments"]]


def check(ref, repos_file=None):
    """Raise ValueError when the card may not be launched now."""
    reason = verdict(*counts(messages(ref, repos_file)))
    if reason:
        raise ValueError(f"{ref}: {reason}")
